"""Reminders (spec 20).

Official reminders are derived from academic events: one per event, at
REMINDER_HOUR on the ACADEMIC day REMINDER_LEAD_DAYS before the event's date,
read on the university's own clock (academic_time.py). With the defaults that
is 08:00 the day before in the university's timezone - 07:00Z for a Lagos
university, whatever timezone the server runs in. An event published after that
moment has already missed it and gets no official reminder: a substitute time
would be a rule nobody wrote.

Personal reminders are separate from official academic records and belong to
one student. A request states its time in exactly one of two ways:

  remind_at_local  a wall-clock time on the university's clock, "2026-09-27T08:00"
                   (preferred - the frontend and the AI both send this);
  remind_at        an absolute instant WITH its offset, kept for compatibility.

Both become one UTC instant before storage. The worker compares stored UTC
instants only and knows nothing about universities or zones.
"""
from datetime import datetime, timedelta

from flask import current_app

from .. import academic_time, clock
from ..db.connection import execute, insert_returning_id, query_all, query_one, transaction
from ..errors import NotFoundError, ValidationError
from . import notification_copy, notification_service


def default_reminder_local(event_date, lead_days=None, hour=None):
    """The official reminder's wall-clock time for an event date: REMINDER_HOUR
    on the academic day REMINDER_LEAD_DAYS before it.

    Returns None when the event has no date - an explicitly unspecified date is
    not an error, it simply cannot carry a deadline reminder (spec 14).
    `lead_days` and `hour` default to the app's configuration; pass them when
    there is no app context (start-up migration).
    """
    if not event_date:
        return None
    lead_days = current_app.config["REMINDER_LEAD_DAYS"] if lead_days is None else lead_days
    hour = current_app.config["REMINDER_HOUR"] if hour is None else hour
    try:
        day = datetime.strptime(event_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    return (day - timedelta(days=lead_days)).replace(hour=hour)


def compute_remind_at(event_date, tz, lead_days=None, hour=None):
    """The official reminder INSTANT (UTC) for an event date in zone `tz`."""
    local = default_reminder_local(event_date, lead_days, hour)
    return None if local is None else academic_time.local_to_instant(local, tz)


def cancel_for_event(event_id, conn=None):
    """Cancel an event's outstanding OFFICIAL reminder. Used when a deadline
    moves (and a replacement is scheduled) and when the event is cancelled."""
    cur = execute(
        """UPDATE event_reminders SET status = 'CANCELLED'
           WHERE event_id = ? AND status = 'PENDING'""",
        (event_id,), conn=conn,
    )
    return cur.rowcount


def cancel_all_for_event(event_id, conn=None):
    """Everything still waiting to remind anyone about a cancelled event: its
    official reminder AND every pending personal reminder a student linked to
    it. Unlinked personal reminders are untouched, and reminders that already
    fired or were already cancelled are never rewritten (status = 'PENDING').
    This is what the rep's cancel dialog promises."""
    official = cancel_for_event(event_id, conn=conn)
    personal = execute(
        """UPDATE personal_reminders SET status = 'CANCELLED'
           WHERE event_id = ? AND status = 'PENDING'""",
        (event_id,), conn=conn,
    ).rowcount
    return {"official": official, "personal": personal}


def schedule_for_event(event, conn=None):
    """Schedule the official reminder for an event, if its moment is still ahead.

    An event published (or moved) after its reminder moment has passed gets no
    official reminder at all - not a late one, and not one at an invented time.
    """
    if event["status"] != "SCHEDULED":
        return None
    tz = academic_time.zone_for_community(event["community_id"], conn=conn)
    remind_at = compute_remind_at(event["event_date"], tz)
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


def recalculate_pending_official(conn, lead_days, hour):
    """Start-up migration: put PENDING official reminders on their university's
    clock (they were once computed as 08:00 UTC).

    Only PENDING reminders of SCHEDULED events are touched, and only when the
    stored instant differs from what the rule gives now, so it is idempotent
    and a normal start writes nothing. SENT and CANCELLED rows are history and
    are never rewritten; personal reminders are not official and are never
    touched, because what zone their author meant cannot be known.

    Runs without an app context, so the policy is passed in. Returns the number
    of reminders moved.
    """
    def _pending_changes():
        rows = conn.execute(
            """SELECT r.id, r.remind_at, e.event_date, u.timezone
               FROM event_reminders r
               JOIN academic_events e ON e.id = r.event_id
               JOIN academic_communities c ON c.id = e.community_id
               JOIN universities u ON u.id = c.university_id
               WHERE r.status = 'PENDING' AND e.status = 'SCHEDULED'""").fetchall()
        changes = []
        for row in rows:
            instant = compute_remind_at(row["event_date"], academic_time.zone(row["timezone"]),
                                        lead_days, hour)
            if instant is not None and clock.to_iso(instant) != row["remind_at"]:
                changes.append((clock.to_iso(instant), row["id"], row["remind_at"]))
        return changes

    if not _pending_changes():
        return 0
    with transaction(conn):
        changes = _pending_changes()
        for new_value, reminder_id, old_value in changes:
            conn.execute(
                """UPDATE event_reminders SET remind_at = ?
                   WHERE id = ? AND status = 'PENDING' AND remind_at = ?""",
                (new_value, reminder_id, old_value))
    return len(changes)


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
    """An absolute `remind_at` instant, which must STATE ITS OFFSET.

    "2026-09-27T08:00" does not say which 08:00, so it is refused rather than
    guessed: reading it as UTC is exactly how a Lagos reminder once fired an
    hour late. A time on the university's clock is sent as remind_at_local.
    """
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValidationError("remind_at must be an ISO-8601 timestamp.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(
            "remind_at must include a timezone offset, for example "
            "2026-09-27T08:00:00+01:00. To give a time on your university's "
            "clock, send it as remind_at_local instead.")
    return parsed


def _requested_instant(data, zone_name):
    """The one UTC instant a create/update request means, or None if it names
    no time. Exactly one of remind_at_local / remind_at may be sent: accepting
    both would leave it unclear which one wins."""
    local = data.get("remind_at_local")
    absolute = data.get("remind_at")
    has_local = local not in (None, "")
    has_absolute = absolute not in (None, "")
    if has_local and has_absolute:
        raise ValidationError(
            "Send either remind_at_local (a time on your university's clock) or "
            "remind_at (an instant with a timezone offset), not both.")
    claimed = data.get("timezone")
    if claimed not in (None, "") and claimed != zone_name:
        # `timezone` is what the API reports, not a choice: posting a payload
        # back unchanged is fine, asking for another zone is refused.
        raise ValidationError(
            f"Reminder times are read on your university's clock ({zone_name}); "
            "a different timezone cannot be chosen for one reminder.")
    if has_local:
        if not zone_name:
            raise ValidationError(
                "remind_at_local needs a university clock, and this account has "
                "no university. Send remind_at with a timezone offset instead.")
        return academic_time.local_to_instant(
            academic_time.parse_local(local), academic_time.zone(zone_name))
    if has_absolute:
        return _parse_remind_at(absolute)
    return None


def _event_in_own_community(user_id, event_id, conn):
    event = query_one("SELECT * FROM academic_events WHERE id = ?", (event_id,), conn=conn)
    if event is None:
        raise NotFoundError("Event not found.")
    # A personal reminder may only reference an event in the student's own
    # community (spec 4).
    member = query_one(
        """SELECT 1 FROM community_members
           WHERE user_id = ? AND community_id = ? AND status = 'ACTIVE'""",
        (user_id, event["community_id"]), conn=conn,
    )
    if member is None:
        raise NotFoundError("Event not found.")
    return event


def _zone_name(user_id, event, conn):
    """The clock a reminder's time is read on: its event's university, or the
    student's own."""
    if event is not None:
        return academic_time.zone_name_for_community(event["community_id"], conn=conn)
    return academic_time.zone_name_for_user(user_id, conn=conn)


def create_personal(user_id, data):
    title = (data.get("title") or "").strip()
    if not title:
        raise ValidationError("A reminder title is required.")

    event_id = data.get("event_id")
    with transaction() as conn:
        event = _event_in_own_community(user_id, event_id, conn) if event_id is not None else None
        instant = _requested_instant(data, _zone_name(user_id, event, conn))
        if instant is None:
            raise ValidationError("remind_at_local is required.")
        reminder_id = insert_returning_id(
            """INSERT INTO personal_reminders (user_id, event_id, title, remind_at, status, created_at)
               VALUES (?, ?, ?, ?, 'PENDING', ?)""",
            (user_id, event_id, title, clock.to_iso(instant), clock.now_iso()), conn=conn,
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
        event = (query_one("SELECT * FROM academic_events WHERE id = ?", (row["event_id"],),
                           conn=conn) if row["event_id"] is not None else None)
        instant = _requested_instant(data, _zone_name(user_id, event, conn))
        remind_at = clock.to_iso(instant) if instant is not None else row["remind_at"]
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
        """SELECT p.*, cm.community_id, e.status AS event_status
           FROM personal_reminders p
           LEFT JOIN community_members cm
                  ON cm.user_id = p.user_id AND cm.status = 'ACTIVE'
           LEFT JOIN academic_events e ON e.id = p.event_id
           WHERE p.status = 'PENDING' AND p.remind_at <= ?""",
        (clock.now_iso(),), conn=conn,
    )
    fired = 0
    for row in due:
        if row["event_id"] is not None and row["event_status"] == "CANCELLED":
            # Linked to an event that was cancelled (before cancellation
            # cancelled linked reminders too): withdrawn, never sent.
            execute("UPDATE personal_reminders SET status = 'CANCELLED' "
                    "WHERE id = ? AND status = 'PENDING'", (row["id"],), conn=conn)
            continue
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


def reminder_payload(row, zone_name=None):
    """A personal reminder for the API. `remind_at` is the stored UTC instant;
    `remind_at_local` is the same moment on the student's university clock,
    which is what the interface shows and edits, so no client ever has to
    convert zones itself."""
    local = None
    if zone_name:
        try:
            local = academic_time.local_string(row["remind_at"], academic_time.zone(zone_name))
        except ValueError:
            local = None  # a malformed legacy value: shown without a local time
    return {
        "id": row["id"],
        "title": row["title"],
        "remind_at": row["remind_at"],
        "remind_at_local": local,
        "timezone": zone_name,
        "status": row["status"],
        "event_id": row["event_id"],
    }


def payloads_for_user(user_id, rows, conn=None):
    """Reminder payloads on the student's own academic clock."""
    zone_name = academic_time.zone_name_for_user(user_id, conn=conn)
    return [reminder_payload(r, zone_name) for r in rows]
