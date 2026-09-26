"""The bell speaks to a student; the email carries the detail.

One notifications row is both an email and an in-app notification. These
protect the split: the bell reads a short, plain `app_subject`/`app_body`, a
kind it can label and a link it can open, while the email keeps the wording
that stands on its own without the app (spec 19).
"""
import re
from datetime import timedelta

from academicai import clock
from academicai.db.connection import execute, query_all

ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
RAW_TOKEN = re.compile(r"\b[A-Z][A-Z_]{4,}\b")


def bell(actor):
    resp = actor.get("/api/notifications")
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["notifications"]


def assert_bell_readable(item):
    text = f"{item['subject']} {item['body'] or ''}"
    assert not ISO_DATE.search(text), f"ISO date in the bell: {text!r}"
    assert not RAW_TOKEN.search(text.replace(item["subject"], "")), \
        f"raw token in the bell body: {text!r}"
    assert "->" not in text and "\n" not in text


def only(items, kind):
    found = [n for n in items if n["kind"] == kind]
    assert found, f"no {kind} notification in {items!r}"
    return found[0]


def test_a_new_event_is_named_and_links_to_itself(client, academic_community):
    setup = academic_community()
    student = setup.members[1]
    event = setup.cos202_assignment

    item = only(bell(student), "EVENT_CREATED")
    assert item["subject"] == "COS202 Assignment (COS202)"
    assert item["body"] == "A new assignment was added for COS202, due Friday 18 September."
    assert item["link"] == f"/events/{event['id']}"
    assert_bell_readable(item)


def test_the_email_keeps_its_full_detail(client, academic_community, app):
    """The email half is unchanged: it must be understood without the app."""
    academic_community()
    with app.app_context():
        rows = query_all("SELECT subject, body, app_subject FROM notifications "
                         "WHERE subject = 'New assignment: COS202 Assignment'")
    assert rows, "the email subject is still the detailed one"
    assert "Date: 2026-09-18" in rows[0]["body"]
    assert rows[0]["app_subject"] == "COS202 Assignment (COS202)"


def test_a_moved_deadline_says_from_and_to(client, academic_community):
    setup = academic_community()
    event = setup.cos202_assignment
    resp = setup.rep.put(f"/api/events/{event['id']}", json={
        "event_date": "2026-09-21", "expected_version": event["version"]})
    assert resp.status_code == 200, resp.get_json()

    item = only(bell(setup.members[1]), "EVENT_CHANGED")
    assert item["subject"] == "COS202 Assignment (COS202)"
    assert item["body"] == ("The deadline moved from Friday 18 September "
                            "to Monday 21 September.")
    assert item["link"] == f"/events/{event['id']}"
    assert_bell_readable(item)


def test_a_venue_change_names_both_venues(client, academic_community):
    setup = academic_community()
    event = setup.cos202_assignment
    setup.rep.put(f"/api/events/{event['id']}", json={
        "venue": "LT3", "expected_version": event["version"]})
    resp = setup.rep.get(f"/api/events/{event['id']}")
    current = resp.get_json()["event"]
    setup.rep.put(f"/api/events/{event['id']}", json={
        "venue": "B107", "expected_version": current["version"]})

    changes = [n for n in bell(setup.members[1]) if n["kind"] == "EVENT_CHANGED"]
    assert changes[0]["body"] == "The venue changed from LT3 to B107."
    assert changes[1]["body"] == "The venue is now LT3."


def test_a_cancellation_says_what_was_cancelled_and_when(client, academic_community):
    setup = academic_community()
    event = setup.cos202_assignment
    resp = setup.rep.post(f"/api/events/{event['id']}/cancel",
                          json={"expected_version": event["version"]})
    assert resp.status_code == 200, resp.get_json()

    item = only(bell(setup.members[1]), "EVENT_CANCELLED")
    assert item["subject"] == "COS202 Assignment (COS202)"
    assert item["body"] == "This assignment, planned for Friday 18 September, has been cancelled."
    assert item["link"] == f"/events/{event['id']}"
    assert_bell_readable(item)


def test_an_event_reminder_does_not_repeat_the_word_reminder(
        client, academic_community, run_worker):
    setup = academic_community()
    student = setup.members[1]
    # The assignment is due on the 18th; its reminder fires the day before.
    clock.freeze(clock.now().replace(month=9, day=17, hour=9, minute=0))
    run_worker()
    student.relogin()

    item = only(bell(student), "EVENT_REMINDER")
    # The kind label says "Reminder"; subject and body do not repeat it.
    assert "Reminder" not in item["subject"] and "reminder" not in (item["body"] or "")
    assert item["subject"] == "COS202 Assignment (COS202)"
    assert item["body"] == "Due Friday 18 September."
    assert item["link"] == f"/events/{setup.cos202_assignment['id']}"
    assert_bell_readable(item)


def test_an_announcement_is_short_and_linked(client, academic_community):
    setup = academic_community()
    long_body = "The e-learning portal is offline on Friday evening. " * 6
    resp = setup.rep.post("/api/community/announcements",
                          json={"title": "Portal maintenance", "body": long_body})
    assert resp.status_code == 201, resp.get_json()

    item = only(bell(setup.members[1]), "ANNOUNCEMENT")
    assert item["subject"] == "Portal maintenance"
    assert item["link"] == "/community"
    assert len(item["body"]) <= 160 and item["body"].endswith("…")


def test_timetable_changes_are_labelled_and_linked(client, academic_community):
    setup = academic_community()
    student = setup.members[1]
    entry = setup.rep.get("/api/community/timetable").get_json()["timetable"]
    cos202 = next(e for e in entry if e["id"] == setup.cos202_class)
    resp = setup.rep.put(f"/api/community/timetable/{setup.cos202_class}",
                         json={"venue": "LT4", "expected_version": cos202["version"]})
    assert resp.status_code == 200, resp.get_json()
    resp = setup.rep.delete(f"/api/community/timetable/{setup.philosophy_entry}")
    assert resp.status_code == 200, resp.get_json()

    items = [n for n in bell(student) if n["kind"] == "TIMETABLE"]
    removed, changed = items[0], items[1]
    assert removed["subject"] == "Class removed from your timetable"
    assert removed["body"] == "Philosophy on Thursdays at 10:00 in B007 is no longer on the timetable."
    assert changed["subject"] == "Timetable changed"
    assert changed["body"] == "Data Structures on Wednesdays at 08:00 in LT4 has changed."
    for item in items:
        assert item["link"] == "/community"
        assert_bell_readable(item)


def test_a_row_queued_before_in_app_wording_still_shows(client, academic_community, app):
    """Older rows have no app_subject: the bell falls back to the email
    wording rather than showing nothing."""
    setup = academic_community()
    student = setup.members[1]
    with app.app_context():
        execute("""INSERT INTO notifications
                   (user_id, community_id, subject, body, status, created_at)
                   VALUES (?, ?, 'Legacy subject', 'Legacy body', 'SENT', ?)""",
                (student.user_id, setup.community_id, clock.now_iso()))
    legacy = [n for n in bell(student) if n["subject"] == "Legacy subject"]
    assert legacy and legacy[0]["body"] == "Legacy body"


def test_a_legacy_notifications_table_gains_the_in_app_columns(tmp_path):
    """A deployed database from before the in-app wording existed: the old
    three-status CHECK, no kind/link/read_at, one queued row. Start-up must add
    the columns AND survive the status rebuild with them, keeping the row."""
    import sqlite3 as sq

    from academicai.app import create_app
    from academicai.config import Config

    path = str(tmp_path / "legacy_notifications.db")
    conn = sq.connect(path)
    conn.executescript("""
        CREATE TABLE universities (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                                   created_at TEXT NOT NULL);
        CREATE TABLE users (id INTEGER PRIMARY KEY, full_name TEXT, email TEXT UNIQUE,
            password_hash TEXT, email_verified INTEGER DEFAULT 1,
            identity_status TEXT DEFAULT 'VERIFIED', token_epoch INTEGER DEFAULT 1,
            university_id INTEGER, department TEXT, level TEXT, academic_session TEXT,
            created_at TEXT, updated_at TEXT);
        CREATE TABLE academic_communities (id INTEGER PRIMARY KEY, university_id INTEGER,
            department TEXT, level TEXT, academic_session TEXT,
            status TEXT DEFAULT 'ACTIVE', created_at TEXT, updated_at TEXT);
        CREATE TABLE notifications (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            community_id INTEGER REFERENCES academic_communities(id),
            subject TEXT NOT NULL, body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING'
                   CHECK (status IN ('PENDING','SENT','FAILED')),
            attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
            dedupe_key TEXT UNIQUE, created_at TEXT NOT NULL, sent_at TEXT);
        INSERT INTO universities VALUES (1, 'Babcock University', 'x');
        INSERT INTO users (id, full_name, email, university_id)
            VALUES (1, 'Legacy', 'l@student.babcock.edu.ng', 1);
        INSERT INTO academic_communities (id, university_id, department, level, academic_session)
            VALUES (1, 1, 'SE', '200', '2026/2027');
        INSERT INTO notifications (user_id, community_id, subject, body, created_at)
            VALUES (1, 1, 'Old subject', 'Old body', '2026-09-01T08:00:00+00:00');
    """)
    conn.commit()
    conn.close()

    class LegacyConfig(Config):
        DATABASE_PATH = path
        TESTING = True
        SECRET_KEY = "x"

    create_app(LegacyConfig)

    conn = sq.connect(path)
    conn.row_factory = sq.Row
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(notifications)")}
    assert {"kind", "link", "read_at", "app_subject", "app_body"} <= columns
    row = conn.execute("SELECT * FROM notifications").fetchone()
    assert (row["subject"], row["body"], row["app_subject"]) == ("Old subject", "Old body", None)
    table_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'notifications'").fetchone()["sql"]
    assert "'SIMULATED'" in table_sql
    conn.close()
