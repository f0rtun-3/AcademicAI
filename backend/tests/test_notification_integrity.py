"""Outbox integrity: recipients are server-decided and each message sends once.

Ensures two workers that read the same PENDING rows cannot both claim them:
the claim is a compare-and-swap on `attempts`, so only one sends each email.
"""
import pytest

from academicai.services import email_service, notification_service

pytestmark = pytest.mark.security


def _queue_announcement(setup, title="Outbox probe"):
    resp = setup.rep.post("/api/community/announcements",
                          json={"title": title, "body": "body"})
    assert resp.status_code == 201
    return resp


# --- Each message sends exactly once ---------------------------------------

def test_two_concurrent_workers_do_not_both_claim_a_row(client, academic_community, app):
    """Two passes that read before either marks SENT claim each row once."""
    setup = academic_community(size=5, seed_events=False)
    _queue_announcement(setup)
    email_service.clear()

    with app.app_context():
        batch = [dict(r) for r in notification_service.pending(100)]
        assert batch, "nothing queued"

        from academicai.db.connection import execute, transaction
        # Worker A claims every row.
        with transaction() as conn:
            claimed_a = []
            for row in batch:
                cur = execute(
                    """UPDATE notifications SET attempts = ?
                       WHERE id = ? AND attempts = ? AND status = 'PENDING'""",
                    (row["attempts"] + 1, row["id"], row["attempts"]), conn=conn)
                if cur.rowcount == 1:
                    claimed_a.append(row["id"])

        # Worker B, holding the same stale read, claims nothing.
        with transaction() as conn:
            claimed_b = []
            for row in batch:
                cur = execute(
                    """UPDATE notifications SET attempts = ?
                       WHERE id = ? AND attempts = ? AND status = 'PENDING'""",
                    (row["attempts"] + 1, row["id"], row["attempts"]), conn=conn)
                if cur.rowcount == 1:
                    claimed_b.append(row["id"])

    assert claimed_a, "worker A claimed nothing"
    assert claimed_b == [], "worker B re-claimed rows worker A already had"


def test_repeated_dispatch_handles_each_message_once(client, academic_community, app):
    """Exactly-once handling, counted under the test backend.

    The tests run on the `memory` backend, which does not deliver anything, so
    these messages are SIMULATED rather than SENT - the outbox no longer claims
    a delivery it did not make. The invariant under test is unchanged: a
    message is handled once and never picked up again.
    """
    setup = academic_community(size=5, seed_events=False)
    _queue_announcement(setup)
    email_service.clear()

    with app.app_context():
        first = notification_service.dispatch_pending()
        second = notification_service.dispatch_pending()
        third = notification_service.dispatch_pending()

    assert first["simulated"] > 0
    assert first["sent"] == 0, "the memory backend must never report a delivery"
    assert second == {"sent": 0, "failed": 0, "simulated": 0}
    assert third == {"sent": 0, "failed": 0, "simulated": 0}
    assert len(email_service.sent_messages()) == first["simulated"]


def test_running_the_whole_worker_twice_sends_once(client, academic_community, app):
    from academicai.worker.jobs import run_once

    setup = academic_community(size=5, seed_events=False)
    _queue_announcement(setup)
    email_service.clear()

    with app.app_context():
        run_once()
        after_first = len(email_service.sent_messages())
        run_once()
        after_second = len(email_service.sent_messages())

    assert after_first > 0
    assert after_second == after_first


def test_a_failed_delivery_can_still_be_retried(client, academic_community, app):
    """A transient failure must not consume the message permanently."""
    setup = academic_community(size=5, seed_events=False)
    _queue_announcement(setup)
    email_service.clear()

    calls = {"n": 0}

    def fail_once(to, subject, body):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("smtp unavailable")

    email_service.set_failure_hook(fail_once)
    with app.app_context():
        first = notification_service.dispatch_pending()
    email_service.set_failure_hook(None)

    assert first["failed"] == 2
    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one(
            "SELECT COUNT(*) AS n FROM notifications WHERE status = 'PENDING'")["n"] == 2
        second = notification_service.dispatch_pending()
    assert second["simulated"] == 2


def test_a_message_is_abandoned_after_the_retry_limit(client, academic_community, app):
    setup = academic_community(size=5, seed_events=False)
    _queue_announcement(setup)

    email_service.set_failure_hook(
        lambda to, subject, body: (_ for _ in ()).throw(RuntimeError("permanent")))
    try:
        with app.app_context():
            for _ in range(notification_service.MAX_ATTEMPTS + 2):
                notification_service.dispatch_pending()
            from academicai.db.connection import query_one
            assert query_one(
                "SELECT COUNT(*) AS n FROM notifications WHERE status = 'PENDING'")["n"] == 0
            assert query_one(
                "SELECT COUNT(*) AS n FROM notifications WHERE status = 'FAILED'")["n"] > 0
    finally:
        email_service.set_failure_hook(None)


def test_duplicate_queueing_is_rejected_by_the_dedupe_key(client, academic_community, app):
    setup = academic_community(size=5, seed_events=False)
    with app.app_context():
        from academicai.db.connection import query_one, transaction
        with transaction() as conn:
            recipients = notification_service.community_recipients(
                setup.community_id, conn=conn)
            first = notification_service.enqueue(
                recipients, setup.community_id, "S", "B",
                dedupe_key="probe:1", conn=conn)
            second = notification_service.enqueue(
                recipients, setup.community_id, "S", "B",
                dedupe_key="probe:1", conn=conn)
        assert first == len(recipients)
        assert second == 0


# --- Recipients are decided by the backend ---------------------------------

def test_a_rep_cannot_choose_the_recipients(client, academic_community, app):
    """Recipient lists are computed server-side from community and course."""
    setup = academic_community(size=5, seed_events=False)
    outsider = academic_community(size=4, department="Computer Science",
                                  seed_events=False)
    setup.rep.relogin()

    resp = setup.rep.post("/api/community/announcements", json={
        "title": "Targeted", "body": "x",
        "recipients": [outsider.rep.user_id],
        "user_ids": [outsider.rep.user_id],
        "community_id": outsider.community_id,
        "notify": [outsider.rep.user_id],
    })
    assert resp.status_code == 201

    with app.app_context():
        from academicai.db.connection import query_all
        rows = query_all(
            """SELECT n.user_id, n.community_id FROM notifications n
               WHERE n.subject LIKE ?""", ("%Targeted%",))
        assert rows
        for row in rows:
            assert row["community_id"] == setup.community_id
            assert row["user_id"] != outsider.rep.user_id


def test_a_student_cannot_trigger_an_official_notification(client, academic_community, app):
    setup = academic_community(size=5, seed_events=False)
    student = setup.members[1]
    with app.app_context():
        from academicai.db.connection import query_one
        before = query_one("SELECT COUNT(*) AS n FROM notifications")["n"]

    for path, payload in (("/api/community/announcements", {"title": "S", "body": "x"}),
                          ("/api/events", {"title": "S", "event_type": "QUIZ"})):
        assert student.post(path, json=payload).status_code == 403

    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT COUNT(*) AS n FROM notifications")["n"] == before


def test_course_notifications_reach_only_enrolled_active_members(client, academic_community,
                                                                 app):
    setup = academic_community(size=5, seed_events=False)
    course = setup.rep.post("/api/community/courses",
                            json={"code": "COS299"}).get_json()["course"]
    enrolled, absent = setup.members[1], setup.members[2]
    assert enrolled.post(f"/api/community/courses/{course['id']}/enroll").status_code == 201

    setup.rep.post("/api/events", json={
        "title": "Course scoped", "event_type": "ASSIGNMENT",
        "course_id": course["id"], "event_date": "2026-10-20"})

    with app.app_context():
        from academicai.db.connection import query_all
        recipients = {r["user_id"] for r in query_all(
            "SELECT user_id FROM notifications WHERE subject LIKE ?", ("%Course scoped%",))}
    assert enrolled.user_id in recipients
    assert absent.user_id not in recipients


def test_a_member_who_leaves_stops_receiving_queued_notifications(client, academic_community,
                                                                  app):
    setup = academic_community(size=5, seed_events=False)
    leaver = setup.members[1]
    _queue_announcement(setup, "Before leaving")
    leaver.post("/api/community/leave")

    with app.app_context():
        from academicai.db.connection import query_one
        row = query_one(
            """SELECT status FROM notifications
               WHERE user_id = ? AND subject LIKE ?""",
            (leaver.user_id, "%Before leaving%"))
        assert row["status"] == "FAILED"


def test_notification_status_values_stay_within_the_allowed_set(client, academic_community,
                                                                app):
    setup = academic_community(size=5, seed_events=False)
    _queue_announcement(setup)
    with app.app_context():
        notification_service.dispatch_pending()
        from academicai.db.connection import query_all
        statuses = {r["status"] for r in query_all("SELECT DISTINCT status FROM notifications")}
    assert statuses <= {"PENDING", "SENT", "SIMULATED", "FAILED"}
    # And on a backend that does not deliver, SENT must not be among them.
    assert "SENT" not in statuses
