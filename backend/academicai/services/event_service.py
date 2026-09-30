"""Academic events (spec 13, 16, 17, 18, 19, 20).

Every mutation carries a version. A caller that acts on a stale version is
rejected with 409 rather than silently overwriting a newer state.

Changing an event does three further things, always in the same transaction as
the change itself: it records the transition in change history, it cancels and
reschedules reminders, and it queues notifications for affected students.
"""
import re

from .. import clock
from ..db.connection import execute, insert_returning_id, query_all, query_one, transaction
from ..errors import ConflictError, NotFoundError, ValidationError
from ..security import authz
from . import course_service, notification_copy, notification_service, reminder_service
from .change_history import record_change

# PROJECT sits beside ASSIGNMENT: both are work with a deadline and both may
# carry the original brief as supporting material. It is a separate type
# rather than an assignment with a label, because a student filtering their
# calendar for projects means something different by it.
EVENT_TYPES = ("ASSIGNMENT", "PROJECT", "QUIZ", "TEST", "PRESENTATION",
               "EXAM", "CLASS", "OTHER")
PRIORITIES = ("LOW", "NORMAL", "HIGH")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")

# Fields a rep may change on an existing event.
MUTABLE_FIELDS = ("title", "description", "event_date", "event_time", "venue",
                  "priority", "course_id")

# Instructions are free text a rep typed, not a parsed value, so they are only
# bounded - never reformatted. A rep who pastes a lecturer's exact wording must
# get that wording back.
MAX_DESCRIPTION_LENGTH = 4000


def validate_description(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("Instructions must be text.")
    text = value.strip()
    if not text:
        return None          # an explicit blank is "none given", not an error
    if len(text) > MAX_DESCRIPTION_LENGTH:
        raise ValidationError(
            f"Instructions are limited to {MAX_DESCRIPTION_LENGTH} characters.")
    return text


def validate_event_type(value):
    value = (value or "").strip().upper()
    if value not in EVENT_TYPES:
        raise ValidationError(f"Event type must be one of: {', '.join(EVENT_TYPES)}.")
    return value


def validate_date(value):
    """None means explicitly unspecified, which is valid (spec 14)."""
    if value is None or value == "":
        return None
    if not DATE_RE.match(str(value)):
        raise ValidationError("Date must be in YYYY-MM-DD format.")
    return str(value)


def validate_time(value):
    if value is None or value == "":
        return None
    if not TIME_RE.match(str(value)):
        raise ValidationError("Time must be in HH:MM format.")
    return str(value)


def list_events(community_id, course_id=None, include_cancelled=True, conn=None):
    sql = """SELECT e.*, c.code AS course_code
             FROM academic_events e LEFT JOIN courses c ON c.id = e.course_id
             WHERE e.community_id = ?"""
    params = [community_id]
    if course_id is not None:
        sql += " AND e.course_id = ?"
        params.append(course_id)
    if not include_cancelled:
        sql += " AND e.status != 'CANCELLED'"
    # Undated events last; on the same day, an event with no time first (it is
    # "that day", which reads before its timed entries). Spelled out because
    # SQLite and PostgreSQL disagree on where NULL sorts by default.
    sql += (" ORDER BY (e.event_date IS NULL), e.event_date,"
            " (e.event_time IS NOT NULL), e.event_time, e.id")
    return query_all(sql, tuple(params), conn=conn)


def get_event(event_id, community_id, conn=None):
    """Scoped by community: an id from another community is a 404, never a leak."""
    row = query_one(
        """SELECT e.*, c.code AS course_code
           FROM academic_events e LEFT JOIN courses c ON c.id = e.course_id
           WHERE e.id = ? AND e.community_id = ?""",
        (event_id, community_id), conn=conn,
    )
    if row is None:
        raise NotFoundError("Event not found.")
    return row


def _resolve_course(community_id, course_id, conn):
    if course_id is None:
        return None
    course_service.get_course(course_id, community_id, conn=conn)
    return course_id


def create_event(actor_id, community_id, data, notify=True, conn=None):
    title = (data.get("title") or "").strip()
    if not title:
        raise ValidationError("An event title is required.")
    event_type = validate_event_type(data.get("event_type"))
    event_date = validate_date(data.get("event_date"))
    event_time = validate_time(data.get("event_time"))
    venue = (data.get("venue") or None)
    description = validate_description(data.get("description"))
    priority = (data.get("priority") or "NORMAL").upper()
    if priority not in PRIORITIES:
        raise ValidationError(f"Priority must be one of: {', '.join(PRIORITIES)}.")

    def _work(conn):
        authz.assert_rep(actor_id, community_id, conn, "create official events")
        course_id = _resolve_course(community_id, data.get("course_id"), conn)
        now = clock.now_iso()
        event_id = insert_returning_id(
            """INSERT INTO academic_events
               (community_id, course_id, event_type, title, description, event_date,
                event_time, venue, priority, status, original_message, created_by,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'SCHEDULED', ?, ?, ?, ?)""",
            (community_id, course_id, event_type, title, description, event_date,
             event_time, venue, priority, data.get("original_message"), actor_id,
             now, now), conn=conn)
        event = query_one("SELECT * FROM academic_events WHERE id = ?", (event_id,), conn=conn)

        record_change(community_id, "academic_event", event_id, "EVENT_CREATED", None,
                      _snapshot(event), actor_id=actor_id,
                      source_message=data.get("original_message"), conn=conn)
        reminder_service.schedule_for_event(event, conn=conn)
        if notify:
            notification_service.enqueue(
                notification_service.recipients_for(community_id, course_id, conn=conn),
                community_id, f"New {event_type.lower()}: {title}",
                _event_email(event, "created", conn=conn),
                dedupe_key=f"event:{event_id}:created", conn=conn,
                **notification_copy.event_created(
                    event, _course_code(course_id, conn=conn)))
        return event

    if conn is not None:
        return _work(conn)
    with transaction() as new_conn:
        return _work(new_conn)


def update_event(actor_id, community_id, event_id, changes, expected_version=None,
                 source_message=None, notify=True, conn=None):
    """Apply a change to an event under optimistic concurrency control (spec 17)."""

    def _work(conn):
        authz.assert_rep(actor_id, community_id, conn, "change official events")
        current = get_event(event_id, community_id, conn=conn)
        if expected_version is not None and int(expected_version) != current["version"]:
            raise ConflictError(
                "This event changed since the proposal was generated. Re-analyse the message.",
                details={"expected_version": int(expected_version),
                         "current_version": current["version"]})
        if current["status"] == "CANCELLED":
            raise ConflictError("This event has been cancelled.")

        updates, old_values, new_values = {}, {}, {}
        for field in MUTABLE_FIELDS:
            if field not in changes:
                continue
            value = changes[field]
            if field == "event_date":
                value = validate_date(value)
            elif field == "event_time":
                value = validate_time(value)
            elif field == "course_id":
                value = _resolve_course(community_id, value, conn)
            elif field == "priority" and value is not None:
                value = str(value).upper()
                if value not in PRIORITIES:
                    raise ValidationError("Invalid priority.")
            elif field == "title":
                value = (value or "").strip()
                if not value:
                    raise ValidationError("An event title cannot be empty.")
            elif field == "description":
                # Clearing instructions is a legitimate edit, so a blank
                # becomes NULL rather than a validation error.
                value = validate_description(value)
            if value != current[field]:
                updates[field] = value
                old_values[field] = current[field]
                new_values[field] = value

        if not updates:
            return current, {}

        assignments = ", ".join(f"{f} = ?" for f in updates)
        execute(
            f"""UPDATE academic_events SET {assignments}, version = version + 1, updated_at = ?
                WHERE id = ? AND version = ?""",
            tuple(updates.values()) + (clock.now_iso(), event_id, current["version"]), conn=conn)
        updated = query_one("SELECT * FROM academic_events WHERE id = ?", (event_id,), conn=conn)

        change_type = _classify_change(updates)
        record_change(community_id, "academic_event", event_id, change_type,
                      old_values, new_values, actor_id=actor_id,
                      source_message=source_message, conn=conn)

        # A moved deadline cancels the old reminder and schedules a replacement.
        if "event_date" in updates:
            reminder_service.reschedule_for_event(updated, conn=conn)

        if notify:
            notification_service.enqueue(
                notification_service.recipients_for(community_id, updated["course_id"], conn=conn),
                community_id, _change_subject(change_type, updated),
                _change_email(updated, old_values, new_values, conn=conn),
                dedupe_key=f"event:{event_id}:v{updated['version']}", conn=conn,
                **notification_copy.event_changed(
                    updated, change_type, old_values, new_values,
                    _course_code(updated["course_id"], conn=conn)))
        return updated, new_values

    if conn is not None:
        return _work(conn)
    with transaction() as new_conn:
        return _work(new_conn)


def cancel_event(actor_id, community_id, event_id, expected_version=None,
                 source_message=None, notify=True, conn=None):
    def _work(conn):
        authz.assert_rep(actor_id, community_id, conn, "change official events")
        current = get_event(event_id, community_id, conn=conn)
        if expected_version is not None and int(expected_version) != current["version"]:
            raise ConflictError(
                "This event changed since the proposal was generated. Re-analyse the message.",
                details={"expected_version": int(expected_version),
                         "current_version": current["version"]})
        if current["status"] == "CANCELLED":
            raise ConflictError("This event is already cancelled.")

        execute(
            """UPDATE academic_events SET status = 'CANCELLED', version = version + 1,
               updated_at = ? WHERE id = ? AND version = ?""",
            (clock.now_iso(), event_id, current["version"]), conn=conn)
        updated = query_one("SELECT * FROM academic_events WHERE id = ?", (event_id,), conn=conn)

        # History is preserved: cancelling never deletes the record (spec 16).
        record_change(community_id, "academic_event", event_id, "EVENT_CANCELLED",
                      {"status": "SCHEDULED"}, {"status": "CANCELLED"},
                      actor_id=actor_id, source_message=source_message, conn=conn)
        # The official reminder and every personal reminder linked to this
        # event - what the rep's cancel dialog promises. Unlinked ones stay.
        reminder_service.cancel_all_for_event(event_id, conn=conn)
        if notify:
            notification_service.enqueue(
                notification_service.recipients_for(community_id, updated["course_id"], conn=conn),
                community_id, f"Cancelled: {updated['title']}",
                f"{updated['title']} has been cancelled.",
                dedupe_key=f"event:{event_id}:cancelled", conn=conn,
                **notification_copy.event_cancelled(
                    updated, _course_code(updated["course_id"], conn=conn)))
        return updated

    if conn is not None:
        return _work(conn)
    with transaction() as new_conn:
        return _work(new_conn)


def _classify_change(updates):
    if "event_date" in updates:
        return "DEADLINE_CHANGED"
    if "venue" in updates:
        return "VENUE_CHANGED"
    if "event_time" in updates:
        return "TIME_CHANGED"
    return "EVENT_UPDATED"


def _change_subject(change_type, event):
    labels = {
        "DEADLINE_CHANGED": "Deadline changed",
        "VENUE_CHANGED": "Venue changed",
        "TIME_CHANGED": "Time changed",
        "EVENT_UPDATED": "Update",
    }
    return f"{labels.get(change_type, 'Update')}: {event['title']}"


def _course_code(course_id, conn=None):
    if course_id is None:
        return None
    row = query_one("SELECT code FROM courses WHERE id = ?", (course_id,), conn=conn)
    return row["code"] if row else None


def _snapshot(event):
    return {
        "title": event["title"], "event_type": event["event_type"],
        "event_date": event["event_date"], "event_time": event["event_time"],
        "venue": event["venue"], "priority": event["priority"], "status": event["status"],
    }


def _event_email(event, action, conn=None):
    """Emails carry enough detail to be understood without opening the app (spec 19)."""
    code = _course_code(event["course_id"], conn=conn)
    lines = [f"{event['title']} ({event['event_type'].title()})"]
    if code:
        lines.append(f"Course: {code}")
    lines.append(f"Date: {event['event_date'] or 'not specified'}")
    lines.append(f"Time: {event['event_time'] or 'not specified'}")
    lines.append(f"Venue: {event['venue'] or 'not specified'}")
    return "\n".join(lines)


def _change_email(event, old_values, new_values, conn=None):
    readable = {"event_date": "Date", "event_time": "Time", "venue": "Venue",
                "title": "Title", "priority": "Priority", "course_id": "Course"}
    lines = [f"{event['title']} has been updated.", ""]
    for field, new in new_values.items():
        old = old_values.get(field)
        lines.append(f"{readable.get(field, field)}: {old or 'not specified'} "
                     f"-> {new or 'not specified'}")
    lines.append("")
    lines.append(_event_email(event, "updated", conn=conn))
    return "\n".join(lines)


def event_payload(row, completed=False, attachments=None):
    """`attachments` is supplied by the caller so a list endpoint can fetch
    them for a whole page in one query. An empty list is the normal case and
    means exactly what it says: no original material was attached."""
    return {
        "id": row["id"],
        "course_id": row["course_id"],
        "course_code": row["course_code"] if "course_code" in row.keys() else None,
        "event_type": row["event_type"],
        "title": row["title"],
        "event_date": row["event_date"],
        "event_time": row["event_time"],
        "venue": row["venue"],
        # Optional everywhere: an event created from a one-line message has no
        # instructions and no material, and that is a complete record.
        "description": row["description"] if "description" in row.keys() else None,
        "priority": row["priority"],
        "status": row["status"],
        "version": row["version"],
        "original_message": row["original_message"],
        "created_at": row["created_at"],
        "completed": completed,
        "attachments": attachments or [],
    }


def mark_complete(user_id, community_id, event_id, complete=True):
    """Personal state only. Never mutates the official event (spec 28)."""
    with transaction() as conn:
        get_event(event_id, community_id, conn=conn)
        if complete:
            existing = query_one(
                "SELECT id FROM personal_event_completions WHERE user_id = ? AND event_id = ?",
                (user_id, event_id), conn=conn)
            if existing is None:
                execute(
                    """INSERT INTO personal_event_completions (user_id, event_id, completed_at)
                       VALUES (?, ?, ?)""",
                    (user_id, event_id, clock.now_iso()), conn=conn)
        else:
            execute("DELETE FROM personal_event_completions WHERE user_id = ? AND event_id = ?",
                    (user_id, event_id), conn=conn)
        return True


def completed_event_ids(user_id, conn=None):
    rows = query_all("SELECT event_id FROM personal_event_completions WHERE user_id = ?",
                     (user_id,), conn=conn)
    return {r["event_id"] for r in rows}
