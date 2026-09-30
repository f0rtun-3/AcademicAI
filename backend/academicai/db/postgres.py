"""PostgreSQL backend: a connection that behaves like the sqlite3 one.

The application talks to its database through connection.py's small API -
execute(), query_one(), query_all(), insert_returning_id(), transaction() and,
in a few places, conn.execute() directly - all written against sqlite3's
behaviour. This module makes a PostgreSQL connection keep that behaviour, so
no service has to know which engine is underneath:

  PLACEHOLDERS  `?` becomes psycopg's `%s`, outside string literals and
                comments, and a literal `%` is doubled so psycopg does not
                read it as a placeholder (translate_sql).
  ROWS          Row reads like sqlite3.Row: by column name (case-insensitive,
                first matching column wins), by position, keys(), dict(row).
  IDS           insert_returning_id appends RETURNING id. A cursor's
                lastrowid is NOT emulated - it raises, rather than returning
                a number that means nothing in PostgreSQL.
  ERRORS        lock timeouts, deadlocks, serialisation failures and lost
                connections become connection.DatabaseBusy (503), as SQLite's
                lock failures do. IntegrityError is psycopg's own, and the app
                maps it to the same 409 as sqlite3's.

TRANSACTIONS AND THE WRITE LOCK
-------------------------------
SQLite's BEGIN IMMEDIATE takes the database's single write lock BEFORE the
first read, so every read-then-write decision in the application (a rep
check before a write, a ballot closing, a membership approval, the outbox
claim) is made against state no other writer can change until it commits.
PostgreSQL's BEGIN takes no such lock. To keep exactly that guarantee, every
immediate transaction here begins by taking ONE app-wide transaction-scoped
advisory lock (WRITE_LOCK_KEY):

    BEGIN; SELECT pg_advisory_xact_lock(WRITE_LOCK_KEY); ...reads, writes...; COMMIT

and a write statement run outside any transaction - which on SQLite is its
own implicit transaction, waiting on the same write lock - is wrapped the
same way. Reads outside a transaction take nothing, as on SQLite. The lock
is released at COMMIT or ROLLBACK, including when a connection is lost.

Writes are therefore serialised across every connection, thread and process
(API and worker), exactly as they are on SQLite today. Narrower locking (per
community) is a possible later optimisation; it is deliberately not part of
the move to PostgreSQL. lock_timeout (from ACADEMICAI_BUSY_TIMEOUT_MS) bounds
the wait, and running out of it is DatabaseBusy, like SQLite's busy_timeout.

psycopg is imported only by this module, and this module only when the
postgresql backend is selected, so SQLite development needs no driver.
"""
import atexit
import os
import re
import threading
from contextlib import contextmanager
from functools import lru_cache

import psycopg
from psycopg import errors as pg_errors
from psycopg.conninfo import make_conninfo
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool

from .connection import DatabaseBusy

# Advisory lock keys (any fixed 64-bit integers; the same in every process).
WRITE_LOCK_KEY = 4_107_203_001     # every read-then-write transaction
STARTUP_LOCK_KEY = 4_107_203_002   # schema migration + start-up data steps

BASELINE_PATH = os.path.join(os.path.dirname(__file__), "schema_postgres.sql")
MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations_postgres")

# Infrastructure contention, never a business error (spec 32).
_BUSY_ERRORS = (
    pg_errors.LockNotAvailable,      # lock_timeout ran out (55P03)
    pg_errors.DeadlockDetected,      # 40P01
    pg_errors.SerializationFailure,  # 40001
    pg_errors.QueryCanceled,         # statement cancelled / statement_timeout
    psycopg.OperationalError,        # the server went away
)

IntegrityError = psycopg.IntegrityError


# ── SQL translation ─────────────────────────────────────────────────────────

@lru_cache(maxsize=4096)
def translate_sql(sql):
    """sqlite3 paramstyle -> psycopg paramstyle.

    `?` outside quotes and comments becomes `%s`; every `%` becomes `%%`,
    because psycopg parses `%` everywhere in a query that has parameters -
    inside string literals too. Quoted text and comments are otherwise left
    exactly as written, so a `?` inside a literal stays a question mark.
    """
    out = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:   # '' or "" escape
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i:j + 1].replace("%", "%%"))
            i = j + 1
        elif ch == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j == -1 else j
            out.append(sql[i:j].replace("%", "%%"))
            i = j
        elif ch == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append(sql[i:j].replace("%", "%%"))
            i = j
        elif ch == "?":
            out.append("%s")
            i += 1
        elif ch == "%":
            out.append("%%")
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


_WRITE_RE = re.compile(r"^\s*(?:--[^\n]*\n\s*|/\*.*?\*/\s*)*(INSERT|UPDATE|DELETE)\b",
                       re.IGNORECASE | re.DOTALL)


def _is_write(sql):
    return _WRITE_RE.match(sql) is not None


# ── Rows ────────────────────────────────────────────────────────────────────

class Row:
    """A result row that reads like sqlite3.Row.

    row["name"] (case-insensitive; the FIRST column of that name wins, as in
    sqlite3), row[0], row.keys(), dict(row), len(row), iteration over the
    values, and equality with another Row.
    """

    __slots__ = ("_names", "_index", "_values")

    def __init__(self, names, index, values):
        self._names = names
        self._index = index
        self._values = values

    def keys(self):
        return list(self._names)

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._values[key]
        try:
            return self._values[self._index[key.lower()]]
        except KeyError:
            raise IndexError("No item with that key") from None

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __eq__(self, other):
        return (isinstance(other, Row) and self._names == other._names
                and tuple(self._values) == tuple(other._values))

    def __hash__(self):
        return hash((tuple(self._names), tuple(self._values)))

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Row({dict(zip(self._names, self._values))!r})"


def _row_factory(cursor):
    names = [column.name for column in (cursor.description or ())]
    index = {}
    for position, name in enumerate(names):
        index.setdefault(name.lower(), position)   # first wins, like sqlite3.Row
    return lambda values: Row(names, index, values)


class Cursor:
    """The parts of a sqlite3 cursor the application uses."""

    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        raise NotImplementedError(
            "lastrowid has no meaning in PostgreSQL; use "
            "connection.insert_returning_id(), which uses INSERT ... RETURNING id.")

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


# ── The connection ──────────────────────────────────────────────────────────

class PgConnection:
    """A psycopg connection presented the way the application uses sqlite3.

    The underlying connection is in autocommit mode, like sqlite3 with
    isolation_level=None: nothing is in a transaction until transaction()
    begins one, and a single statement outside one commits on its own.
    """

    dialect = "postgresql"

    def __init__(self, raw, release=None):
        self.raw = raw
        self._release = release

    @property
    def in_transaction(self):
        return self.raw.info.transaction_status != TransactionStatus.IDLE

    def _run(self, sql, params):
        cursor = self.raw.cursor(row_factory=_row_factory)
        try:
            if params:
                cursor.execute(translate_sql(sql), tuple(params))
            else:
                cursor.execute(sql)
        except _BUSY_ERRORS as exc:
            raise DatabaseBusy(str(exc)) from exc
        return Cursor(cursor)

    def execute(self, sql, params=()):
        # A write outside a transaction is its own transaction on SQLite and
        # waits for the write lock; here it takes the same app-wide lock.
        if not self.in_transaction and _is_write(sql):
            with self.transaction(immediate=True):
                return self._run(sql, params)
        return self._run(sql, params)

    def insert_returning_id(self, sql, params=()):
        statement = sql.rstrip().rstrip(";") + " RETURNING id"
        return self.execute(statement, params).fetchone()[0]

    # -- transactions --------------------------------------------------------

    def _begin(self, immediate):
        try:
            self.raw.execute("BEGIN")
            if immediate:
                self.raw.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK_KEY,))
        except _BUSY_ERRORS as exc:
            self._rollback_quietly()
            raise DatabaseBusy(str(exc)) from exc

    def _rollback_quietly(self):
        try:
            self.raw.execute("ROLLBACK")
        except psycopg.Error:
            pass

    @contextmanager
    def transaction(self, immediate=True):
        """One transaction; joins an outer one rather than nesting, exactly
        as connection.transaction does on SQLite."""
        if self.in_transaction:
            yield self
            return
        self._begin(immediate)
        try:
            yield self
        except BaseException:
            self._rollback_quietly()
            raise
        else:
            try:
                self.raw.execute("COMMIT")
            except _BUSY_ERRORS as exc:
                self._rollback_quietly()
                raise DatabaseBusy(str(exc)) from exc

    @contextmanager
    def startup_lock(self):
        """Hold the start-up lock (session-scoped) for schema migration and the
        start-up data steps, so an API and a worker starting together take
        turns instead of racing to create the same tables and rows."""
        self.raw.execute("SELECT pg_advisory_lock(%s)", (STARTUP_LOCK_KEY,))
        try:
            yield self
        finally:
            # A lost connection has released the lock already; failing to say
            # so must not hide the error that got us here.
            try:
                self.raw.execute("SELECT pg_advisory_unlock(%s)", (STARTUP_LOCK_KEY,))
            except psycopg.Error:
                pass

    def close(self):
        if self.in_transaction:
            self._rollback_quietly()
        if self._release is not None:
            self._release(self.raw)
            self._release = None
        else:
            self.raw.close()


# ── Connecting ──────────────────────────────────────────────────────────────

def _session_settings(raw, lock_timeout_ms):
    raw.execute(f"SET lock_timeout = {int(lock_timeout_ms)}")
    raw.execute("SET application_name = 'academicai'")


def connect(url, lock_timeout_ms=5000):
    """A dedicated connection (start-up, maintenance). Not pooled."""
    raw = psycopg.connect(url, autocommit=True)
    _session_settings(raw, lock_timeout_ms)
    return PgConnection(raw)


_pools = {}
_pools_lock = threading.Lock()


def _pool_for(url, lock_timeout_ms, min_size, max_size):
    # Keyed by process id too: a pool must never cross a fork (gunicorn).
    key = (url, int(lock_timeout_ms), os.getpid())
    with _pools_lock:
        pool = _pools.get(key)
        if pool is None:
            pool = ConnectionPool(
                url, min_size=min_size, max_size=max_size, open=True,
                kwargs={"autocommit": True},
                configure=lambda raw: _session_settings(raw, lock_timeout_ms),
                name="academicai")
            _pools[key] = pool
    return pool


def checkout(config):
    """A pooled connection for one request or worker job."""
    pool = _pool_for(config["DATABASE_URL"], config["SQLITE_BUSY_TIMEOUT_MS"],
                     config.get("DB_POOL_MIN", 1), config.get("DB_POOL_MAX", 10))
    try:
        raw = pool.getconn()
    except psycopg.OperationalError as exc:
        raise DatabaseBusy(str(exc)) from exc
    return PgConnection(raw, release=pool.putconn)


def close_pools(url=None):
    """Close pooled connections (for tests, and at interpreter exit)."""
    with _pools_lock:
        for key in [k for k in _pools if url is None or k[0] == url]:
            _pools.pop(key).close()


atexit.register(close_pools)


def with_search_path(url, schema):
    """The same database, with `schema` first on the search path."""
    return make_conninfo(url, options=f"-c search_path={schema}")


# ── Migrations ──────────────────────────────────────────────────────────────

def _migrations():
    """(version, name, sql) in order: the baseline schema, then any numbered
    files in migrations_postgres/ (0002_add_something.sql, ...)."""
    with open(BASELINE_PATH, "r", encoding="utf-8") as fh:
        found = [(1, "baseline", fh.read())]
    if os.path.isdir(MIGRATIONS_DIR):
        for filename in sorted(os.listdir(MIGRATIONS_DIR)):
            match = re.match(r"^(\d{4})_(\w+)\.sql$", filename)
            if not match or int(match.group(1)) <= 1:
                continue
            with open(os.path.join(MIGRATIONS_DIR, filename), "r", encoding="utf-8") as fh:
                found.append((int(match.group(1)), match.group(2), fh.read()))
    return found


def migrate(conn, applied_at):
    """Apply every migration not yet recorded in schema_migrations.

    Each one runs in its own transaction with its row in schema_migrations, so
    a migration is applied completely or not at all, and exactly once. The
    caller holds the start-up lock (startup_lock), which is what makes two
    processes starting together safe. Returns the versions applied.
    """
    raw = conn.raw
    raw.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                       version    INTEGER PRIMARY KEY,
                       name       TEXT NOT NULL,
                       applied_at TEXT NOT NULL)""")
    done = {row[0] for row in raw.execute("SELECT version FROM schema_migrations").fetchall()}
    applied = []
    for version, name, sql in _migrations():
        if version in done:
            continue
        with raw.transaction():
            raw.execute(sql)
            raw.execute("INSERT INTO schema_migrations (version, name, applied_at) "
                        "VALUES (%s, %s, %s)", (version, name, applied_at))
        applied.append(version)
    return applied
