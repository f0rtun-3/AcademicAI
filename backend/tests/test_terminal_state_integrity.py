"""Terminal states are terminal (spec 18).

Regressions for a confirmed defect: a withdrawn announcement and a cancelled
timetable entry could each be re-transitioned and edited. Each repeat wrote a
change_history row claiming a PUBLISHED -> WITHDRAWN (or ACTIVE -> CANCELLED)
transition that had not happened, so the audit trail recorded transitions that
were false. academic_events already guarded this; these two did not.
"""
import pytest

pytestmark = pytest.mark.security


def _history(app, entity_type, entity_id):
    with app.app_context():
        from academicai.db.connection import query_all
        return [r["change_type"] for r in query_all(
            "SELECT change_type FROM change_history WHERE entity_type = ? AND entity_id = ?",
            (entity_type, entity_id))]


# --- Announcements ---------------------------------------------------------

def test_an_announcement_cannot_be_withdrawn_twice(client, academic_community, app):
    setup = academic_community(size=5, seed_events=False)
    ann = setup.rep.post("/api/community/announcements",
                         json={"title": "A", "body": "b"}).get_json()["announcement"]

    assert setup.rep.delete(f"/api/community/announcements/{ann['id']}").status_code == 200
    second = setup.rep.delete(f"/api/community/announcements/{ann['id']}")
    assert second.status_code == 409
    assert second.get_json()["details"]["status"] == "WITHDRAWN"

    assert _history(app, "announcement", ann["id"]).count("ANNOUNCEMENT_WITHDRAWN") == 1


def test_a_withdrawn_announcement_cannot_be_edited(client, academic_community, app):
    setup = academic_community(size=5, seed_events=False)
    ann = setup.rep.post("/api/community/announcements",
                         json={"title": "Original", "body": "b"}).get_json()["announcement"]
    setup.rep.delete(f"/api/community/announcements/{ann['id']}")

    resp = setup.rep.put(f"/api/community/announcements/{ann['id']}",
                         json={"title": "Edited after withdrawal"})
    assert resp.status_code == 409

    with app.app_context():
        from academicai.db.connection import query_one
        row = query_one("SELECT title, status FROM announcements WHERE id = ?", (ann["id"],))
        assert row["title"] == "Original"
        assert row["status"] == "WITHDRAWN"
    assert "ANNOUNCEMENT_UPDATED" not in _history(app, "announcement", ann["id"])


# --- Timetable entries -----------------------------------------------------

def test_a_timetable_entry_cannot_be_cancelled_twice(client, academic_community, app):
    setup = academic_community(size=5)
    entry = setup.rep.get("/api/community/timetable").get_json()["timetable"][0]

    assert setup.rep.delete(f"/api/community/timetable/{entry['id']}").status_code == 200
    with app.app_context():
        from academicai.db.connection import query_one
        after_first = query_one("SELECT version FROM timetable_entries WHERE id = ?",
                                (entry["id"],))["version"]

    second = setup.rep.delete(f"/api/community/timetable/{entry['id']}")
    assert second.status_code == 409
    assert second.get_json()["details"]["status"] == "CANCELLED"

    with app.app_context():
        from academicai.db.connection import query_one
        # The refused call must not bump the version either.
        assert query_one("SELECT version FROM timetable_entries WHERE id = ?",
                         (entry["id"],))["version"] == after_first
    assert _history(app, "timetable_entry", entry["id"]).count("TIMETABLE_CANCELLED") == 1


def test_a_cancelled_timetable_entry_cannot_be_edited(client, academic_community, app):
    setup = academic_community(size=5)
    entry = setup.rep.get("/api/community/timetable").get_json()["timetable"][0]
    setup.rep.delete(f"/api/community/timetable/{entry['id']}")

    resp = setup.rep.put(f"/api/community/timetable/{entry['id']}",
                         json={"venue": "Edited after cancel"})
    assert resp.status_code == 409

    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT venue FROM timetable_entries WHERE id = ?",
                         (entry["id"],))["venue"] != "Edited after cancel"


def test_events_still_guard_their_terminal_state(client, academic_community):
    """The behaviour the other two now match."""
    setup = academic_community(size=5)
    event = setup.cos202_assignment
    current = setup.rep.get(f"/api/events/{event['id']}").get_json()["event"]

    assert setup.rep.post(f"/api/events/{event['id']}/cancel",
                          json={"expected_version": current["version"]}).status_code == 200
    latest = setup.rep.get(f"/api/events/{event['id']}").get_json()["event"]
    assert setup.rep.post(f"/api/events/{event['id']}/cancel",
                          json={"expected_version": latest["version"]}).status_code == 409
    assert setup.rep.put(f"/api/events/{event['id']}",
                         json={"venue": "X",
                               "expected_version": latest["version"]}).status_code == 409


# --- The reminder worker must not act on a stale event status --------------

def test_a_reminder_is_not_sent_for_an_event_cancelled_after_the_batch_read(
        client, academic_community, app):
    """Regression: the worker checked the status captured when it selected the
    batch, so an event cancelled in between was still reminded about."""
    from academicai import clock
    from academicai.services import reminder_service

    setup = academic_community(size=5, seed_events=False)
    event = setup.rep.post("/api/events", json={
        "title": "Stale reminder", "event_type": "ASSIGNMENT",
        "event_date": "2026-09-20"}).get_json()["event"]

    clock.freeze(clock.parse_iso("2026-09-19T08:00:00+00:00"))

    real_execute = reminder_service.execute
    injected = {"done": False}

    def cancel_while_claiming(sql, params=(), conn=None):
        result = real_execute(sql, params, conn=conn)
        if not injected["done"] and "event_reminders" in sql and "SENT" in sql:
            injected["done"] = True
            real_execute("UPDATE academic_events SET status = 'CANCELLED' WHERE id = ?",
                         (event["id"],), conn=conn)
        return result

    reminder_service.execute = cancel_while_claiming
    try:
        with app.app_context():
            reminder_service.process_due_event_reminders()
    finally:
        reminder_service.execute = real_execute

    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT status FROM academic_events WHERE id = ?",
                         (event["id"],))["status"] == "CANCELLED"
        assert query_one(
            "SELECT COUNT(*) AS n FROM notifications WHERE subject LIKE ?",
            ("Reminder: Stale%",))["n"] == 0
        assert injected["done"], "the injection never ran; the test proves nothing"


def test_a_scheduled_event_still_reminds_normally(client, academic_community, app,
                                                  run_worker):
    """The fix must not suppress legitimate reminders."""
    from academicai import clock

    setup = academic_community(size=5, seed_events=False)
    setup.rep.post("/api/events", json={
        "title": "Live reminder", "event_type": "ASSIGNMENT",
        "event_date": "2026-09-20"})

    clock.freeze(clock.parse_iso("2026-09-19T08:00:00+00:00"))
    run_worker()

    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT COUNT(*) AS n FROM notifications WHERE subject LIKE ?",
                         ("Reminder: Live%",))["n"] > 0
