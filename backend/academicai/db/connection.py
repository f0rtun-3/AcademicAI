"""Connection and transaction management.

SQLite by default (local development and tests); PostgreSQL when
DATABASE_BACKEND is "postgresql" (production). Everything below that talks
to SQLite directly - PRAGMAs, the two table rebuilds, ALTER TABLE for added
columns - is SQLite-only. PostgreSQL's schema is db/schema_postgres.sql plus
numbered migrations, and its connection is db/postgres.py, which keeps the
behaviour described here (including BEGIN IMMEDIATE's write lock, as an
advisory lock). The functions the application calls - get_db, transaction,
execute, query_one, query_all, insert_returning_id - work on either.

Design rules (spec 32):
  * foreign keys ON
  * WAL where the database is a real file
  * busy_timeout so concurrent writers wait rather than failing instantly
  * BEGIN IMMEDIATE for read-then-write operations, so a decision made from a
    read cannot be invalidated by another writer before the write lands
  * a SQLite lock failure must never be reported as a business error such as
    the stale-proposal 409; it surfaces as its own DatabaseBusy error
"""
import os
import sqlite3
from contextlib import contextmanager

from flask import current_app, g

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


class DatabaseBusy(RuntimeError):
    """Raised when the database could not acquire a lock within busy_timeout
    (SQLite) or lock_timeout (PostgreSQL), or could not be reached.

    Deliberately distinct from business-rule errors so that infrastructure
    contention is never mistaken for a stale proposal (spec 32).
    """


def _configure(conn, config):
    conn.row_factory = sqlite3.Row
    # isolation_level=None -> explicit transaction control; we issue BEGIN ourselves.
    conn.isolation_level = None
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {int(config['busy_timeout_ms'])}")
    if config["wal"] and config["path"] != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def connect(path, busy_timeout_ms=5000, wal=True):
    if path != ":memory:":
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=busy_timeout_ms / 1000.0)
    return _configure(conn, {"path": path, "busy_timeout_ms": busy_timeout_ms, "wal": wal})


def _is_postgres(conn):
    return getattr(conn, "dialect", None) == "postgresql"


def get_db():
    """Connection for the current request/worker job, created on first use."""
    if "db" not in g:
        app = current_app
        path = app.config["DATABASE_PATH"]
        if app.config.get("DATABASE_BACKEND") == "postgresql":
            from . import postgres
            g.db = postgres.checkout(app.config)   # back to the pool in close_db
            g.db_is_shared = False
        elif path == ":memory:" and app.config.get("_SHARED_MEMORY_CONN") is not None:
            # Tests share one in-memory connection so every request sees the same DB.
            g.db = app.config["_SHARED_MEMORY_CONN"]
            g.db_is_shared = True
        else:
            g.db = connect(
                path,
                busy_timeout_ms=app.config["SQLITE_BUSY_TIMEOUT_MS"],
                wal=app.config["SQLITE_WAL"],
            )
            g.db_is_shared = False
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    shared = g.pop("db_is_shared", False)
    if conn is not None and not shared:
        conn.close()


# Columns added to existing tables after the first release. The project has no
# migration framework; schema.sql is authoritative for new databases and this
# list brings an already-deployed SQLite file up to date. Keep it small.
_ADDED_COLUMNS = (
    ("users", "student_id_number", "TEXT"),
    # Terms & Conditions acceptance, recorded at registration. Additive and
    # nullable: an account created before the Terms existed keeps NULL, which
    # is the truth - it never agreed to a version.
    ("users", "terms_version", "TEXT"),
    ("users", "terms_accepted_at", "TEXT"),
    ("identity_verifications", "provider", "TEXT"),
    ("identity_verifications", "authoritative", "INTEGER NOT NULL DEFAULT 0"),
    ("identity_verifications", "evidence_format", "TEXT"),
    ("identity_verifications", "evidence_width", "INTEGER"),
    ("identity_verifications", "evidence_height", "INTEGER"),
    ("identity_verifications", "evidence_bytes", "INTEGER"),
    ("identity_verifications", "evidence_deleted_at", "TEXT"),
    # Typed assignment/project instructions. Additive and nullable: every
    # existing event stays valid with NULL, which is what "no instructions
    # were given" has always meant.
    ("academic_events", "description", "TEXT"),
    # In-app notifications. Additive and nullable: every queued row that
    # predates them stays valid, and a NULL `read_at` correctly means unread.
    ("notifications", "kind", "TEXT"),
    ("notifications", "link", "TEXT"),
    ("notifications", "read_at", "TEXT"),
    # The bell's own wording, separate from the email's (notification_copy.py).
    # Additive and nullable: an older row keeps showing its email wording.
    ("notifications", "app_subject", "TEXT"),
    ("notifications", "app_body", "TEXT"),
    # Email verification moved from a long link token to a six-digit code.
    # `code_salt` makes each stored digest unique and unguessable (see
    # security/tokens.py); `attempts` is what makes a short code safe, by
    # destroying it after a handful of wrong guesses. Both are additive: a row
    # predating them has NULL salt and NULL attempts, which the code treats as
    # a legacy link token and simply refuses rather than mis-verifying.
    ("email_verification_tokens", "code_salt", "TEXT"),
    ("email_verification_tokens", "attempts", "INTEGER NOT NULL DEFAULT 0"),
    # HOW an account came to be verified: 'OTP' when a code was actually
    # entered, 'SKIPPED_NO_VERIFICATION' when the deployment had verification
    # switched off. Without this, email_verified = 1 means two different things
    # and there is no way to tell them apart afterwards - so re-enabling
    # verification could never identify which accounts still need it.
    # NULL on rows that predate the column.
    ("users", "email_verification_method", "TEXT"),
    # The university's academic clock (IANA zone). Added nullable because
    # SQLite cannot add a NOT NULL column without a default, and there is
    # deliberately no default zone. _require_university_timezones backfills
    # the known ones and refuses to start while any university lacks one.
    ("universities", "timezone", "TEXT"),
)


# A CHECK constraint cannot be altered in SQLite, so widening event_type to
# accept PROJECT needs the documented 12-step table rebuild. This is the only
# rebuild in the project and it is deliberately narrow.
#
# It runs only when the deployed table is genuinely missing the value, it runs
# inside one transaction, and it verifies the row count and the foreign keys
# before committing. If anything disagrees the transaction rolls back and the
# application starts on the old table rather than on a half-migrated one.
_EVENT_TYPES_SQL = ("'ASSIGNMENT','PROJECT','QUIZ','TEST','PRESENTATION',"
                    "'EXAM','CLASS','OTHER'")


def _event_type_check_is_current(conn):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'academic_events'"
    ).fetchone()
    if row is None:
        return True          # nothing deployed yet; schema.sql will create it
    return "'PROJECT'" in (row["sql"] or "")


def _widen_event_type_check(conn):
    """Rebuild academic_events so event_type also accepts PROJECT.

    Nothing is dropped until the copy has been verified, and the whole thing is
    one transaction. Foreign keys are suspended for the swap - three tables
    reference this one - and re-checked before the transaction closes.
    """
    if _event_type_check_is_current(conn):
        return False

    columns = [r["name"] for r in conn.execute("PRAGMA table_info(academic_events)")]
    before = conn.execute("SELECT COUNT(*) AS n FROM academic_events").fetchone()["n"]

    # `description` may not exist yet on a database that predates it; the
    # rebuilt table always has it, and the copy fills it with NULL.
    source = ", ".join(columns)
    target = ", ".join(columns)

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        conn.execute(f"""
            CREATE TABLE academic_events_rebuild (
                id              INTEGER PRIMARY KEY,
                community_id    INTEGER NOT NULL REFERENCES academic_communities(id),
                course_id       INTEGER REFERENCES courses(id),
                event_type      TEXT NOT NULL
                                CHECK (event_type IN ({_EVENT_TYPES_SQL})),
                title           TEXT NOT NULL,
                description     TEXT,
                event_date      TEXT,
                event_time      TEXT,
                venue           TEXT,
                priority        TEXT NOT NULL DEFAULT 'NORMAL'
                                CHECK (priority IN ('LOW','NORMAL','HIGH')),
                status          TEXT NOT NULL DEFAULT 'SCHEDULED'
                                CHECK (status IN ('SCHEDULED','CANCELLED','RESCHEDULED')),
                original_message TEXT,
                version         INTEGER NOT NULL DEFAULT 1,
                created_by      INTEGER NOT NULL REFERENCES users(id),
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """)
        conn.execute(
            f"INSERT INTO academic_events_rebuild ({target}) SELECT {source} FROM academic_events")

        copied = conn.execute(
            "SELECT COUNT(*) AS n FROM academic_events_rebuild").fetchone()["n"]
        if copied != before:
            raise RuntimeError(
                f"Refusing to migrate academic_events: copied {copied} of {before} rows.")

        conn.execute("DROP TABLE academic_events")
        conn.execute("ALTER TABLE academic_events_rebuild RENAME TO academic_events")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_community "
            "ON academic_events(community_id, status)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_course ON academic_events(course_id)")

        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(
                "Refusing to migrate academic_events: the rebuilt table leaves "
                f"{len(broken)} dangling foreign key reference(s).")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    return True


def _notification_status_check_is_current(conn):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='notifications'"
    ).fetchone()
    if row is None:
        return True          # nothing deployed yet; schema.sql will create it
    return "'SIMULATED'" in (row["sql"] or "")


def _widen_notification_status_check(conn):
    """Rebuild notifications so status also accepts SIMULATED.

    WHY A FOURTH STATUS EXISTS
    --------------------------
    The outbox had three terminal answers: it is waiting, a provider took it,
    or it could not be delivered. A development backend that prints a message
    to a terminal is none of those. It was being recorded as SENT, which made
    the outbox claim a delivery nobody made - and an outbox that lies is not
    evidence of anything.

    SIMULATED is terminal like SENT, so a message is still handled exactly
    once and the idempotence guarantee is unchanged. It simply does not claim
    the message left the building.

    Same shape as _widen_event_type_check: nothing is dropped until the copy is
    verified, and the whole swap is one transaction.
    """
    if _notification_status_check_is_current(conn):
        return False

    columns = [r["name"] for r in conn.execute("PRAGMA table_info(notifications)")]
    before = conn.execute("SELECT COUNT(*) AS n FROM notifications").fetchone()["n"]
    copy = ", ".join(columns)

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        conn.execute("""
            CREATE TABLE notifications_rebuild (
                id            INTEGER PRIMARY KEY,
                user_id       INTEGER NOT NULL REFERENCES users(id),
                community_id  INTEGER REFERENCES academic_communities(id),
                subject       TEXT NOT NULL,
                body          TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'PENDING'
                              CHECK (status IN ('PENDING','SENT','SIMULATED','FAILED')),
                attempts      INTEGER NOT NULL DEFAULT 0,
                last_error    TEXT,
                dedupe_key    TEXT UNIQUE,
                created_at    TEXT NOT NULL,
                sent_at       TEXT,
                kind          TEXT,
                link          TEXT,
                read_at       TEXT,
                app_subject   TEXT,
                app_body      TEXT
            )
        """)
        conn.execute(
            f"INSERT INTO notifications_rebuild ({copy}) SELECT {copy} FROM notifications")

        copied = conn.execute(
            "SELECT COUNT(*) AS n FROM notifications_rebuild").fetchone()["n"]
        if copied != before:
            raise RuntimeError(
                f"Refusing to migrate notifications: copied {copied} of {before} rows.")

        conn.execute("DROP TABLE notifications")
        conn.execute("ALTER TABLE notifications_rebuild RENAME TO notifications")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_pending "
                     "ON notifications(status, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user "
                     "ON notifications(user_id, id DESC)")

        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(
                "Refusing to migrate notifications: the rebuilt table leaves "
                f"{len(broken)} dangling foreign key reference(s).")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    return True


def _apply_added_columns(conn):
    """Bring a deployed database up to date, tolerating a concurrent starter.

    The check-then-ALTER is a race: the API and the worker are separate
    processes that both run this at boot. Both can read PRAGMA table_info
    before either commits its ALTER, and the loser then dies on "duplicate
    column name" - which is how the worker crashed silently on the first start
    after a column was added, leaving every timed feature dead while the API
    looked healthy.

    A duplicate column means the other process already did the work, which is
    the outcome this function wanted. Nothing else is swallowed.
    """
    for table, column, definition in _ADDED_COLUMNS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # table not present in this database
        if column in existing:
            continue
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise


def init_schema(conn):
    if _is_postgres(conn):
        return _init_postgres_schema(conn)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        script = fh.read()
    try:
        conn.executescript(script)
    except sqlite3.IntegrityError as exc:
        _explain_schema_conflict(conn, exc)
        raise
    _widen_event_type_check(conn)
    _apply_added_columns(conn)
    _widen_notification_status_check(conn)
    _seed_reference_data(conn)
    _require_university_timezones(conn)
    return conn


def _init_postgres_schema(conn):
    """PostgreSQL: apply pending migrations (schema_postgres.sql is the
    baseline), then the same idempotent start-up data steps as SQLite. The
    caller holds the start-up lock (app._init_database)."""
    from datetime import datetime, timezone

    from . import postgres

    postgres.migrate(conn, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    _seed_reference_data(conn)
    _require_university_timezones(conn)
    return conn


def _require_university_timezones(conn):
    """Give every university its academic timezone, or refuse to start.

    Universities named in reference_data.UNIVERSITY_TIMEZONES that have no zone
    yet are backfilled with their known one. Any other university without a
    zone - or with a value that is not a geographic IANA zone - stops start-up
    with a message saying exactly which rows need one. Nothing is guessed: a
    wrong zone moves every reminder and every "today" in that university, and
    UTC is not a safe default for anyone.

    Everything is checked BEFORE anything is written, and the write only fills
    rows that are still empty, so two processes starting together (API and
    worker) cannot disagree and a normal start performs no writes at all.
    """
    from .. import academic_time
    from . import reference_data

    fill, unresolved = reference_data.timezone_backfill(conn)
    problems = [f"id {uid} {name!r} (no timezone set)" for uid, name, _ in unresolved]
    for row in conn.execute(
            "SELECT id, name, timezone FROM universities "
            "WHERE timezone IS NOT NULL AND timezone <> ''").fetchall():
        try:
            academic_time.zone(row["timezone"])
        except academic_time.InvalidTimezone as exc:
            problems.append(f"id {row['id']} {row['name']!r} ({exc})")
    if problems:
        example = (unresolved[0][0] if unresolved else None) or "<id>"
        raise RuntimeError(
            "Refusing to start: every university needs its academic timezone "
            "(universities.timezone, a geographic IANA zone such as "
            "'Africa/Lagos'), and these do not have a valid one: "
            + "; ".join(problems) + ". No timezone has been assumed or written. "
            "Set each to the zone where the university is, for example "
            f"UPDATE universities SET timezone = 'Africa/Lagos' WHERE id = {example}; "
            "then start again.")
    if fill:
        with transaction(conn):
            for university_id, zone_name in fill:
                conn.execute(
                    "UPDATE universities SET timezone = ? "
                    "WHERE id = ? AND (timezone IS NULL OR timezone = '')",
                    (zone_name, university_id))


def _explain_schema_conflict(conn, exc):
    """Turn a constraint failure during start-up into an actionable message.

    The one-ACTIVE-membership index cannot be created over historical data that
    already violates it. Nothing is repaired automatically: deciding which of a
    user's memberships is the real one changes who can act in which community,
    which is an operator's call, not a migration's.
    """
    if "community_members.user_id" not in str(exc):
        return
    try:
        rows = conn.execute(
            """SELECT user_id, COUNT(*) AS n FROM community_members
               WHERE status = 'ACTIVE' GROUP BY user_id HAVING n > 1"""
        ).fetchall()
    except sqlite3.Error:  # pragma: no cover - diagnostics only
        return
    if not rows:
        return
    affected = ", ".join(str(r[0] if isinstance(r, tuple) else r["user_id"]) for r in rows)
    raise RuntimeError(
        "Cannot apply the one-active-membership constraint: these users already "
        f"hold more than one ACTIVE community membership (user ids: {affected}). "
        "No data has been changed. End the memberships that should no longer be "
        "active, then start the application again."
    ) from exc


def _seed_reference_data(conn):
    """Populate the university email-domain registry.

    Runs on every start and is idempotent, which is how an already-deployed
    database picks up the registry without a separate migration step.
    """
    from datetime import datetime, timezone

    from . import reference_data

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return reference_data.seed(conn, now)


@contextmanager
def transaction(conn=None, immediate=True):
    """Run a block in one transaction.

    immediate=True issues BEGIN IMMEDIATE, taking the write lock up front. Use it
    for every read-then-write sequence (ballot resolution, publishing, approvals)
    so the state a decision was based on cannot change under it.
    """
    conn = conn if conn is not None else get_db()
    if _is_postgres(conn):
        # BEGIN plus the app-wide write lock when immediate (db/postgres.py).
        with conn.transaction(immediate=immediate):
            yield conn
        return
    if conn.in_transaction:
        # Already inside an outer transaction: join it rather than nesting,
        # so the outer block keeps all-or-nothing semantics.
        yield conn
        return
    try:
        conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    except sqlite3.OperationalError as exc:
        raise DatabaseBusy(str(exc)) from exc
    try:
        yield conn
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    else:
        try:
            conn.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise DatabaseBusy(str(exc)) from exc


def query_all(sql, params=(), conn=None):
    conn = conn if conn is not None else get_db()
    return conn.execute(sql, params).fetchall()


def query_one(sql, params=(), conn=None):
    conn = conn if conn is not None else get_db()
    return conn.execute(sql, params).fetchone()


def execute(sql, params=(), conn=None):
    conn = conn if conn is not None else get_db()
    return conn.execute(sql, params)


def insert_returning_id(sql, params=(), conn=None):
    conn = conn if conn is not None else get_db()
    if _is_postgres(conn):
        return conn.insert_returning_id(sql, params)   # INSERT ... RETURNING id
    cur = conn.execute(sql, params)
    return cur.lastrowid
