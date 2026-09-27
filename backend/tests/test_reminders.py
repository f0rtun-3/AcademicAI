"""Reminders: official scheduling and personal reminders (spec 20)."""
from datetime import timedelta

import pytest

from academicai import clock
from academicai.services import email_service


def test_reminder_is_scheduled_one_day_before_at_0800(client, academic_community, app):
    setup = academic_community(seed_events=False)
    event = setup.rep.post("/api/events", json={
        "title": "COS202 Quiz", "event_type": "QUIZ",
        "course_id": setup.courses["COS202"], "event_date": "2026-09-25"}).get_json()["event"]
    with app.app_context():
        from academicai.db.connection import query_all
        rows = query_all("SELECT * FROM event_reminders WHERE event_id = ?", (event["id"],))
        assert len(rows) == 1
        # 08:00 on the university's clock (Babcock: Africa/Lagos, UTC+1) is
        # 07:00 UTC - not 08:00 UTC, which fired at 09:00 in Lagos.
        assert rows[0]["remind_at"] == "2026-09-24T07:00:00+00:00"
        assert rows[0]["status"] == "PENDING"


def test_event_without_a_date_gets_no_reminder(client, academic_community, app):
    setup = academic_community(seed_events=False)
    event = setup.rep.post("/api/events", json={
        "title": "TBD Quiz", "event_type": "QUIZ"}).get_json()["event"]
    with app.app_context():
        from academicai.db.connection import query_all
        assert query_all("SELECT * FROM event_reminders WHERE event_id = ?",
                         (event["id"],)) == []


def test_deadline_change_cancels_old_and_schedules_new(client, academic_community, app):
    """When a deadline changes: cancel the old reminder, schedule a new one (spec 20)."""
    setup = academic_community(seed_events=False)
    event = setup.rep.post("/api/events", json={
        "title": "COS202 Quiz", "event_type": "QUIZ",
        "course_id": setup.courses["COS202"], "event_date": "2026-09-25"}).get_json()["event"]
    setup.rep.put(f"/api/events/{event['id']}", json={"event_date": "2026-10-02"})
    with app.app_context():
        from academicai.db.connection import query_all
        rows = query_all("SELECT * FROM event_reminders WHERE event_id = ? ORDER BY id",
                         (event["id"],))
        assert len(rows) == 2
        assert rows[0]["status"] == "CANCELLED"
        assert rows[1]["status"] == "PENDING"
        assert rows[1]["remind_at"] == "2026-10-01T07:00:00+00:00"   # 08:00 Lagos


def test_cancelling_an_event_cancels_future_reminders(client, academic_community, app):
    setup = academic_community(seed_events=False)
    event = setup.rep.post("/api/events", json={
        "title": "COS202 Quiz", "event_type": "QUIZ",
        "course_id": setup.courses["COS202"], "event_date": "2026-09-25"}).get_json()["event"]
    setup.rep.post(f"/api/events/{event['id']}/cancel")
    with app.app_context():
        from academicai.db.connection import query_all
        rows = query_all("SELECT * FROM event_reminders WHERE event_id = ?", (event["id"],))
        assert all(r["status"] == "CANCELLED" for r in rows)


def test_due_reminder_emails_enrolled_students(client, academic_community, run_worker):
    setup = academic_community(seed_events=False)
    setup.rep.post("/api/events", json={
        "title": "COS202 Quiz", "event_type": "QUIZ",
        "course_id": setup.courses["COS202"], "event_date": "2026-09-25"})
    run_worker()
    email_service.clear()

    clock.freeze(clock.parse_iso("2026-09-24T08:30:00+00:00"))
    run_worker()
    subjects = [m["subject"] for m in email_service.sent_messages()]
    assert any("Reminder: COS202 Quiz" == s for s in subjects)


def test_reminder_recipients_resolve_at_fire_time(client, academic_community, run_worker):
    """A student who leaves before the reminder fires is not reminded."""
    setup = academic_community(seed_events=False)
    setup.rep.post("/api/events", json={
        "title": "COS202 Quiz", "event_type": "QUIZ",
        "course_id": setup.courses["COS202"], "event_date": "2026-09-25"})
    run_worker()
    leaver = setup.members[2]
    leaver.post("/api/community/leave")

    email_service.clear()
    clock.freeze(clock.parse_iso("2026-09-24T08:30:00+00:00"))
    run_worker()
    reminded = {m["to"] for m in email_service.sent_messages()}
    assert leaver.email not in reminded


def test_reminder_firing_is_idempotent(client, academic_community, run_worker):
    setup = academic_community(seed_events=False)
    setup.rep.post("/api/events", json={
        "title": "COS202 Quiz", "event_type": "QUIZ",
        "course_id": setup.courses["COS202"], "event_date": "2026-09-25"})
    run_worker()
    clock.freeze(clock.parse_iso("2026-09-24T08:30:00+00:00"))
    run_worker()
    count = len(email_service.sent_messages())
    run_worker()
    run_worker()
    assert len(email_service.sent_messages()) == count


# --- Personal reminders ---------------------------------------------------

def test_student_creates_and_lists_a_personal_reminder(client, academic_community):
    setup = academic_community()
    student = setup.members[1]
    resp = student.post("/api/reminders", json={
        "title": "Start the COS202 assignment",
        "remind_at": "2026-09-16T18:00:00+00:00",
        "event_id": setup.cos202_assignment["id"]})
    assert resp.status_code == 201
    reminders = student.get("/api/reminders").get_json()["reminders"]
    assert [r["title"] for r in reminders] == ["Start the COS202 assignment"]


def test_personal_reminder_fires(client, academic_community, run_worker):
    setup = academic_community()
    student = setup.members[1]
    student.post("/api/reminders", json={
        "title": "Revise", "remind_at": "2026-09-16T18:00:00+00:00"})
    email_service.clear()
    clock.freeze(clock.parse_iso("2026-09-16T18:05:00+00:00"))
    run_worker()
    assert any(m["to"] == student.email and "Revise" in m["subject"]
               for m in email_service.sent_messages())


def test_personal_reminder_can_be_updated_and_cancelled(client, academic_community):
    setup = academic_community()
    student = setup.members[1]
    created = student.post("/api/reminders", json={
        "title": "Revise", "remind_at": "2026-09-16T18:00:00+00:00"}).get_json()["reminder"]
    updated = student.put(f"/api/reminders/{created['id']}",
                          json={"title": "Revise harder"}).get_json()["reminder"]
    assert updated["title"] == "Revise harder"
    assert student.delete(f"/api/reminders/{created['id']}").status_code == 200
    assert student.get("/api/reminders").get_json()["reminders"][0]["status"] == "CANCELLED"


def test_personal_reminder_requires_valid_timestamp(client, academic_community):
    setup = academic_community()
    resp = setup.members[1].post("/api/reminders",
                                 json={"title": "x", "remind_at": "not-a-date"})
    assert resp.status_code == 400


def test_marking_complete_is_personal_not_official(client, academic_community):
    """'Mark Complete' is personal state, never an event mutation (spec 28)."""
    setup = academic_community()
    student, other = setup.members[1], setup.members[2]
    event_id = setup.cos202_assignment["id"]
    assert student.post(f"/api/events/{event_id}/complete").status_code == 200

    mine = next(e for e in student.get("/api/events").get_json()["events"]
                if e["id"] == event_id)
    theirs = next(e for e in other.get("/api/events").get_json()["events"]
                  if e["id"] == event_id)
    assert mine["completed"] is True
    assert theirs["completed"] is False
    assert theirs["status"] == "SCHEDULED"
    assert mine["version"] == theirs["version"]     # official record untouched
