"""An archived academic session accepts no official writes (spec 23).

Regression for a confirmed defect: a rep election still open when the session
was archived went on to promote its candidate INTO the archived community, and
that new rep could then create events, announcements and courses in a session
that had already ended.
"""
from datetime import timedelta

import pytest

from academicai import clock

pytestmark = pytest.mark.security

WRITES = [
    ("/api/events", {"title": "Post-archive", "event_type": "QUIZ"}),
    ("/api/community/announcements", {"title": "Post-archive", "body": "x"}),
    ("/api/community/courses", {"code": "DEAD101"}),
    ("/api/community/timetable", {"day_of_week": "MONDAY", "start_time": "09:00"}),
    ("/api/ai/publish", {"action": "CREATE", "scope": "EVENT",
                         "title": "Post-archive", "event_type": "QUIZ"}),
]


def _archive(app, actor_id, community_id):
    with app.app_context():
        from academicai.services import calendar_service
        return calendar_service.archive_session(actor_id, community_id)


def test_archiving_demotes_every_sitting_rep(client, academic_community, app):
    setup = academic_community(size=5, seed_events=False)
    _archive(app, setup.rep.user_id, setup.community_id)

    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one(
            """SELECT COUNT(*) AS n FROM community_members
               WHERE community_id = ? AND role = 'VERIFIED_REP'""",
            (setup.community_id,))["n"] == 0


@pytest.mark.parametrize("path,payload", WRITES)
def test_a_former_rep_cannot_write_after_archival(client, academic_community, app,
                                                  path, payload):
    setup = academic_community(size=5, seed_events=False)
    _archive(app, setup.rep.user_id, setup.community_id)
    # Archiving revokes rep sessions, so re-authenticate as the demoted user.
    former = setup.rep.relogin()
    assert former.post(path, json=payload).status_code == 403


def test_a_ballot_open_at_archival_does_not_promote(client, academic_community, app,
                                                    run_worker):
    """The reproduction case. A ballot mid-flight must not outlive the session."""
    setup = academic_community(size=6, seed_events=False)
    candidate = setup.members[1]

    nomination_id = setup.rep.post(
        "/api/rep/nominate", json={"candidate_id": candidate.user_id}
    ).get_json()["nomination"]["id"]
    for voter in setup.members[2:5]:
        assert voter.post(f"/api/rep/candidates/{nomination_id}/vote",
                          json={"vote": "YES"}).status_code == 201

    _archive(app, setup.rep.user_id, setup.community_id)

    clock.advance(timedelta(hours=25))
    run_worker()

    with app.app_context():
        from academicai.db.connection import query_one
        role = query_one("""SELECT role FROM community_members
                            WHERE user_id = ? AND community_id = ?""",
                         (candidate.user_id, setup.community_id))["role"]
        ballot = query_one("SELECT * FROM rep_nominations WHERE id = ?", (nomination_id,))

    assert role == "STUDENT"
    assert ballot["status"] == "FAILED"
    # The votes were real; the session ending is what stopped the promotion.
    assert ballot["yes_votes"] == 3


def test_a_candidate_promoted_nowhere_cannot_write(client, academic_community, app,
                                                   run_worker):
    """End-to-end: the exploit path, now closed."""
    setup = academic_community(size=6, seed_events=False)
    candidate = setup.members[1]
    nomination_id = setup.rep.post(
        "/api/rep/nominate", json={"candidate_id": candidate.user_id}
    ).get_json()["nomination"]["id"]
    for voter in setup.members[2:5]:
        voter.post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": "YES"})

    _archive(app, setup.rep.user_id, setup.community_id)
    clock.advance(timedelta(hours=25))
    run_worker()

    promoted = candidate.relogin()
    for path, payload in WRITES:
        assert promoted.post(path, json=payload).status_code == 403, path

    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one(
            "SELECT COUNT(*) AS n FROM academic_events WHERE title = ?",
            ("Post-archive",))["n"] == 0
        assert query_one(
            "SELECT COUNT(*) AS n FROM announcements WHERE title = ?",
            ("Post-archive",))["n"] == 0
        assert query_one(
            "SELECT COUNT(*) AS n FROM courses WHERE code = ?", ("DEAD101",))["n"] == 0


def test_archiving_mid_request_blocks_the_write(client, academic_community, app,
                                                monkeypatch):
    """Archive committing between the route gate and the service write."""
    from academicai.services import event_service

    setup = academic_community(size=5, seed_events=False)
    rep = setup.rep
    real = event_service.create_event

    def archive_then_create(actor_id, community_id, *a, **kw):
        _archive(app, actor_id, community_id)
        return real(actor_id, community_id, *a, **kw)

    monkeypatch.setattr(event_service, "create_event", archive_then_create)
    resp = rep.post("/api/events", json={"title": "Raced archive", "event_type": "QUIZ"})
    # Refused because archiving demoted them; either way the write is stopped.
    assert resp.status_code == 403

    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT COUNT(*) AS n FROM academic_events WHERE title = ?",
                         ("Raced archive",))["n"] == 0


def test_archived_status_alone_blocks_a_still_seated_rep(client, academic_community, app):
    """Isolates the community-status guard from the rep-role guard.

    Archiving normally demotes reps, so this marks the community ARCHIVED
    while deliberately leaving the rep seated - the state a mid-flight ballot
    used to produce - and checks the write boundary still refuses.
    """
    setup = academic_community(size=5, seed_events=False)
    with app.app_context():
        from academicai.db.connection import execute, transaction
        with transaction() as conn:
            execute("UPDATE academic_communities SET status = 'ARCHIVED' WHERE id = ?",
                    (setup.community_id,), conn=conn)

    assert setup.rep.get("/api/community").get_json()["membership"]["role"] == "VERIFIED_REP"

    for path, payload in WRITES:
        resp = setup.rep.post(path, json=payload)
        assert resp.status_code == 403, path
        assert resp.get_json()["details"]["community_status"] == "ARCHIVED", path

    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT COUNT(*) AS n FROM academic_events WHERE title = ?",
                         ("Post-archive",))["n"] == 0


def test_archived_status_blocks_edits_to_existing_records(client, academic_community, app):
    """Historical records must not become editable after the session ends."""
    setup = academic_community(size=5)
    event_id = setup.cos202_assignment["id"]
    with app.app_context():
        from academicai.db.connection import execute, transaction
        with transaction() as conn:
            execute("UPDATE academic_communities SET status = 'ARCHIVED' WHERE id = ?",
                    (setup.community_id,), conn=conn)

    assert setup.rep.put(f"/api/events/{event_id}",
                         json={"event_date": "2026-12-25"}).status_code == 403
    assert setup.rep.post(f"/api/events/{event_id}/cancel").status_code == 403


def test_archived_community_still_readable_by_its_members(client, academic_community, app):
    """Students keep their record; only writes are refused (spec 23)."""
    setup = academic_community(size=5)
    member = setup.members[1]
    _archive(app, setup.rep.user_id, setup.community_id)

    assert member.get("/api/community").status_code == 200
    assert member.get("/api/events").status_code == 200
    assert member.get("/api/community/changes").status_code == 200


def test_archival_stops_pending_notifications_and_reminders(client, academic_community, app):
    setup = academic_community(size=5)
    _archive(app, setup.rep.user_id, setup.community_id)
    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one(
            "SELECT COUNT(*) AS n FROM notifications WHERE community_id = ? AND status='PENDING'",
            (setup.community_id,))["n"] == 0
        assert query_one(
            """SELECT COUNT(*) AS n FROM event_reminders WHERE status = 'PENDING'
               AND event_id IN (SELECT id FROM academic_events WHERE community_id = ?)""",
            (setup.community_id,))["n"] == 0


def test_no_new_election_can_start_in_an_archived_community(client, academic_community, app):
    setup = academic_community(size=6, seed_events=False)
    _archive(app, setup.rep.user_id, setup.community_id)
    member = setup.members[1]
    resp = member.post("/api/rep/nominate", json={"candidate_id": member.user_id})
    assert resp.status_code == 409
