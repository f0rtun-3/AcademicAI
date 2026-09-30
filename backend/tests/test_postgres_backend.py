"""The PostgreSQL backend itself (db/postgres.py and schema_postgres.sql).

What it must keep from SQLite - that the application cannot tell the engines
apart - is tested on both engines in test_database_portability.py. This file
tests the mechanics PostgreSQL needs to get there: SQL translation, the
app-wide write lock that stands in for BEGIN IMMEDIATE, error mapping, the
migration runner, concurrent start-up, and that the schema is the same schema.

Needs ACADEMICAI_TEST_POSTGRES_URL; skipped (and reported skipped) without it,
apart from the translation tests, which need only the driver.
"""
import re
import sqlite3
import threading
import time
from contextlib import contextmanager

import pytest

psycopg = pytest.importorskip("psycopg")

from academicai.db import postgres  # noqa: E402
from academicai.db.connection import (DatabaseBusy, connect as sqlite_connect,  # noqa: E402
                                      init_schema, query_one, transaction)
from tests import pg_support  # noqa: E402

pytestmark = pytest.mark.postgres


@contextmanager
def holding_write_lock(url):
    """Another connection inside an immediate transaction, holding the lock."""
    holder = postgres.connect(url)
    try:
        with holder.transaction(immediate=True):
            yield holder
    finally:
        holder.close()


def _started(fn):
    """Run fn in a thread; return (thread, outcome list)."""
    outcome = []

    def run():
        try:
            outcome.append(fn())
        except Exception as exc:  # recorded for the assertion, never swallowed
            outcome.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    return thread, outcome


# ── SQL translation (no database needed) ────────────────────────────────────

def test_question_marks_become_psycopg_placeholders():
    assert postgres.translate_sql("SELECT * FROM t WHERE a = ? AND b IN (?, ?)") == \
        "SELECT * FROM t WHERE a = %s AND b IN (%s, %s)"


def test_question_marks_in_literals_identifiers_and_comments_are_left_alone():
    sql = ("SELECT '?' AS q, 'it''s ?' AS r, \"odd?\" FROM t -- why?\n"
           "WHERE x = ? /* not ? this */ AND y = ?")
    assert postgres.translate_sql(sql) == (
        "SELECT '?' AS q, 'it''s ?' AS r, \"odd?\" FROM t -- why?\n"
        "WHERE x = %s /* not ? this */ AND y = %s")


def test_every_percent_sign_is_escaped_for_the_driver():
    assert postgres.translate_sql("SELECT 'a%b' WHERE n LIKE '%z' AND m = ? AND 5 % 2 = 1") == \
        "SELECT 'a%%b' WHERE n LIKE '%%z' AND m = %s AND 5 %% 2 = 1"
    assert postgres.translate_sql("SELECT 1 -- 100%\n") == "SELECT 1 -- 100%%\n"


# ── Connection behaviour ────────────────────────────────────────────────────

@pytest.fixture
def pg(pg_schema):
    """A migrated schema (via a real app start) and its url."""
    pg_support.make_pg_app(pg_schema)
    return pg_schema


def test_lastrowid_is_refused_rather_than_faked(pg):
    conn = postgres.connect(pg)
    try:
        cursor = conn.execute("SELECT 1")
        with pytest.raises(NotImplementedError, match="insert_returning_id"):
            cursor.lastrowid
    finally:
        conn.close()


def test_a_connection_is_idle_outside_transactions_and_joins_an_outer_one(pg):
    conn = postgres.connect(pg)
    try:
        assert not conn.in_transaction
        conn.execute("SELECT 1")
        assert not conn.in_transaction            # autocommit, like sqlite3's None
        with transaction(conn) as outer:
            assert conn.in_transaction
            with transaction(conn) as inner:
                assert inner is outer
        assert not conn.in_transaction
    finally:
        conn.close()


def test_a_pooled_connection_goes_back_clean_after_a_failed_request(pg):
    app = pg_support.make_pg_app(pg)
    with app.app_context():
        from academicai.db.connection import get_db
        conn = get_db()
        conn.raw.execute("BEGIN")                 # left open, as by a crash mid-request
        raw = conn.raw
    # close_db ran at teardown: the transaction was rolled back, not pooled.
    assert raw.info.transaction_status == psycopg.pq.TransactionStatus.IDLE


# ── The write lock: BEGIN IMMEDIATE's guarantee on PostgreSQL ───────────────

def test_an_immediate_transaction_holds_the_write_lock_until_it_ends(pg):
    fast = postgres.connect(pg, lock_timeout_ms=100)
    try:
        with holding_write_lock(pg):
            with pytest.raises(DatabaseBusy):
                with transaction(fast):
                    pass
            # Reads outside a transaction take no lock, as on SQLite.
            assert fast.execute("SELECT COUNT(*) FROM universities").fetchone()[0] == 4
        with transaction(fast):                   # released at COMMIT/ROLLBACK
            pass
    finally:
        fast.close()


def test_a_write_outside_a_transaction_also_waits_for_the_lock(pg):
    fast = postgres.connect(pg, lock_timeout_ms=100)
    try:
        with holding_write_lock(pg):
            with pytest.raises(DatabaseBusy):
                fast.execute("UPDATE universities SET name = name WHERE id = ?", (1,))
        fast.execute("UPDATE universities SET name = name WHERE id = ?", (1,))
    finally:
        fast.close()


def test_a_waiting_writer_proceeds_as_soon_as_the_holder_commits(pg):
    waiter = postgres.connect(pg, lock_timeout_ms=10_000)
    try:
        with holding_write_lock(pg) as holder:
            holder.execute("UPDATE universities SET name = 'Renamed' WHERE id = ?", (1,))

            def read_under_lock():
                with transaction(waiter):
                    return waiter.execute(
                        "SELECT name FROM universities WHERE id = ?", (1,)).fetchone()[0]

            thread, outcome = _started(read_under_lock)
            time.sleep(0.3)
            assert thread.is_alive(), "the second writer did not wait for the lock"
        thread.join(timeout=10)
        # It read AFTER the holder committed: the decision sees the new state.
        assert outcome == ["Renamed"]
    finally:
        waiter.close()


def test_the_lock_is_released_when_its_connection_is_lost(pg):
    holder = postgres.connect(pg)
    fast = postgres.connect(pg, lock_timeout_ms=2000)
    try:
        holder.raw.execute("BEGIN")
        holder.raw.execute("SELECT pg_advisory_xact_lock(%s)", (postgres.WRITE_LOCK_KEY,))
        pid = holder.raw.info.backend_pid
        with psycopg.connect(pg, autocommit=True) as admin:
            admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
        with transaction(fast):
            pass
    finally:
        fast.close()
        try:
            holder.raw.close()
        except Exception:
            pass


def test_read_then_write_decisions_are_serialised(pg):
    """The guarantee the whole application relies on: a value read inside a
    transaction cannot be changed by another writer before this one writes.
    Eight concurrent read-increment-write transactions must lose nothing."""
    setup = postgres.connect(pg)
    setup.execute("CREATE TABLE counter (id INTEGER PRIMARY KEY, n INTEGER NOT NULL)")
    setup.execute("INSERT INTO counter VALUES (1, 0)")
    setup.close()

    def increment(immediate):
        conn = postgres.connect(pg, lock_timeout_ms=20_000)
        try:
            with conn.transaction(immediate=immediate):
                n = conn.execute("SELECT n FROM counter WHERE id = 1").fetchone()[0]
                time.sleep(0.05)                    # widen the window
                conn.execute("UPDATE counter SET n = ? WHERE id = 1", (n + 1,))
        finally:
            conn.close()

    def run(immediate, threads=8):
        barrier = threading.Barrier(threads)

        def worker():
            barrier.wait()
            increment(immediate)
        pool = [threading.Thread(target=worker) for _ in range(threads)]
        for t in pool:
            t.start()
        for t in pool:
            t.join()
        conn = postgres.connect(pg)
        try:
            n = conn.execute("SELECT n FROM counter WHERE id = 1").fetchone()[0]
            conn.execute("UPDATE counter SET n = 0 WHERE id = 1")
            return n
        finally:
            conn.close()

    assert run(immediate=True) == 8
    # The control: the same transactions without the lock lose updates, so the
    # lock - not luck, and not PostgreSQL's default isolation - is what holds.
    assert run(immediate=False) < 8


# ── Error mapping ───────────────────────────────────────────────────────────

def test_a_lost_connection_is_database_busy_not_a_crash(pg):
    conn = postgres.connect(pg)
    try:
        with psycopg.connect(pg, autocommit=True) as admin:
            admin.execute("SELECT pg_terminate_backend(%s)", (conn.raw.info.backend_pid,))
        with pytest.raises(DatabaseBusy):
            conn.execute("SELECT 1")
    finally:
        try:
            conn.raw.close()
        except Exception:
            pass


@pytest.mark.parametrize("error", ["DeadlockDetected", "SerializationFailure",
                                   "LockNotAvailable", "QueryCanceled"])
def test_contention_errors_are_database_busy(error):
    raised = getattr(psycopg.errors, error)("simulated")

    class Raw:
        class info:
            transaction_status = psycopg.pq.TransactionStatus.IDLE

        def cursor(self, **_kw):
            class Cursor:
                def execute(self, *_a):
                    raise raised
            return Cursor()

    with pytest.raises(DatabaseBusy) as excinfo:
        postgres.PgConnection(Raw()).execute("SELECT 1")
    assert excinfo.value.__cause__ is raised


def test_other_database_errors_are_not_disguised(pg):
    conn = postgres.connect(pg)
    try:
        with pytest.raises(psycopg.errors.UndefinedTable):
            conn.execute("SELECT * FROM no_such_table")
        with pytest.raises(psycopg.IntegrityError):
            conn.execute("INSERT INTO universities (name, created_at, timezone) "
                         "VALUES (?, 'now', 'Africa/Lagos')", ("Babcock University",))
    finally:
        conn.close()


def test_api_lock_timeout_is_503_and_constraint_failure_is_409(pg_schema):
    app = pg_support.make_pg_app(pg_schema, SQLITE_BUSY_TIMEOUT_MS=100)

    @app.post("/__test/duplicate-university")
    def duplicate():
        from academicai.db.connection import execute
        execute("INSERT INTO universities (name, created_at, timezone) "
                "VALUES ('Babcock University', 'now', 'Africa/Lagos')")
        return {}

    client = app.test_client()
    resp = client.post("/__test/duplicate-university")
    assert resp.status_code == 409
    assert resp.get_json() == {"error": "conflict",
                               "message": "That operation conflicts with existing data."}

    with holding_write_lock(pg_schema):
        resp = client.post("/api/auth/register", json={
            "full_name": "Locked Out", "email": "locked@student.babcock.edu.ng",
            "password": "Password123", "confirm_password": "Password123",
            "university": "Babcock University", "department": "Software Engineering",
            "level": "200", "academic_session": "2026/2027",
            "student_id_number": "BU/SEN/0001",
            "accept_terms": True, "terms_version": _terms_version()})
    assert resp.status_code == 503, resp.get_json()
    assert resp.get_json()["error"] == "database_busy"


def _terms_version():
    from academicai.services.auth_service import TERMS_VERSION
    return TERMS_VERSION


# ── Migrations ──────────────────────────────────────────────────────────────

def _versions(url):
    conn = postgres.connect(url)
    try:
        return [tuple(r) for r in conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version").fetchall()]
    finally:
        conn.close()


def test_the_baseline_is_applied_once_and_a_restart_changes_nothing(pg_schema):
    pg_support.make_pg_app(pg_schema)
    assert _versions(pg_schema) == [(1, "baseline")]
    pg_support.make_pg_app(pg_schema)                     # second start
    conn = postgres.connect(pg_schema)
    try:
        assert postgres.migrate(conn, "now") == []
        assert conn.execute("SELECT COUNT(*) FROM universities").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM university_email_domains").fetchone()[0] == 4
    finally:
        conn.close()
    assert _versions(pg_schema) == [(1, "baseline")]


def test_a_numbered_migration_is_applied_once(pg_schema, tmp_path, monkeypatch):
    pg_support.make_pg_app(pg_schema)
    (tmp_path / "0002_add_nickname.sql").write_text(
        "ALTER TABLE users ADD COLUMN nickname TEXT;")
    (tmp_path / "README.txt").write_text("not a migration")
    monkeypatch.setattr(postgres, "MIGRATIONS_DIR", str(tmp_path))
    pg_support.make_pg_app(pg_schema)
    pg_support.make_pg_app(pg_schema)
    assert _versions(pg_schema) == [(1, "baseline"), (2, "add_nickname")]
    conn = postgres.connect(pg_schema)
    try:
        assert conn.execute("SELECT COUNT(*) FROM information_schema.columns WHERE "
                            "table_schema = current_schema() AND table_name = 'users' "
                            "AND column_name = 'nickname'").fetchone()[0] == 1
    finally:
        conn.close()


def test_a_failing_migration_changes_nothing_and_stops_the_start(pg_schema, tmp_path,
                                                                 monkeypatch):
    pg_support.make_pg_app(pg_schema)
    (tmp_path / "0002_half_done.sql").write_text(
        "ALTER TABLE users ADD COLUMN nickname TEXT;\nSELECT no_such_function();")
    monkeypatch.setattr(postgres, "MIGRATIONS_DIR", str(tmp_path))
    with pytest.raises(psycopg.Error):
        pg_support.make_pg_app(pg_schema)
    assert _versions(pg_schema) == [(1, "baseline")]
    conn = postgres.connect(pg_schema)
    try:
        assert conn.execute("SELECT COUNT(*) FROM information_schema.columns WHERE "
                            "table_schema = current_schema() AND table_name = 'users' "
                            "AND column_name = 'nickname'").fetchone()[0] == 0
    finally:
        conn.close()


def test_start_up_still_refuses_a_university_without_a_valid_timezone(pg):
    """The start-up data steps run on PostgreSQL too (the SQLite version of
    this lives in test_academic_timezone, on a legacy SQLite file)."""
    conn = postgres.connect(pg)
    try:
        conn.execute("INSERT INTO universities (name, created_at, timezone) "
                     "VALUES ('Olympus Polytechnic', 'now', 'Mars/Olympus')")
    finally:
        conn.close()
    with pytest.raises(RuntimeError, match="Olympus Polytechnic"):
        pg_support.make_pg_app(pg)


# ── Concurrent start-up (API and worker) ────────────────────────────────────

def test_api_and_workers_starting_together_migrate_exactly_once(pg_schema):
    starters = 6
    barrier = threading.Barrier(starters)
    results = [None] * starters

    def start(index):
        try:
            barrier.wait(timeout=10)
            app = pg_support.make_pg_app(pg_schema)
            if index % 2:                          # the worker runs its jobs at once
                with app.app_context():
                    from academicai.worker.jobs import run_once
                    outcome = run_once()
                    assert not [v for v in outcome.values()
                                if isinstance(v, dict) and "error" in v], outcome
            results[index] = "ok"
        except Exception as exc:
            results[index] = f"{type(exc).__name__}: {exc}"

    threads = [threading.Thread(target=start, args=(i,)) for i in range(starters)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert results == ["ok"] * starters
    assert _versions(pg_schema) == [(1, "baseline")]
    conn = postgres.connect(pg_schema)
    try:
        assert conn.execute("SELECT COUNT(*) FROM universities").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM university_email_domains").fetchone()[0] == 4
    finally:
        conn.close()


def test_a_starting_process_waits_for_another_ones_migration(pg_schema):
    holder = postgres.connect(pg_schema)
    try:
        with holder.startup_lock():
            thread, outcome = _started(lambda: pg_support.make_pg_app(pg_schema))
            time.sleep(0.5)
            assert thread.is_alive(), "start-up did not wait for the start-up lock"
            assert not _schema_has("universities", pg_schema)
        thread.join(timeout=30)
        assert len(outcome) == 1 and not isinstance(outcome[0], Exception), outcome
        assert _versions(pg_schema) == [(1, "baseline")]
    finally:
        holder.close()


def _schema_has(table, url):
    conn = postgres.connect(url)
    try:
        return conn.execute("SELECT to_regclass(?) IS NOT NULL", (table,)).fetchone()[0]
    finally:
        conn.close()


# ── The schema is the same schema ───────────────────────────────────────────

def _sqlite_shape():
    conn = sqlite_connect(":memory:", wal=False)
    init_schema(conn)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    shape = {"columns": {}, "not_null": set(), "defaults": {}, "foreign_keys": set(),
             "unique": set(), "checks": {}}
    for table in tables:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        shape["columns"][table] = [c["name"] for c in cols]
        for c in cols:
            if c["notnull"] or c["pk"]:
                shape["not_null"].add((table, c["name"]))
            if c["dflt_value"] is not None:
                shape["defaults"][(table, c["name"])] = c["dflt_value"]
        for fk in conn.execute(f"PRAGMA foreign_key_list({table})"):
            shape["foreign_keys"].add((table, fk["from"], fk["table"], fk["to"]))
        for index in conn.execute(f"PRAGMA index_list({table})"):
            if index["unique"] and index["origin"] != "pk":
                columns = tuple(i["name"] for i in conn.execute(
                    f"PRAGMA index_info({index['name']})"))
                shape["unique"].add((table, columns, bool(index["partial"])))
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?",
                           (table,)).fetchone()[0]
        for column, values in re.findall(r"CHECK\s*\((\w+) IN \(([^)]*)\)\)", sql):
            shape["checks"][(table, column)] = set(re.findall(r"'([^']*)'", values))
    conn.close()
    return shape


def _postgres_shape(url):
    conn = postgres.connect(url)
    q = lambda sql: conn.execute(sql).fetchall()  # noqa: E731
    shape = {"columns": {}, "not_null": set(), "defaults": {}, "foreign_keys": set(),
             "unique": set(), "checks": {}}
    for table, column, nullable, default in q(
            """SELECT table_name, column_name, is_nullable, column_default
               FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name <> 'schema_migrations'
               ORDER BY table_name, ordinal_position"""):
        shape["columns"].setdefault(table, []).append(column)
        if nullable == "NO":
            shape["not_null"].add((table, column))
        if default is not None:
            shape["defaults"][(table, column)] = re.sub(r"::\w+$", "", default)
    for table, column, ref_table, ref_column in q(
            """SELECT c.conrelid::regclass::text, a.attname,
                      c.confrelid::regclass::text, af.attname
               FROM pg_constraint c
               JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
               JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = c.confkey[1]
               WHERE c.contype = 'f' AND c.connamespace = current_schema()::regnamespace"""):
        shape["foreign_keys"].add((table, column, ref_table, ref_column))
    for table, definition in q(
            """SELECT tablename, indexdef FROM pg_indexes
               WHERE schemaname = current_schema() AND indexdef LIKE 'CREATE UNIQUE%'
                 AND indexname NOT LIKE '%_pkey'"""):
        columns = re.search(r"USING btree \(([^)]*)\)", definition).group(1)
        shape["unique"].add((table, tuple(c.strip() for c in columns.split(",")),
                             " WHERE " in definition))
    for table, definition in q(
            """SELECT conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint
               WHERE contype = 'c' AND connamespace = current_schema()::regnamespace"""):
        column = re.search(r"\(\((\w+)", definition).group(1)
        shape["checks"][(table, column)] = set(re.findall(r"'([^']*)'::text", definition))
    conn.close()
    return shape


def test_the_postgresql_schema_matches_the_sqlite_schema(pg):
    sqlite_shape, pg_shape = _sqlite_shape(), _postgres_shape(pg)
    assert pg_shape["columns"] == sqlite_shape["columns"]
    assert pg_shape["not_null"] == sqlite_shape["not_null"]
    assert pg_shape["defaults"] == sqlite_shape["defaults"]
    assert pg_shape["foreign_keys"] == sqlite_shape["foreign_keys"]
    assert pg_shape["unique"] == sqlite_shape["unique"]
    assert pg_shape["checks"] == sqlite_shape["checks"]
    assert len(pg_shape["columns"]) == 27


def test_the_baseline_ids_are_bigint_identities(pg):
    conn = postgres.connect(pg)
    try:
        rows = conn.execute(
            """SELECT table_name, data_type, is_identity FROM information_schema.columns
               WHERE table_schema = current_schema() AND column_name = 'id'
                 AND table_name <> 'schema_migrations'""").fetchall()
    finally:
        conn.close()
    assert len(rows) == 27
    assert {(r[1], r[2]) for r in rows} == {("bigint", "YES")}


def test_sqlite_is_untouched_by_the_postgresql_backend():
    """The SQLite path never imports the driver's connection types."""
    conn = sqlite_connect(":memory:", wal=False)
    try:
        assert isinstance(conn, sqlite3.Connection)
        init_schema(conn)
        with transaction(conn):
            conn.execute("UPDATE universities SET name = name")
        assert query_one("SELECT COUNT(*) AS n FROM universities", conn=conn)["n"] == 4
    finally:
        conn.close()
