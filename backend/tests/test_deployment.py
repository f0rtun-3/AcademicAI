"""Deployment concerns: entry points, persistence and backups (spec 32)."""
import os
import sqlite3
import tempfile

import pytest


def test_app_boots_with_a_file_database_and_creates_schema():
    from academicai.app import create_app
    from academicai.config import TestConfig

    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "nested", "academicai.db")

    class FileConfig(TestConfig):
        DATABASE_PATH = path
        SQLITE_WAL = True

    app = create_app(FileConfig)
    assert os.path.exists(path)          # parent directories are created
    client = app.test_client()
    assert client.get("/api/health").status_code == 200

    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    for expected in ("users", "academic_communities", "community_members",
                     "academic_events", "change_history", "notifications",
                     "chat_conversations", "rep_removals"):
        assert expected in tables


def test_backup_produces_a_readable_copy_and_prunes_old_ones():
    from academicai.app import create_app
    from academicai.config import TestConfig
    from backup_db import backup

    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "academicai.db")

    class FileConfig(TestConfig):
        DATABASE_PATH = path
        SQLITE_WAL = True

    app = create_app(FileConfig)
    with app.app_context():
        from academicai import clock
        from academicai.db.connection import execute, transaction
        with transaction() as conn:
            execute("INSERT INTO universities (name, created_at, timezone) VALUES (?, ?, ?)",
                    ("Backup Test University", clock.now_iso(), "Africa/Lagos"), conn=conn)

    dest = os.path.join(directory, "backups")
    target = backup(path, dest, keep=2)

    conn = sqlite3.connect(target)
    names = {r[0] for r in conn.execute("SELECT name FROM universities").fetchall()}
    domains = conn.execute(
        "SELECT COUNT(*) FROM university_email_domains WHERE active = 1").fetchone()[0]
    conn.close()
    assert "Backup Test University" in names
    # The seeded email-domain registry must survive a backup too.
    assert "Babcock University" in names
    assert domains == 4

    # Older backups beyond `keep` are pruned.
    for i in range(4):
        open(os.path.join(dest, f"academicai-2020010{i}T000000Z.db"), "w").close()
    backup(path, dest, keep=2)
    remaining = [f for f in os.listdir(dest) if f.endswith(".db")]
    assert len(remaining) == 2


def test_secret_key_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("ACADEMICAI_SECRET_KEY", "from-the-environment")
    import importlib

    from academicai import config
    importlib.reload(config)
    assert config.Config.SECRET_KEY == "from-the-environment"
    monkeypatch.delenv("ACADEMICAI_SECRET_KEY")
    importlib.reload(config)


def test_unknown_route_returns_json_not_html(client):
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_wrong_method_returns_json(client):
    resp = client.get("/api/auth/login")
    assert resp.status_code == 405
    assert resp.get_json()["error"] == "method_not_allowed"


def test_production_refuses_to_start_with_the_default_secret():
    """A placeholder secret in production makes every token forgeable (spec 25)."""
    from academicai.app import create_app
    from academicai.config import Config

    class ProdConfig(Config):
        ENV = "production"
        TESTING = False
        DATABASE_PATH = "/tmp/academicai-prod-check.db"
        # Stated rather than inherited: the point of the test is the
        # PLACEHOLDER value, and leaving it implicit made the test depend on
        # whatever the machine's environment happened to hold.
        SECRET_KEY = Config.DEFAULT_SECRET_KEY
        EMAIL_BACKEND = "resend"
        RESEND_API_KEY = "re_test_key"

    with pytest.raises(RuntimeError) as excinfo:
        create_app(ProdConfig)
    assert "ACADEMICAI_SECRET_KEY" in str(excinfo.value)


def test_production_refuses_an_in_memory_database():
    from academicai.app import create_app
    from academicai.config import Config

    class ProdConfig(Config):
        ENV = "production"
        TESTING = False
        SECRET_KEY = "a-real-production-secret"
        DATABASE_PATH = ":memory:"

    with pytest.raises(RuntimeError) as excinfo:
        create_app(ProdConfig)
    assert "ACADEMICAI_DB_PATH" in str(excinfo.value)


def test_production_starts_when_properly_configured():
    import tempfile

    from academicai.app import create_app
    from academicai.config import Config

    directory = tempfile.mkdtemp()

    class ProdConfig(Config):
        ENV = "production"
        TESTING = False
        SECRET_KEY = "a-real-production-secret"
        DATABASE_PATH = os.path.join(directory, "academicai.db")
        # A backend that actually sends. `console` used to satisfy this check,
        # which allowed a deployment that printed verification codes to a log
        # while students waited for mail that was never sent.
        EMAIL_BACKEND = "resend"
        RESEND_API_KEY = "re_test_key"

    app = create_app(ProdConfig)
    assert app.config["SECRET_KEY"] == "a-real-production-secret"
    assert app.debug is False


def test_development_still_starts_with_defaults():
    from academicai.app import create_app
    from academicai.config import TestConfig

    assert create_app(TestConfig) is not None


def test_migration_fails_clearly_on_duplicate_active_memberships(tmp_path):
    """A legacy database that violates the one-ACTIVE-membership rule must fail
    with a diagnosis naming the affected users, and must not repair or destroy
    anything: choosing which membership survives is an operator decision."""
    import sqlite3 as sq

    from academicai.app import create_app
    from academicai.config import Config

    path = str(tmp_path / "legacy.db")
    conn = sq.connect(path)
    conn.executescript("""
        CREATE TABLE universities (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                                   created_at TEXT NOT NULL);
        CREATE TABLE users (id INTEGER PRIMARY KEY, full_name TEXT, email TEXT UNIQUE,
            password_hash TEXT, email_verified INTEGER DEFAULT 1,
            identity_status TEXT DEFAULT 'VERIFIED', token_epoch INTEGER DEFAULT 1,
            university_id INTEGER, department TEXT, level TEXT, academic_session TEXT,
            created_at TEXT, updated_at TEXT);
        CREATE TABLE academic_communities (id INTEGER PRIMARY KEY, university_id INTEGER,
            department TEXT, level TEXT, academic_session TEXT,
            status TEXT DEFAULT 'ACTIVE', created_at TEXT, updated_at TEXT);
        CREATE TABLE community_members (id INTEGER PRIMARY KEY, community_id INTEGER,
            user_id INTEGER, role TEXT DEFAULT 'STUDENT', status TEXT DEFAULT 'ACTIVE',
            requested_at TEXT, approved_by INTEGER, approved_at TEXT, ended_at TEXT,
            rep_since TEXT, UNIQUE(community_id, user_id));
        INSERT INTO universities VALUES (1, 'Babcock University', 'x');
        INSERT INTO users (id, full_name, email, university_id)
            VALUES (1, 'Legacy', 'l@student.babcock.edu.ng', 1);
        INSERT INTO academic_communities (id, university_id, department, level, academic_session)
            VALUES (1,1,'SE','200','2026/2027'), (2,1,'SE','300','2026/2027');
        INSERT INTO community_members (community_id, user_id, status, requested_at)
            VALUES (1,1,'ACTIVE','x'), (2,1,'ACTIVE','x');
    """)
    conn.commit()
    conn.close()

    class LegacyConfig(Config):
        DATABASE_PATH = path
        TESTING = True
        SECRET_KEY = "x"

    with pytest.raises(RuntimeError) as excinfo:
        create_app(LegacyConfig)
    message = str(excinfo.value)
    assert "one-active-membership" in message
    assert "user ids: 1" in message
    assert "No data has been changed" in message

    conn = sq.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM community_members").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    conn.close()


def test_migration_succeeds_on_a_legacy_database_with_one_active_membership(tmp_path):
    import sqlite3 as sq

    from academicai.app import create_app
    from academicai.config import Config

    path = str(tmp_path / "ok.db")
    conn = sq.connect(path)
    conn.executescript("""
        CREATE TABLE universities (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                                   created_at TEXT NOT NULL);
        CREATE TABLE users (id INTEGER PRIMARY KEY, full_name TEXT, email TEXT UNIQUE,
            password_hash TEXT, email_verified INTEGER DEFAULT 1,
            identity_status TEXT DEFAULT 'VERIFIED', token_epoch INTEGER DEFAULT 1,
            university_id INTEGER, department TEXT, level TEXT, academic_session TEXT,
            created_at TEXT, updated_at TEXT);
        CREATE TABLE academic_communities (id INTEGER PRIMARY KEY, university_id INTEGER,
            department TEXT, level TEXT, academic_session TEXT,
            status TEXT DEFAULT 'ACTIVE', created_at TEXT, updated_at TEXT);
        CREATE TABLE community_members (id INTEGER PRIMARY KEY, community_id INTEGER,
            user_id INTEGER, role TEXT DEFAULT 'STUDENT', status TEXT DEFAULT 'ACTIVE',
            requested_at TEXT, approved_by INTEGER, approved_at TEXT, ended_at TEXT,
            rep_since TEXT, UNIQUE(community_id, user_id));
        INSERT INTO universities VALUES (1, 'Babcock University', 'x');
        INSERT INTO users (id, full_name, email, university_id)
            VALUES (1, 'Legacy', 'l@student.babcock.edu.ng', 1);
        INSERT INTO academic_communities (id, university_id, department, level, academic_session)
            VALUES (1,1,'SE','200','2026/2027'), (2,1,'SE','300','2026/2027');
        -- ACTIVE + PENDING_APPROVAL is the normal mid-transfer shape and must
        -- remain legal; an ENDED row alongside it must not block the index.
        INSERT INTO community_members (community_id, user_id, status, requested_at)
            VALUES (1,1,'ACTIVE','x'), (2,1,'PENDING_APPROVAL','x');
    """)
    conn.commit()
    conn.close()

    class LegacyConfig(Config):
        DATABASE_PATH = path
        TESTING = True
        SECRET_KEY = "x"

    create_app(LegacyConfig)
    conn = sq.connect(path)
    indexes = [r[1] for r in conn.execute("PRAGMA index_list(community_members)")]
    assert any("one_active_membership" in name for name in indexes)
    assert conn.execute("SELECT COUNT(*) FROM community_members").fetchone()[0] == 2
    conn.close()


def test_production_refuses_a_backend_that_cannot_send():
    """A build that only prints email must never be a production build."""
    import tempfile

    from academicai.app import create_app
    from academicai.config import Config

    directory = tempfile.mkdtemp()

    class Base(Config):
        ENV = "production"
        TESTING = False
        SECRET_KEY = "a-real-production-secret"
        DATABASE_PATH = os.path.join(directory, "academicai.db")

    for backend in ("console", "memory"):
        class ProdConfig(Base):
            EMAIL_BACKEND = backend

        with pytest.raises(RuntimeError) as excinfo:
            create_app(ProdConfig)
        assert "does not send mail" in str(excinfo.value)


def test_production_refuses_resend_without_an_api_key():
    """Configured to send, but with nothing to send it with."""
    import tempfile

    from academicai.app import create_app
    from academicai.config import Config

    class ProdConfig(Config):
        ENV = "production"
        TESTING = False
        SECRET_KEY = "a-real-production-secret"
        DATABASE_PATH = os.path.join(tempfile.mkdtemp(), "academicai.db")
        EMAIL_BACKEND = "resend"
        RESEND_API_KEY = None

    with pytest.raises(RuntimeError) as excinfo:
        create_app(ProdConfig)
    assert "ACADEMICAI_RESEND_API_KEY" in str(excinfo.value)
