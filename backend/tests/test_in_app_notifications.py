"""In-app notifications: the bell, and who can see what.

The architecture rule these protect: the WORKER decides that a reminder fired.
A notification exists because a job processed a due row, never because a clock
somewhere reached a time. Nothing in the API creates one.

The privacy rule: a notification is one person's. Every read is scoped by
user_id in the query, and an id belonging to someone else is indistinguishable
from an id that does not exist.
"""
from datetime import timedelta

from academicai import clock
from academicai.worker.jobs import run_once


def create_reminder(actor, title, at):
    resp = actor.post("/api/reminders", json={"title": title, "remind_at": at})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["reminder"]


def bell(actor):
    resp = actor.get("/api/notifications")
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


# ── The worker is the authority ────────────────────────────────────────────

def test_a_due_reminder_produces_an_in_app_notification(client, academic_community, app):
    setup = academic_community()
    student = setup.members[1]
    due = (clock.now() + timedelta(minutes=5)).isoformat()
    reminder = create_reminder(student, "Revise for the quiz", due)

    # Before its time: nothing has happened, however long the page is open.
    clock.advance(timedelta(minutes=1))
    with app.app_context():
        run_once()
    assert [n for n in bell(student)["notifications"]
            if n["kind"] == "PERSONAL_REMINDER"] == []

    # The time passes — and STILL nothing, until the worker runs. The clock
    # reaching the hour is not the event; the job processing it is.
    clock.advance(timedelta(minutes=10))
    assert [n for n in bell(student)["notifications"]
            if n["kind"] == "PERSONAL_REMINDER"] == []

    with app.app_context():
        run_once()

    fired = [n for n in bell(student)["notifications"] if n["kind"] == "PERSONAL_REMINDER"]
    assert len(fired) == 1
    # The bell's kind label already says "Reminder", so the in-app wording
    # does not repeat it: the subject is the student's own title and there is
    # no body to add. The email keeps its "Reminder: …" subject.
    assert fired[0]["subject"] == "Revise for the quiz"
    assert fired[0]["body"] is None
    assert fired[0]["link"] == "/reminders"
    assert fired[0]["read_at"] is None

    # And the reminder itself is SENT — the two agree because they came from
    # the same transaction.
    row = [r for r in student.get("/api/reminders").get_json()["reminders"]
           if r["id"] == reminder["id"]][0]
    assert row["status"] == "SENT"


def test_an_event_reminder_links_to_the_record(client, academic_community, app):
    setup = academic_community()
    # Event reminders are scheduled when a rep publishes an event; advance to
    # the point the worker would fire them. The jump outlives the session
    # token, so sign back in — a harness detail, not the feature.
    clock.advance(timedelta(days=30))
    with app.app_context():
        run_once()
    student = setup.members[1].relogin()

    linked = [n for n in bell(student)["notifications"]
              if n["kind"] == "EVENT_REMINDER"]
    assert linked, "expected at least one event reminder"
    assert linked[0]["link"].startswith("/events/")


def test_the_worker_never_notifies_twice(client, academic_community, app):
    """Idempotence: a second cycle must not re-notify (spec 21)."""
    setup = academic_community()
    student = setup.members[1]
    create_reminder(student, "Only once", (clock.now() + timedelta(minutes=1)).isoformat())
    clock.advance(timedelta(minutes=5))
    with app.app_context():
        run_once()
        run_once()
        run_once()
    matching = [n for n in bell(student)["notifications"] if n["subject"] == "Only once"]
    assert len(matching) == 1


# ── Whose notifications ────────────────────────────────────────────────────

def test_a_student_sees_only_their_own(client, academic_community, app):
    setup = academic_community()
    mine, theirs = setup.members[1], setup.members[2]
    create_reminder(mine, "Mine alone", (clock.now() + timedelta(minutes=1)).isoformat())
    clock.advance(timedelta(minutes=5))
    with app.app_context():
        run_once()

    assert any(n["subject"] == "Mine alone" for n in bell(mine)["notifications"])
    assert not any(n["subject"] == "Mine alone"
                   for n in bell(theirs)["notifications"])


def test_marking_someone_elses_notification_is_a_404(client, academic_community, app):
    setup = academic_community()
    mine, theirs = setup.members[1], setup.members[2]
    create_reminder(mine, "Private", (clock.now() + timedelta(minutes=1)).isoformat())
    clock.advance(timedelta(minutes=5))
    with app.app_context():
        run_once()
    target = [n for n in bell(mine)["notifications"] if n["subject"] == "Private"][0]

    resp = theirs.post(f"/api/notifications/{target['id']}/read")
    assert resp.status_code == 404
    # ...and it is still unread for its actual owner.
    owned = [n for n in bell(mine)["notifications"] if n["id"] == target["id"]][0]
    assert owned["read_at"] is None


def test_an_id_that_does_not_exist_answers_the_same_as_one_that_is_not_yours(
        client, academic_community, app):
    """Otherwise the endpoint reports whether a stranger's row exists."""
    setup = academic_community()
    mine, theirs = setup.members[1], setup.members[2]
    create_reminder(mine, "Probe", (clock.now() + timedelta(minutes=1)).isoformat())
    clock.advance(timedelta(minutes=5))
    with app.app_context():
        run_once()
    real = [n for n in bell(mine)["notifications"] if n["subject"] == "Probe"][0]

    not_theirs = theirs.post(f"/api/notifications/{real['id']}/read")
    nonexistent = theirs.post("/api/notifications/999999/read")
    assert not_theirs.status_code == nonexistent.status_code == 404
    assert not_theirs.get_json()["message"] == nonexistent.get_json()["message"]


def test_marking_all_read_touches_nobody_else(client, academic_community, app):
    setup = academic_community()
    mine, theirs = setup.members[1], setup.members[2]
    for actor, title in ((mine, "Mine"), (theirs, "Theirs")):
        create_reminder(actor, title, (clock.now() + timedelta(minutes=1)).isoformat())
    clock.advance(timedelta(minutes=5))
    with app.app_context():
        run_once()

    assert bell(theirs)["unread"] > 0
    before = bell(theirs)["unread"]
    resp = mine.post("/api/notifications/read-all")
    assert resp.status_code == 200
    assert bell(mine)["unread"] == 0
    assert bell(theirs)["unread"] == before


def test_notifications_require_authentication(client, academic_community):
    academic_community()
    assert client.get("/api/notifications").status_code == 401
    assert client.post("/api/notifications/1/read").status_code == 401
    assert client.post("/api/notifications/read-all").status_code == 401


# ── Read state ─────────────────────────────────────────────────────────────

def test_read_state_persists_and_the_badge_follows_it(client, academic_community, app):
    setup = academic_community()
    student = setup.members[1]
    create_reminder(student, "Badge check", (clock.now() + timedelta(minutes=1)).isoformat())
    clock.advance(timedelta(minutes=5))
    with app.app_context():
        run_once()

    first = bell(student)
    assert first["unread"] >= 1
    target = [n for n in first["notifications"] if n["subject"] == "Badge check"][0]

    resp = student.post(f"/api/notifications/{target['id']}/read")
    assert resp.status_code == 200
    assert resp.get_json()["unread"] == first["unread"] - 1

    # Survives a fresh request, i.e. it is in the database, not in a component.
    after = bell(student)
    marked = [n for n in after["notifications"] if n["id"] == target["id"]][0]
    assert marked["read_at"] is not None
    assert after["unread"] == first["unread"] - 1

    # Marking twice is not an error and does not double-count.
    assert student.post(f"/api/notifications/{target['id']}/read").status_code == 200
    assert bell(student)["unread"] == after["unread"]


# ── The outbox is not the bell ─────────────────────────────────────────────

def test_delivery_state_is_never_reported_to_the_student(client, academic_community, app):
    """`status`/`attempts`/`last_error` describe the email outbox. Whether a
    message left the building is not a fact about the student's reminder, and
    showing it would claim a delivery we cannot currently make."""
    setup = academic_community()
    student = setup.members[1]
    create_reminder(student, "No delivery claims", (clock.now() + timedelta(minutes=1)).isoformat())
    clock.advance(timedelta(minutes=5))
    with app.app_context():
        run_once()

    for item in bell(student)["notifications"]:
        for leaked in ("status", "attempts", "last_error", "sent_at", "dedupe_key", "user_id"):
            assert leaked not in item, f"{leaked} must not reach the client"


def test_reading_a_notification_does_not_disturb_the_outbox(client, academic_community, app):
    """The two lifecycles are independent: marking read must not look like a
    delivery, and must not un-send or re-queue anything."""
    from academicai.db.connection import query_one

    setup = academic_community()
    student = setup.members[1]
    create_reminder(student, "Independent", (clock.now() + timedelta(minutes=1)).isoformat())
    clock.advance(timedelta(minutes=5))
    with app.app_context():
        run_once()
        target = query_one(
            "SELECT id, status FROM notifications WHERE subject = ?",
            ("Reminder: Independent",))
        before = target["status"]

    student.post(f"/api/notifications/{target['id']}/read")

    with app.app_context():
        after = query_one("SELECT status, read_at FROM notifications WHERE id = ?",
                          (target["id"],))
    assert after["status"] == before
    assert after["read_at"] is not None
