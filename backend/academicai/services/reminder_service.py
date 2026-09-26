"""Reminders (spec 20).

Official reminders are derived from academic events: one reminder per event,
fired a fixed lead time before the deadline at a fixed server-local hour.
There is deliberately no per-user timezone in the MVP, but the firing time is
computed in one function so timezone support can be added there later without
touching call sites.

Personal reminders are separate from official academic records and belong to
one student.
"""
from datetime import datetime, time, timezone

from flask import current_app

from .. import clock
from ..db.connection import execute, insert_returning_id, query_all, query_one, transaction
from ..errors import NotFoundError, ValidationError
from . import notification_copy, notification_service


def compute_remind_at(event_date, lead_days=None, hour=None):
    """Reminder instant for a deadline date.

    Returns None when the event has no date - an explicitly unspecified date is
    not an error, it simply cannot carry a deadline reminder (spec 14).
    """
    if not event_date:
        return None
    lead_days = current_app.config["REMINDER_LEAD_DAYS"] if lead_days is None else lead_days
    hour = current_app.config["REMINDER_HOUR_LOCAL"] if hour is None else hour
    try:
        day = datetime.strptime(event_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    fire_day = day - clock.days(lead_days)
    return datetime.combine(fire_day, time(hour=hour), tzinfo=timezone.utc)


def cancel_for_event(event_id, conn=None):
    """Cancel outstanding reminders for an event. Used when a deadline moves or
    the event is cancelled (spec 20)."""
    cur = execute(
        """UPDATE event_reminders SET status = 'CANCELLED'
           WHERE event_id = ? AND status = 'PENDING'""",
        (event_id,), conn=conn,
    )
    return cur.rowcount


def schedule_for_event(event, conn=None):
    """Schedule the reminder for an event, if one is due in the future."""
    if event["status"] != "SCHEDULED":
        return None
    remind_at = compute_remind_at(event["event_date"])
    if remind_at is None or remind_at <= clock.now():
        return None
    reminder_id = insert_returning_id(
        """INSERT INTO event_reminders (event_id, remind_at, status, created_at)
           VALUES (?, ?, 'PENDING', ?)""",
        (event["id"], clock.to_iso(remind_at), clock.now_iso()), conn=conn,
    )
    return query_one("SELECT * FROM event_reminders WHERE id = ?", (reminder_id,), conn=conn)


def reschedule_for_event(event, conn=None):
    """Cancel the old reminder and schedule a replacement (spec 19, 20)."""
    cancelled = cancel_for_event(event["id"], conn=conn)
    created = schedule_for_event(event, conn=conn)
    return {"cancelled": cancelled, "scheduled": created["id"] if created else None}


def reminders_for_event(event_id, conn=None):
    return query_all("SELECT * FROM event_reminders WHERE event_id = ? ORDER BY id",
                     (event_id,), conn=conn)


def process_due_event_reminders(conn=None):
    """Fire due event reminders.

    Recipients resolve here rather than at scheduling time, so membership and
    enrollment changes between scheduling and firing are honoured.
    """
    due = query_all(
        """SELECT r.*, e.community_id, e.course_id, e.title, e.event_type,
                  e.event_date, e.event_time, e.venue, e.status AS event_status,
                  c.code AS course_code
           FROM event_reminders r JOIN academic_events e ON e.id = r.event_id
           LEFT JOIN courses c ON c.id = e.course_id
           WHERE r.status = 'PENDING' AND r.remind_at <= ?""",
        (clock.now_iso(),), conn=conn,
    )
    fired = 0
    for row in due:
        cur = execute(
            "UPDATE event_reminders SET status = 'SENT', sent_at = ? WHERE id = ? AND status = 'PENDING'",
            (clock.now_iso(), row["id"]), conn=conn,
        )
        if cur.rowcount == 0:
            continue  # another worker already fired it
        # Re-read the event INSIDE the claiming transaction. The status in
        # `row` was captured when the batch was selected; an event cancelled
        # between that read and this point would otherwise still be reminded
        # about, telling students to submit work that no longer exists.
        current = query_one("SELECT status FROM academic_events WHERE id = ?",
                            (row["event_id"],), conn=conn)
        if current is None or current["status"] != "SCHEDULED":
            continue  # cancelled after the reminder was queued
        when = row["event_date"] or "a date to be confirmed"
        body = (f"Reminder: {row['title']} ({row['event_type'].title()}) is due {when}"
                + (f" at {row['event_time']}" if row["event_time"] else "")
                + (f", venue {row['venue']}" if row["venue"] else "") + ".")
        notification_service.enqueue(
            notification_service.recipients_for(row["community_id"], row["course_id"], conn=conn),
            row["community_id"], f"Reminder: {row['title']}", body,
            dedupe_key=f"event_reminder:{row['id']}", conn=conn,
            # The bell opens the record this is about, and words it without
            # repeating "Reminder" - the kind label already says so.
            **notification_copy.event_reminder(row, row["course_code"]),
        )
        fired += 1
    return fired


# --- Personal reminders (spec 20, 28) -------------------------------------
#
# States are PENDING | SENT | CANCELLED. There is deliberately no COMPLETED
# state: cancelling a reminder and finishing the academic work it refers to are
# separate concepts, and completing an official event is recorded separately in
# personal_event_completions. Adding COMPLETED would be a schema change and is
# deferred to product refinement.

def _parse_remind_at(value):
    """The instant a personal reminder fires, from an ISO-8601 timestamp that
    STATES ITS OFFSET.

    The client turns the wall-clock time a student picked into an absolute
    instant in the student's own zone (DST included) and sends it with an
    offset or "Z". A timestamp without one is refused rather than guessed:
    reading "2026-09-27T08:00" as UTC is exactly how a Lagos reminder came to
    fire an hour late, and a guess cannot be right for every zone.
    """
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValidationError("remind_at must be an ISO-8601 timestamp.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(
            "remind_at must include a timezone offset, for example "
            "2026-09-27T08:00:00+01:00.")
    return parsed


def create_personal(user_id, data):
    title = (data.get("title") or "").strip()
    remind_at = (data.get("remind_at") or "").strip()
    if not title:
        raise ValidationError("A reminder title is required.")
    if not remind_at:
        raise ValidationError("remind_at is required.")
    parsed = _parse_remind_at(remind_at)

    event_id = data.get("event_id")
    with transaction() as conn:
        if event_id is not None:
            event = query_one("SELECT * FROM academic_events WHERE id = ?", (event_id,), conn=conn)
            if event is None:
                raise NotFoundError("Event not found.")
            # A personal reminder may only reference an event in the student's
            # own community (spec 4).
            member = query_one(
                """SELECT 1 FROM community_members
                   WHERE user_id = ? AND community_id = ? AND status = 'ACTIVE'""",
                (user_id, event["community_id"]), conn=conn,
            )
            if member is None:
                raise NotFoundError("Event not found.")
        reminder_id = insert_returning_id(
            """INSERT INTO personal_reminders (user_id, event_id, title, remind_at, status, created_at)
               VALUES (?, ?, ?, ?, 'PENDING', ?)""",
            (user_id, event_id, title, clock.to_iso(parsed), clock.now_iso()), conn=conn,
        )
        return query_one("SELECT * FROM personal_reminders WHERE id = ?", (reminder_id,), conn=conn)


def list_personal(user_id, conn=None):
    return query_all(
        "SELECT * FROM personal_reminders WHERE user_id = ? ORDER BY remind_at",
        (user_id,), conn=conn,
    )


def _owned(user_id, reminder_id, conn):
    row = query_one("SELECT * FROM personal_reminders WHERE id = ? AND user_id = ?",
                    (reminder_id, user_id), conn=conn)
    if row is None:
        raise NotFoundError("Reminder not found.")
    return row


def update_personal(user_id, reminder_id, data):
    with transaction() as conn:
        row = _owned(user_id, reminder_id, conn)
        title = (data.get("title") or row["title"]).strip()
        remind_at = data.get("remind_at")
        if remind_at:
            remind_at = clock.to_iso(_parse_remind_at(remind_at))
        else:
            remind_at = row["remind_at"]
        execute("UPDATE personal_reminders SET title = ?, remind_at = ? WHERE id = ?",
                (title, remind_at, reminder_id), conn=conn)
        return query_one("SELECT * FROM personal_reminders WHERE id = ?", (reminder_id,), conn=conn)


def delete_personal(user_id, reminder_id):
    with transaction() as conn:
        _owned(user_id, reminder_id, conn)
        execute("UPDATE personal_reminders SET status = 'CANCELLED' WHERE id = ?",
                (reminder_id,), conn=conn)
        return True


def process_due_personal_reminders(conn=None):
    due = query_all(
        """SELECT p.*, cm.community_id
           FROM personal_reminders p
           LEFT JOIN community_members cm
                  ON cm.user_id = p.user_id AND cm.status = 'ACTIVE'
           WHERE p.status = 'PENDING' AND p.remind_at <= ?""",
        (clock.now_iso(),), conn=conn,
    )
    fired = 0
    for row in due:
        cur = execute(
            "UPDATE personal_reminders SET status = 'SENT', sent_at = ? WHERE id = ? AND status = 'PENDING'",
            (clock.now_iso(), row["id"]), conn=conn,
        )
        if cur.rowcount == 0:
            continue
        notification_service.enqueue(
            [row["user_id"]], row["community_id"], f"Reminder: {row['title']}",
            f"Your personal reminder: {row['title']}",
            dedupe_key=f"personal_reminder:{row['id']}", conn=conn,
            # A personal reminder has no record of its own, so the bell opens
            # the list where the student can act on it.
            **notification_copy.personal_reminder(row),
        )
        fired += 1
    return fired


def reminder_payload(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "remind_at": row["remind_at"],
        "status": row["status"],
        "event_id": row["event_id"],
    }
