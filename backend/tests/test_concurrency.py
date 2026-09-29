"""Concurrency and transaction discipline (spec 17, 21, 32).

These tests use a real file-backed SQLite database, because the in-memory
database used elsewhere shares a single connection and cannot exhibit real
lock contention.
"""
import os
import tempfile
import threading

import pytest

from academicai import clock
from academicai.app import create_app
from academicai.config import TestConfig
from academicai.db.connection import DatabaseBusy, connect, query_all, query_one, transaction
from academicai.services.auth_service import TERMS_VERSION  # noqa: E402
# What the sign-up form sends when its Terms box is ticked.
TERMS_ACCEPTED = {"accept_terms": True, "terms_version": TERMS_VERSION}

pytestmark = pytest.mark.concurrency


@pytest.fixture
def file_app(tmp_path):
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    os.unlink(path)

    class FileConfig(TestConfig):
        DATABASE_PATH = path
        SQLITE_WAL = True

    app = create_app(FileConfig)
    yield app
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except OSError:
            pass


def _seed(app):
    """Build a rep-led community with one event, through the real API."""
    client = app.test_client()
    from datetime import timedelta

    actors = []
    for i in range(4):
        email = f"conc{i}@student.babcock.edu.ng"
        payload = {**TERMS_ACCEPTED, "full_name": f"Conc Student {i}", "email": email,
                   "password": "Password123", "confirm_password": "Password123",
                   "university": "Babcock University", "department": "Software Engineering",
                   "level": "200", "academic_session": "2026/2027",
                   "student_id_number": f"BU/SEN/{i:04d}"}
        code = client.post("/api/auth/register", json=payload).get_json()["verification_code"]
        client.post("/api/auth/verify-email", json={"email": email, "code": code})
        session = client.post("/api/auth/login",
                              json={"email": email, "password": "Password123"}).get_json()
        headers = {"Authorization": f"Bearer {session['token']}"}
        client.post("/api/community/setup", headers=headers)
        client.post("/api/community/join", headers=headers)
        actors.append({"email": email, "id": session["user"]["id"], "headers": headers})

    nomination = client.post("/api/rep/nominate",
                             json={"candidate_id": actors[0]["id"]},
                             headers=actors[0]["headers"]).get_json()["nomination"]["id"]
    for actor in actors[1:]:
        client.post(f"/api/rep/candidates/{nomination}/vote", json={"vote": "YES"},
                    headers=actor["headers"])

    clock.advance(timedelta(hours=25))
    with app.app_context():
        from academicai.worker.jobs import run_once
        run_once()

    for actor in actors:
        session = client.post("/api/auth/login",
                              json={"email": actor["email"],
                                    "password": "Password123"}).get_json()
        actor["headers"] = {"Authorization": f"Bearer {session['token']}"}

    event = client.post("/api/events",
                        json={"title": "COS202 Assignment", "event_type": "ASSIGNMENT",
                              "event_date": "2026-10-02"},
                        headers=actors[0]["headers"]).get_json()["event"]
    return actors, event, nomination


def test_concurrent_updates_to_one_event_yield_one_winner(file_app):
    """Optimistic concurrency: the loser gets 409, not a silent overwrite (spec 17)."""
    actors, event, _ = _seed(file_app)
    results = []
    barrier = threading.Barrier(2)

    def attempt(new_date):
        client = file_app.test_client()
        barrier.wait()
        resp = client.put(f"/api/events/{event['id']}",
                          json={"event_date": new_date, "expected_version": event["version"]},
                          headers=actors[0]["headers"])
        results.append(resp.status_code)

    threads = [threading.Thread(target=attempt, args=(d,))
               for d in ("2026-10-05", "2026-10-09")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [200, 409]
    with file_app.app_context():
        row = query_one("SELECT * FROM academic_events WHERE id = ?", (event["id"],))
        assert row["version"] == event["version"] + 1
        assert row["event_date"] in ("2026-10-05", "2026-10-09")


def test_concurrent_ballot_closing_promotes_once(file_app):
    """Two workers closing the same ballot must promote exactly one rep (spec 21)."""
    actors, _event, _ = _seed(file_app)
    client = file_app.test_client()
    nomination = client.post("/api/rep/nominate",
                             json={"candidate_id": actors[1]["id"]},
                             headers=actors[0]["headers"]).get_json()["nomination"]["id"]
    for actor in actors[1:]:
        if actor["id"] != actors[1]["id"]:
            client.post(f"/api/rep/candidates/{nomination}/vote", json={"vote": "YES"},
                        headers=actor["headers"])
    client.post(f"/api/rep/candidates/{nomination}/vote", json={"vote": "YES"},
                headers=actors[0]["headers"])

    from datetime import timedelta
    clock.advance(timedelta(hours=25))

    outcomes = []
    barrier = threading.Barrier(4)

    def close():
        from academicai.worker.jobs import run_once
        with file_app.app_context():
            barrier.wait()
            try:
                outcomes.append(run_once()["close_expired_nominations"])
            except DatabaseBusy:
                outcomes.append("busy")

    threads = [threading.Thread(target=close) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    resolved = [o for o in outcomes if isinstance(o, list) and o]
    assert len(resolved) == 1, outcomes
    with file_app.app_context():
        row = query_one(
            """SELECT COUNT(*) AS n FROM community_members
               WHERE role = 'VERIFIED_REP' AND status = 'ACTIVE'""")
        assert row["n"] == 2          # the original rep plus exactly one new one
        history = query_all(
            "SELECT * FROM change_history WHERE entity_type = 'rep_nomination' AND entity_id = ?",
            (nomination,))
        assert len([h for h in history if h["change_type"].startswith("NOMINATION_P")]) == 1


def test_concurrent_votes_are_all_recorded_exactly_once(file_app):
    actors, _event, _ = _seed(file_app)
    client = file_app.test_client()
    nomination = client.post("/api/rep/nominate",
                             json={"candidate_id": actors[1]["id"]},
                             headers=actors[0]["headers"]).get_json()["nomination"]["id"]
    voters = [a for a in actors if a["id"] != actors[1]["id"]]
    statuses = []
    barrier = threading.Barrier(len(voters))

    def vote(actor):
        c = file_app.test_client()
        barrier.wait()
        resp = c.post(f"/api/rep/candidates/{nomination}/vote", json={"vote": "YES"},
                      headers=actor["headers"])
        statuses.append(resp.status_code)

    threads = [threading.Thread(target=vote, args=(a,)) for a in voters]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert statuses == [201] * len(voters)
    with file_app.app_context():
        rows = query_all("SELECT * FROM rep_verification_votes WHERE nomination_id = ?",
                         (nomination,))
        assert len(rows) == len(voters)


def test_double_vote_is_rejected_under_concurrency(file_app):
    actors, _event, _ = _seed(file_app)
    client = file_app.test_client()
    nomination = client.post("/api/rep/nominate",
                             json={"candidate_id": actors[1]["id"]},
                             headers=actors[0]["headers"]).get_json()["nomination"]["id"]
    statuses = []
    barrier = threading.Barrier(2)

    def vote():
        c = file_app.test_client()
        barrier.wait()
        statuses.append(c.post(f"/api/rep/candidates/{nomination}/vote", json={"vote": "YES"},
                               headers=actors[2]["headers"]).status_code)

    threads = [threading.Thread(target=vote) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(statuses) == [201, 409]


def test_lock_contention_is_not_reported_as_a_stale_proposal(file_app):
    """A SQLite lock failure must surface as 503, never as a business 409 (spec 32)."""
    actors, event, _ = _seed(file_app)
    path = file_app.config["DATABASE_PATH"]

    blocker = connect(path, busy_timeout_ms=50, wal=True)
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("UPDATE academic_events SET title = 'locked' WHERE id = ?", (event["id"],))
    class Blocked(TestConfig):
        DATABASE_PATH = path
        SQLITE_WAL = True
        SQLITE_BUSY_TIMEOUT_MS = 50      # fail fast rather than wait out the test

    client = create_app(Blocked).test_client()
    resp = client.put(f"/api/events/{event['id']}",
                      json={"event_date": "2026-11-01", "expected_version": event["version"]},
                      headers=actors[0]["headers"])
    blocker.execute("ROLLBACK")
    blocker.close()

    assert resp.status_code == 503
    assert resp.get_json()["error"] == "database_busy"


def test_wal_and_foreign_keys_are_enabled_on_file_databases(file_app):
    with file_app.app_context():
        from academicai.db.connection import get_db
        conn = get_db()
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_transaction_rolls_back_on_failure(file_app):
    with file_app.app_context():
        before = query_one("SELECT COUNT(*) AS n FROM universities")["n"]
        with pytest.raises(RuntimeError):
            with transaction() as conn:
                conn.execute("INSERT INTO universities (name, created_at, timezone) "
                             "VALUES ('X', 'now', 'Africa/Lagos')")
                raise RuntimeError("boom")
        after = query_one("SELECT COUNT(*) AS n FROM universities")["n"]
        assert after == before
