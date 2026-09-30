"""A reminder reaching its time: in the app at once, by email separately.

What these protect:

  TIMING     the worker wakes as a reminder comes due, not on its next fixed
             cycle; and the bell is told when the next reminder is due, so it
             can ask for the notification the moment the worker creates it.
  CHANNELS   the bell row is created when the reminder fires, and nothing that
             happens to its email - refused, retried, given up on - removes it,
             hides it, or marks it read.
  EMAIL      a provider's permanent refusal (4xx) is recorded once and not
             retried; network trouble and 429/5xx still are.
"""
import logging
from datetime import timedelta

import pytest

from academicai import clock
from academicai.services import email_service, reminder_service
from academicai.worker.jobs import reminders_due, run_once
from academicai.worker.worker import wait_for_next_cycle


def create_reminder(actor, title, at, **extra):
    resp = actor.post("/api/reminders", json={"title": title, "remind_at": at, **extra})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["reminder"]


def bell(actor):
    resp = actor.get("/api/notifications")
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def reminders_in(payload):
    return [n for n in payload["notifications"] if n["kind"] == "PERSONAL_REMINDER"]


# ── When to look: the bell's hint ──────────────────────────────────────────

def test_the_bell_is_told_when_the_next_reminder_is_due(client, academic_community, app):
    setup = academic_community(seed_events=False)
    student = setup.members[1]
    assert bell(student)["next_reminder_at"] is None

    soon = create_reminder(student, "Revise", (clock.now() + timedelta(minutes=5)).isoformat())
    later = create_reminder(student, "Pack", (clock.now() + timedelta(hours=3)).isoformat())
    assert bell(student)["next_reminder_at"] == soon["remind_at"]

    # Fired, it is no longer "next": the hint moves on to the one after.
    clock.advance(timedelta(minutes=6))
    with app.app_context():
        run_once()
    payload = bell(student)
    assert payload["next_reminder_at"] == later["remind_at"]
    assert [n["subject"] for n in reminders_in(payload)] == ["Revise"]


def test_the_hint_is_a_hint_and_creates_nothing(client, academic_community, app):
    """Past its time but not yet processed, the reminder is still 'next' - and
    there is still no notification. Only the worker makes one."""
    setup = academic_community(seed_events=False)
    student = setup.members[1]
    due = create_reminder(student, "Revise", (clock.now() + timedelta(minutes=1)).isoformat())
    clock.advance(timedelta(minutes=2))
    payload = bell(student)
    assert payload["next_reminder_at"] == due["remind_at"]
    assert reminders_in(payload) == []


def test_official_reminders_count_only_for_the_people_they_will_reach(
        client, academic_community, app):
    """The same recipient rule the worker applies: a course event's reminder is
    'next' only for students actively enrolled in that course."""
    from academicai.db.connection import query_one

    setup = academic_community(seed_events=False)
    student = setup.members[1]
    resp = setup.rep.post("/api/events", json={
        "title": "Heritage Seminar", "event_type": "PRESENTATION",
        "course_id": setup.courses["GEDS201"], "event_date": "2026-09-23"})
    assert resp.status_code == 201, resp.get_json()
    event_id = resp.get_json()["event"]["id"]
    with app.app_context():
        expected = query_one("SELECT remind_at FROM event_reminders WHERE event_id = ?",
                             (event_id,))["remind_at"]

    # Not enrolled in GEDS201: that reminder will not reach them.
    assert bell(student)["next_reminder_at"] is None
    student.post(f"/api/community/courses/{setup.courses['GEDS201']}/enroll")
    assert bell(student)["next_reminder_at"] == expected


def test_the_hint_never_describes_someone_elses_reminders(client, academic_community):
    setup = academic_community(seed_events=False)
    owner, other = setup.members[1], setup.members[2]
    create_reminder(owner, "Private", (clock.now() + timedelta(minutes=5)).isoformat())
    assert bell(other)["next_reminder_at"] is None


# ── When to run: the worker wakes as a reminder comes due ──────────────────

def test_reminders_due_is_true_exactly_while_one_waits(client, academic_community, app):
    setup = academic_community(seed_events=False)
    create_reminder(setup.members[1], "Revise",
                    (clock.now() + timedelta(minutes=2)).isoformat())
    with app.app_context():
        assert reminders_due() is False
    clock.advance(timedelta(minutes=3))
    with app.app_context():
        assert reminders_due() is True
        run_once()
        assert reminders_due() is False


def test_the_worker_wakes_early_for_a_due_reminder():
    slept = []
    answers = iter([False, False, True])
    outcome = wait_for_next_cycle(60, due=lambda: next(answers), step=2,
                                  sleep=slept.append, stopped=lambda: False)
    assert outcome == "due"
    assert sum(slept) == 6          # three checks, not the full minute


def test_with_nothing_due_the_worker_waits_its_interval():
    slept = []
    outcome = wait_for_next_cycle(15, due=lambda: False, step=2,
                                  sleep=slept.append, stopped=lambda: False)
    assert outcome == "interval"
    assert sum(slept) == 15         # the last step is shortened to fit


def test_the_worker_stops_promptly_while_waiting():
    outcome = wait_for_next_cycle(60, due=lambda: False, step=2,
                                  sleep=lambda s: None, stopped=lambda: True)
    assert outcome == "stopped"


def test_a_failed_due_check_does_not_stop_the_wait():
    def broken():
        raise RuntimeError("database is locked")
    outcome = wait_for_next_cycle(4, due=broken, step=2,
                                  sleep=lambda s: None, stopped=lambda: False)
    assert outcome == "interval"


# ── Two channels: email trouble never touches the bell ─────────────────────

def _fire(student, app, title="Revise for the quiz"):
    create_reminder(student, title, (clock.now() + timedelta(minutes=1)).isoformat())
    clock.advance(timedelta(minutes=2))
    with app.app_context():
        return run_once()


def test_a_refused_email_leaves_the_in_app_reminder_in_place(
        client, academic_community, app, caplog):
    setup = academic_community(seed_events=False)
    student = setup.members[1]

    def refuse(to, subject, body):
        raise email_service.EmailDeliveryError(
            "Resend rejected the message (403): testing emails only", permanent=True)

    email_service.set_failure_hook(refuse)
    with caplog.at_level(logging.WARNING, logger="academicai.notifications"):
        results = _fire(student, app)
    assert results["dispatch_notifications"]["failed"] >= 1

    # In the app: there, unread, counted - exactly as if the email had gone.
    payload = bell(student)
    fired = reminders_in(payload)
    assert [n["subject"] for n in fired] == ["Revise for the quiz"]
    assert fired[0]["read_at"] is None
    assert payload["unread"] >= 1
    # The delivery state is not part of what the student is shown.
    assert "status" not in fired[0]

    # The email: failed once, not retried, and logged with its reason.
    from academicai.db.connection import query_one
    with app.app_context():
        row = query_one("SELECT * FROM notifications WHERE kind = 'PERSONAL_REMINDER'")
    assert row["status"] == "FAILED"
    assert row["attempts"] == 1
    assert "403" in row["last_error"]
    assert any("permanent, not retried" in r.getMessage() for r in caplog.records)

    # Later cycles do not ask the provider again, and the bell is unchanged.
    for _ in range(3):
        with app.app_context():
            run_once()
    with app.app_context():
        assert query_one("SELECT attempts FROM notifications WHERE id = ?",
                         (row["id"],))["attempts"] == 1
    assert [n["subject"] for n in reminders_in(bell(student))] == ["Revise for the quiz"]


def test_a_transient_failure_is_still_retried(client, academic_community, app):
    setup = academic_community(seed_events=False)
    student = setup.members[1]

    def unreachable(to, subject, body):
        raise email_service.EmailDeliveryError("Could not reach Resend: timed out")

    email_service.set_failure_hook(unreachable)
    _fire(student, app)
    from academicai.db.connection import query_one
    with app.app_context():
        row = query_one("SELECT * FROM notifications WHERE kind = 'PERSONAL_REMINDER'")
    assert row["status"] == "PENDING"      # will be asked again
    assert row["attempts"] == 1
    assert reminders_in(bell(student))       # and it is in the bell meanwhile


def test_email_giving_up_does_not_mark_the_reminder_read(client, academic_community, app):
    setup = academic_community(seed_events=False)
    student = setup.members[1]
    email_service.set_failure_hook(
        lambda to, subject, body: (_ for _ in ()).throw(RuntimeError("smtp down")))
    _fire(student, app)
    for _ in range(6):
        with app.app_context():
            run_once()
    fired = reminders_in(bell(student))
    assert len(fired) == 1 and fired[0]["read_at"] is None


# ── What the toast says ────────────────────────────────────────────────────

def test_a_reminder_linked_to_an_event_says_what_is_due_and_when(
        client, academic_community, app):
    setup = academic_community()
    student = setup.members[1]
    event = setup.cos202_assignment      # COS202 Assignment, due 2026-09-18
    create_reminder(student, "COS202 Assignment",
                    (clock.now() + timedelta(minutes=1)).isoformat(), event_id=event["id"])
    clock.advance(timedelta(minutes=2))
    with app.app_context():
        run_once()

    fired = reminders_in(bell(student))
    assert fired[0]["subject"] == "COS202 Assignment"
    # A full day, never "today": the bell's history is read again later.
    assert fired[0]["body"].startswith("Due Friday 18 September")

    from academicai.db.connection import query_one
    with app.app_context():
        email = query_one("SELECT body FROM notifications WHERE kind = 'PERSONAL_REMINDER'")
    assert "Your personal reminder: COS202 Assignment" in email["body"]
    assert "Due Friday 18 September" in email["body"]


# ── Resend: which refusals are permanent ───────────────────────────────────

@pytest.mark.parametrize("status,permanent", [
    (400, True), (403, True), (422, True),     # the provider said no to THIS message
    (408, False), (429, False), (500, False), (503, False),
])
def test_which_provider_refusals_are_permanent(app, status, permanent):
    import io
    import urllib.error
    from unittest import mock

    error = urllib.error.HTTPError("https://api.resend.com/emails", status, "refused", {},
                                   io.BytesIO(b'{"message":"no"}'))
    with app.app_context():
        app.config.update({"EMAIL_BACKEND": "resend", "RESEND_API_KEY": "re_test",
                           "EMAIL_FROM": "AcademicAI <onboarding@resend.dev>"})
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(email_service.EmailDeliveryError) as excinfo:
                email_service.send("someone@example.com", "s", "b")
    assert excinfo.value.permanent is permanent
    assert str(status) in str(excinfo.value)


def test_a_permanent_refusal_is_not_retried_by_the_outbox(client, academic_community, app):
    """Direct check on dispatch: one attempt, FAILED, reason kept."""
    from academicai.db.connection import query_all
    from academicai.services import notification_service

    setup = academic_community(seed_events=False)
    setup.rep.post("/api/community/announcements", json={"title": "Probe", "body": "b"})
    email_service.set_failure_hook(lambda to, subject, body: (_ for _ in ()).throw(
        email_service.EmailDeliveryError("refused (403)", permanent=True)))
    with app.app_context():
        notification_service.dispatch_pending()
        notification_service.dispatch_pending()
        rows = query_all("SELECT status, attempts FROM notifications WHERE subject LIKE '%Probe%'")
    assert rows
    assert {(r["status"], r["attempts"]) for r in rows} == {("FAILED", 1)}


@pytest.mark.sqlite_only       # total_changes() is SQLite's
def test_reminder_service_exposes_no_decision(app):
    """any_due and next_due_for_user read; neither writes. (A guard against a
    future change that makes the hint 'helpfully' fire something.)"""
    with app.app_context():
        from academicai.db.connection import query_one
        before = query_one("SELECT total_changes() AS n")["n"]
        reminder_service.any_due()
        reminder_service.next_due_for_user(1)
        after = query_one("SELECT total_changes() AS n")["n"]
    assert before == after
