"""Terms & Conditions acceptance at registration.

The sign-up form's checkbox is only half of this. The rule that matters is
here: an account cannot be created without agreeing to the CURRENT version of
the Terms, and the agreement is recorded as what was agreed to (a stable
version id) and when - nothing more.
"""
import sqlite3

import pytest

from academicai import clock
from academicai.db.connection import _apply_added_columns
from academicai.services.auth_service import TERMS_VERSION

BASE = {
    "full_name": "Terms Student", "email": "terms@student.babcock.edu.ng",
    "password": "Password123", "confirm_password": "Password123",
    "university": "Babcock University", "department": "Software Engineering",
    "level": "200", "academic_session": "2026/2027", "student_id_number": "BU/SEN/7001",
}


def _account(app, email):
    from academicai.db.connection import query_one
    with app.app_context():
        return query_one("SELECT * FROM users WHERE email = ?", (email,))


def test_the_version_is_a_stable_id_for_the_current_terms():
    # The page reads "Effective Tuesday 29 September 2026"; this is its id.
    assert TERMS_VERSION == "2026-09-29"


@pytest.mark.parametrize("acceptance", [
    {},                                                        # never ticked
    {"accept_terms": False, "terms_version": TERMS_VERSION},   # unticked
    {"accept_terms": "true", "terms_version": TERMS_VERSION},  # not a real yes
    {"accept_terms": 1, "terms_version": TERMS_VERSION},
])
def test_an_account_cannot_be_created_without_agreeing(client, app, acceptance):
    resp = client.post("/api/auth/register", json={**BASE, **acceptance})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["details"]["field"] == "accept_terms"
    assert "Terms & Conditions" in body["message"]
    assert _account(app, BASE["email"]) is None, "no account exists"


@pytest.mark.parametrize("version", [None, "", "2025-01-01", "Tuesday 29 September 2026"])
def test_agreeing_to_any_other_version_is_refused(client, app, version):
    resp = client.post("/api/auth/register",
                       json={**BASE, "accept_terms": True, "terms_version": version})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["details"] == {"field": "accept_terms", "terms_version": TERMS_VERSION}
    assert "updated" in body["message"]
    assert _account(app, BASE["email"]) is None


def test_the_acceptance_is_recorded_as_version_and_time(client, app):
    resp = client.post("/api/auth/register",
                       json={**BASE, "accept_terms": True, "terms_version": TERMS_VERSION})
    assert resp.status_code == 201, resp.get_json()
    row = _account(app, BASE["email"])
    assert row["terms_version"] == TERMS_VERSION
    assert row["terms_accepted_at"] == clock.now_iso()
    assert row["terms_accepted_at"] == row["created_at"]


def test_nothing_else_about_the_acceptance_is_kept(app):
    """Version and time only: no IP, user agent or copy of the text."""
    from academicai.db.connection import query_all
    with app.app_context():
        columns = {r["name"] for r in query_all("PRAGMA table_info(users)")}
    terms_columns = {c for c in columns if "terms" in c or "accept" in c or "agree" in c}
    assert terms_columns == {"terms_version", "terms_accepted_at"}


def test_an_older_database_gains_the_columns_on_start_up():
    """A deployed database from before the Terms: the migrator adds both
    columns, nullable, and leaves every existing account as it was."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE users (id INTEGER PRIMARY KEY, full_name TEXT NOT NULL,
                    email TEXT NOT NULL, student_id_number TEXT)""")
    conn.execute("INSERT INTO users (full_name, email) VALUES ('Early Student', 'early@x.edu')")
    _apply_added_columns(conn)
    _apply_added_columns(conn)          # idempotent: a second start changes nothing
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    assert {"terms_version", "terms_accepted_at"} <= columns
    early = conn.execute("SELECT * FROM users").fetchone()
    assert early["terms_version"] is None and early["terms_accepted_at"] is None


def test_an_account_from_before_the_terms_still_signs_in(client, app, register):
    actor = register(client)
    from academicai.db.connection import execute, transaction
    with app.app_context():
        with transaction() as conn:
            execute("UPDATE users SET terms_version = NULL, terms_accepted_at = NULL WHERE id = ?",
                    (actor.user_id,), conn=conn)
    resp = client.post("/api/auth/login", json={"email": actor.email, "password": "Password123"})
    assert resp.status_code == 200
