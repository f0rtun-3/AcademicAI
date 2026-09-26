"""Email notifications and recipient resolution (spec 19, 24)."""
from academicai.services import email_service
from tests.conftest import analyze


def _inboxes(run_worker):
    run_worker()
    return email_service.sent_messages()


def test_new_event_notifies_enrolled_students(client, academic_community, run_worker):
    setup = academic_community(seed_events=False)
    setup.rep.post("/api/events", json={
        "title": "COS202 Quiz", "event_type": "QUIZ",
        "course_id": setup.courses["COS202"], "event_date": "2026-09-25"})
    recipients = {m["to"] for m in _inboxes(run_worker)}
    # Everyone enrolled in COS202 in this community.
    for member in setup.members:
        assert member.email in recipients


def test_course_notifications_exclude_unenrolled_members(
        client, academic_community, run_worker):
    """Not every member is enrolled in every course (spec 24)."""
    setup = academic_community(seed_events=False)
    setup.rep.post("/api/community/courses", json={"code": "MTH101", "title": "Calculus"})
    course_id = next(c["id"] for c in
                     setup.rep.get("/api/community/courses").get_json()["courses"]
                     if c["code"] == "MTH101")
    setup.members[1].post(f"/api/community/courses/{course_id}/enroll")

    email_service.clear()
    setup.rep.post("/api/events", json={
        "title": "MTH101 Test", "event_type": "TEST",
        "course_id": course_id, "event_date": "2026-09-25"})
    recipients = {m["to"] for m in _inboxes(run_worker)}
    assert setup.members[1].email in recipients
    assert setup.members[2].email not in recipients


def test_community_wide_event_notifies_all_members(client, academic_community, run_worker):
    setup = academic_community(seed_events=False)
    email_service.clear()
    setup.rep.post("/api/events", json={
        "title": "General Exam Briefing", "event_type": "OTHER", "event_date": "2026-09-25"})
    recipients = {m["to"] for m in _inboxes(run_worker)}
    for member in setup.members:
        assert member.email in recipients


def test_announcement_notifies_the_community(client, academic_community, run_worker):
    setup = academic_community(seed_events=False)
    email_service.clear()
    setup.rep.post("/api/community/announcements",
                   json={"title": "Lecture hall moved", "body": "We are now in LT3."})
    messages = _inboxes(run_worker)
    assert any("Lecture hall moved" in m["subject"] for m in messages)
    assert any("LT3" in m["body"] for m in messages)


def test_deadline_change_email_explains_the_change(client, academic_community, run_worker):
    """Emails must be understandable without opening the app (spec 19)."""
    setup = academic_community()
    email_service.clear()
    setup.rep.put(f"/api/events/{setup.cos202_assignment['id']}",
                  json={"event_date": "2026-09-21"})
    messages = _inboxes(run_worker)
    body = next(m["body"] for m in messages if "Deadline changed" in m["subject"])
    assert "2026-09-18" in body and "2026-09-21" in body


def test_late_joiner_does_not_receive_earlier_notifications(
        client, academic_community, run_worker, verified_user):
    """Recipients resolve at publish time (spec 19)."""
    setup = academic_community(seed_events=False)
    setup.rep.post("/api/events", json={
        "title": "Early Quiz", "event_type": "QUIZ", "event_date": "2026-09-25"})
    run_worker()

    newcomer = verified_user(client)
    newcomer.post("/api/community/setup")
    newcomer.post("/api/community/join")
    setup.rep.post(f"/api/community/requests/{newcomer.user_id}/approve")

    email_service.clear()
    run_worker()
    assert newcomer.email not in {m["to"] for m in email_service.sent_messages()}
    # But the record itself is visible to them.
    titles = {e["title"] for e in newcomer.get("/api/events").get_json()["events"]}
    assert "Early Quiz" in titles


def test_student_who_left_stops_receiving_queued_notifications(
        client, academic_community, run_worker, app):
    setup = academic_community(seed_events=False)
    leaver = setup.members[1]
    setup.rep.post("/api/events", json={
        "title": "Quiz", "event_type": "QUIZ", "event_date": "2026-09-25"})
    leaver.post("/api/community/leave")
    email_service.clear()
    run_worker()
    assert leaver.email not in {m["to"] for m in email_service.sent_messages()}


def test_failed_delivery_is_retried_then_marked_failed(
        client, academic_community, run_worker, app):
    setup = academic_community(seed_events=False)
    setup.rep.post("/api/events", json={
        "title": "Quiz", "event_type": "QUIZ", "event_date": "2026-09-25"})

    def explode(to, subject, body):
        raise RuntimeError("smtp unavailable")

    quiz_rows = "SELECT * FROM notifications WHERE subject LIKE 'New quiz%'"
    email_service.set_failure_hook(explode)
    run_worker()
    with app.app_context():
        from academicai.db.connection import query_all
        rows = query_all(quiz_rows)
        assert rows
        assert all(r["status"] == "PENDING" for r in rows)   # retryable
        assert all(r["attempts"] == 1 for r in rows)

    for _ in range(5):
        run_worker()
    with app.app_context():
        from academicai.db.connection import query_all
        rows = query_all(quiz_rows)
        assert all(r["status"] == "FAILED" for r in rows)
        assert all(r["last_error"] for r in rows)

    # Recovery: a later success is still possible for new messages.
    email_service.set_failure_hook(None)


def test_notification_dispatch_is_idempotent(client, academic_community, run_worker, app):
    setup = academic_community(seed_events=False)
    setup.rep.post("/api/events", json={
        "title": "Quiz", "event_type": "QUIZ", "event_date": "2026-09-25"})
    run_worker()
    first = len(email_service.sent_messages())
    run_worker()
    run_worker()
    assert len(email_service.sent_messages()) == first


def test_duplicate_enqueue_is_deduplicated(client, academic_community, app):
    setup = academic_community(seed_events=False)
    with app.app_context():
        from academicai.db.connection import query_all, transaction
        from academicai.services import notification_service
        with transaction() as conn:
            notification_service.enqueue([setup.rep.user_id], setup.community_id,
                                         "Subject", "Body", dedupe_key="k1", conn=conn)
            notification_service.enqueue([setup.rep.user_id], setup.community_id,
                                         "Subject", "Body", dedupe_key="k1", conn=conn)
        rows = query_all("SELECT * FROM notifications WHERE dedupe_key LIKE 'k1%'")
        assert len(rows) == 1
