"""PostgreSQL test support.

The suite runs on SQLite. PostgreSQL is opt-in, in two ways:

  ACADEMICAI_TEST_POSTGRES_URL=postgresql://user@host:port/db
      runs the PostgreSQL tests (test_postgres_*.py), each in a schema of its
      own inside that database, dropped afterwards. Without it they are
      skipped - reported as skipped, never as passed.

  ACADEMICAI_TEST_BACKEND=postgresql   (with the URL above)
      runs the WHOLE suite on PostgreSQL: every app a test creates uses one
      schema, emptied before each test. Tests marked `sqlite_only` exercise
      SQLite itself (PRAGMAs, file locking, the SQLite table rebuilds) and are
      skipped in this mode.

The database named in the URL must be a disposable one: schemas are created
and dropped in it.
"""
import os
import uuid

PG_URL = os.environ.get("ACADEMICAI_TEST_POSTGRES_URL") or None
FULL_SUITE_ON_POSTGRES = (
    os.environ.get("ACADEMICAI_TEST_BACKEND", "sqlite").strip().lower() == "postgresql")


def _integrity_errors():
    import sqlite3
    errors = [sqlite3.IntegrityError]
    try:
        import psycopg
        errors.append(psycopg.IntegrityError)
    except ImportError:  # pragma: no cover - an environment without the driver
        pass
    return tuple(errors)


# A constraint failure, from whichever engine the test is running on.
INTEGRITY_ERRORS = _integrity_errors()


def admin_connect():
    import psycopg
    return psycopg.connect(PG_URL, autocommit=True)


def create_schema(purpose="t"):
    """A new empty schema. Returns (name, url) - the url puts it first on the
    search path, so everything created through it lands there."""
    from academicai.db import postgres

    name = f"academicai_test_{purpose}_{uuid.uuid4().hex[:10]}"
    with admin_connect() as conn:
        conn.execute(f'CREATE SCHEMA "{name}"')
    return name, postgres.with_search_path(PG_URL, name)


def drop_schema(name, url):
    from academicai.db import postgres

    postgres.close_pools(url)
    with admin_connect() as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')


def pg_config(url, **attrs):
    from academicai.config import TestConfig

    return type("PostgresTestConfig", (TestConfig,),
                {"DATABASE_BACKEND": "postgresql", "DATABASE_URL": url, **attrs})


def make_pg_app(url, **overrides):
    from academicai.app import create_app

    return create_app(pg_config(url), **overrides)


def user_tables(conn):
    rows = conn.execute(
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'
             AND table_name <> 'schema_migrations'""").fetchall()
    return [row[0] for row in rows]


def empty_all_tables(url):
    """Every table emptied and every id sequence restarted, schema kept."""
    from academicai.db import postgres

    conn = postgres.connect(url)
    try:
        tables = user_tables(conn)
        if tables:
            conn.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables)
                         + " RESTART IDENTITY CASCADE")
    finally:
        conn.close()
