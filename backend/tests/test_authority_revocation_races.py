"""Authority must be re-checked where the write happens, not only at the door.

The require_rep decorator reads membership when a request arrives. The write
runs later, inside its own transaction. Between those moments a removal ballot
can close or a transfer can complete, and the decorator's answer goes stale.

Ensures event, announcement, timetable and course writes re-check rep
authority inside their own transaction, so a publish issued in that window
cannot land after the rep's authority has been revoked (spec 12).
"""
import pytest

from academicai import clock

pytestmark = pytest.mark.security


def _revoke_rep(app, user_id, community_id):
    with app.app_context():
        from academicai.db.connection import execute, transaction
        with transaction() as conn:
            execute("""UPDATE community_members SET role = 'STUDENT', rep_since = NULL
                       WHERE user_id = ? AND community_id = ?""",
                    (user_id, community_id), conn=conn)


def _end_membership(app, user_id, community_id):
    with app.app_context():
        from academicai.db.connection import execute, transaction
        with transaction() as conn:
            execute("""UPDATE community_members SET status = 'ENDED', role = 'STUDENT'
                       WHERE user_id = ? AND community_id = ?""",
                    (user_id, community_id), conn=conn)


# --- The services refuse a non-rep actor in their own right ----------------

@pytest.mark.parametrize("service,func,args", [
    ("event_service", "create_event",
     lambda cid: (cid, {"title": "Forged", "event_type": "QUIZ",
                        "event_date": "2026-10-20"})),
    ("announcement_service", "create_announcement",
     lambda cid: (cid, {"title": "Forged", "body": "x"})),
    ("timetable_service", "create_entry",
     lambda cid: (cid, {"day_of_week": "MONDAY", "start_time": "09:00", "venue": "B007"})),
    ("course_service", "create_course",
     lambda cid: (cid, {"code": "FAKE101", "title": "Forged"})),
])
def test_write_services_refuse_a_non_rep_actor(client, academic_community, app,
                                               service, func, args):
    """Defence in depth: the service is authoritative, not just the route."""
    import importlib

    from academicai.errors import AuthorizationError

    setup = academic_community(size=5, seed_events=False)
    student = setup.members[1]
    community_id = setup.rep.get("/api/community").get_json()["community"]["id"]

    module = importlib.import_module(f"academicai.services.{service}")
    with app.app_context():
        with pytest.raises(AuthorizationError):
            getattr(module, func)(student.user_id, *args(community_id))


def test_update_and_cancel_also_refuse_a_non_rep_actor(client, academic_community, app):
    from academicai.errors import AuthorizationError
    from academicai.services import event_service

    setup = academic_community(size=5)
    student = setup.members[1]
    community_id = setup.rep.get("/api/community").get_json()["community"]["id"]
    event_id = setup.cos202_assignment["id"]

    with app.app_context():
        with pytest.raises(AuthorizationError):
            event_service.update_event(student.user_id, community_id, event_id,
                                       {"event_date": "2026-12-01"})
        with pytest.raises(AuthorizationError):
            event_service.cancel_event(student.user_id, community_id, event_id)


# --- The removal race, over HTTP -------------------------------------------

@pytest.mark.parametrize("path,payload,service,func", [
    ("/api/events", {"title": "Raced", "event_type": "QUIZ", "event_date": "2026-10-20"},
     "event_service", "create_event"),
    ("/api/community/announcements", {"title": "Raced", "body": "x"},
     "announcement_service", "create_announcement"),
    ("/api/community/timetable", {"day_of_week": "MONDAY", "start_time": "09:00"},
     "timetable_service", "create_entry"),
    ("/api/community/courses", {"code": "RACE101", "title": "Raced"},
     "course_service", "create_course"),
])
def test_authority_revoked_mid_request_blocks_the_write(
        client, academic_community, app, monkeypatch, path, payload, service, func):
    """Revoke the rep between the route's gate and the service's write."""
    import importlib

    setup = academic_community(size=6, seed_events=False)
    rep = setup.rep
    community_id = rep.get("/api/community").get_json()["community"]["id"]

    module = importlib.import_module(f"academicai.services.{service}")
    real = getattr(module, func)

    def revoke_then_call(actor_id, cid, *a, **kw):
        _revoke_rep(app, actor_id, cid)
        return real(actor_id, cid, *a, **kw)

    monkeypatch.setattr(module, func, revoke_then_call)

    with app.app_context():
        from academicai.db.connection import query_one
        before = query_one(
            "SELECT COUNT(*) AS n FROM timetable_entries WHERE community_id = ?",
            (community_id,))["n"]

    resp = rep.post(path, json=payload)
    assert resp.status_code == 403, resp.get_json()

    # Nothing was written by the refused request.
    with app.app_context():
        from academicai.db.connection import query_one
        for table, column in (("academic_events", "title"), ("announcements", "title"),
                              ("courses", "code")):
            row = query_one(f"SELECT COUNT(*) AS n FROM {table} WHERE {column} LIKE ?",
                            ("%Raced%",))
            assert row["n"] == 0, table
        after = query_one(
            "SELECT COUNT(*) AS n FROM timetable_entries WHERE community_id = ?",
            (community_id,))["n"]
        assert after == before


def test_a_completed_removal_ballot_blocks_a_later_publish(
        client, academic_community, run_worker):
    """The full product path: a removal ballot closes, then the rep tries to publish."""
    from datetime import timedelta

    setup = academic_community(size=6, seed_events=False)
    rep = setup.rep
    # A second rep is needed to open a removal against the first.
    second = setup.members[1]
    nomination_id = rep.post("/api/rep/nominate",
                             json={"candidate_id": second.user_id}
                             ).get_json()["nomination"]["id"]
    for voter in setup.members[2:5]:
        voter.post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": "YES"})
    clock.advance(timedelta(hours=25))
    run_worker()
    second.relogin()

    removal_id = second.post("/api/rep/removals",
                             json={"target_user_id": rep.user_id}
                             ).get_json()["removal"]["id"]
    for voter in setup.members[2:5]:
        voter.relogin().post(f"/api/rep/removals/{removal_id}/vote", json={"vote": "YES"})
    clock.advance(timedelta(hours=25))
    run_worker()

    removed = rep.relogin()
    assert removed.get("/api/community").get_json()["membership"]["role"] == "STUDENT"
    for path, payload in (
            ("/api/events", {"title": "After removal", "event_type": "QUIZ"}),
            ("/api/community/announcements", {"title": "After removal", "body": "x"}),
            ("/api/community/courses", {"code": "GONE101"}),
            ("/api/ai/publish", {"action": "CREATE", "scope": "EVENT",
                                 "title": "After removal", "event_type": "QUIZ"})):
        assert removed.post(path, json=payload).status_code == 403, path


# --- The transfer race ------------------------------------------------------

def test_membership_ending_mid_request_blocks_the_write(
        client, academic_community, app, monkeypatch):
    """A transfer completing mid-request must not let the old community be written."""
    from academicai.services import event_service

    setup = academic_community(size=5, seed_events=False)
    rep = setup.rep
    real = event_service.create_event

    def end_then_call(actor_id, cid, *a, **kw):
        _end_membership(app, actor_id, cid)
        return real(actor_id, cid, *a, **kw)

    monkeypatch.setattr(event_service, "create_event", end_then_call)
    resp = rep.post("/api/events", json={"title": "Orphaned", "event_type": "QUIZ"})
    assert resp.status_code == 403

    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT COUNT(*) AS n FROM academic_events WHERE title = ?",
                         ("Orphaned",))["n"] == 0


def test_ai_publish_was_already_protected_and_still_is(
        client, academic_community, app, monkeypatch):
    """publishing_service always re-checked in-transaction; confirm unchanged."""
    from academicai.services import publishing_service

    setup = academic_community(size=5, seed_events=False)
    rep = setup.rep
    real = publishing_service.publish

    def revoke_then_publish(actor_id, community_id, *a, **kw):
        _revoke_rep(app, actor_id, community_id)
        return real(actor_id, community_id, *a, **kw)

    monkeypatch.setattr(publishing_service, "publish", revoke_then_publish)
    resp = rep.post("/api/ai/publish", json={
        "action": "CREATE", "scope": "EVENT", "title": "Raced publish",
        "event_type": "QUIZ"})
    assert resp.status_code == 403


# --- Concurrency, with real threads -----------------------------------------
#
# Uses a file-backed database: the in-memory database shares one connection,
# which SQLite forbids across threads (see tests/test_concurrency.py).

@pytest.mark.sqlite_only       # PostgreSQL: test_postgres_concurrency.py
def test_concurrent_removal_and_publish_leaves_consistent_state(tmp_path):
    """Whichever order they land in, the database must agree with the outcome."""
    import os
    import tempfile
    import threading

    from academicai.app import create_app
    from academicai.config import TestConfig
    from academicai.db.connection import connect

    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    os.unlink(path)

    class FileConfig(TestConfig):
        DATABASE_PATH = path
        SQLITE_WAL = True
        IDENTITY_TEMP_DIR = str(tmp_path / "evidence")

    app = create_app(FileConfig)
    try:
        from tests.conftest import seed_rep_community_over_http

        rep_headers, rep_id, community_id = seed_rep_community_over_http(app)
        client = app.test_client()
        results = {}

        def publish():
            results["publish"] = client.post(
                "/api/events", json={"title": "Concurrent", "event_type": "QUIZ"},
                headers=rep_headers).status_code

        def revoke():
            conn = connect(path, busy_timeout_ms=5000, wal=True)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("""UPDATE community_members SET role = 'STUDENT'
                                WHERE user_id = ? AND community_id = ?""",
                             (rep_id, community_id))
                conn.execute("COMMIT")
            finally:
                conn.close()

        threads = [threading.Thread(target=publish), threading.Thread(target=revoke)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        verify = connect(path, busy_timeout_ms=5000, wal=True)
        published = verify.execute(
            "SELECT COUNT(*) AS n FROM academic_events WHERE title = 'Concurrent'"
        ).fetchone()["n"]
        still_rep = verify.execute(
            """SELECT COUNT(*) AS n FROM community_members
               WHERE user_id = ? AND community_id = ? AND role = 'VERIFIED_REP'""",
            (rep_id, community_id)).fetchone()["n"]
        verify.close()

        # The publish either succeeded while authority held, or was refused.
        # What must never happen is a status that disagrees with the database.
        assert results["publish"] in (201, 403)
        assert (results["publish"] == 201) == (published == 1)
        assert still_rep == 0
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(path + suffix)
            except OSError:
                pass
