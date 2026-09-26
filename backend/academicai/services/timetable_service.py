"""Official timetable (spec 13, 15, 17).

Timetable entries are recurring weekly classes. They carry a version like any
other mutable entity, and a day/venue/time change is recorded in history and
notified, never silently overwritten.
"""
from .. import clock
from ..db.connection import execute, insert_returning_id, query_all, query_one, transaction
from ..errors import ConflictError, NotFoundError, ValidationError
from ..security import authz
from . import course_service, notification_copy, notification_service
from .change_history import record_change

DAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
MUTABLE_FIELDS = ("day_of_week", "start_time", "end_time", "venue", "title", "course_id")


def validate_day(value):
    day = (value or "").strip().upper()
    if day not in DAYS:
        raise ValidationError(f"Day must be one of: {', '.join(DAYS)}.")
    return day


def list_entries(community_id, conn=None):
    return query_all(
        """SELECT t.*, c.code AS course_code
           FROM timetable_entries t LEFT JOIN courses c ON c.id = t.course_id
           WHERE t.community_id = ? AND t.status = 'ACTIVE'
           ORDER BY CASE t.day_of_week
                      WHEN 'MONDAY' THEN 1 WHEN 'TUESDAY' THEN 2 WHEN 'WEDNESDAY' THEN 3
                      WHEN 'THURSDAY' THEN 4 WHEN 'FRIDAY' THEN 5 WHEN 'SATURDAY' THEN 6
                      ELSE 7 END, t.start_time""",
        (community_id,), conn=conn,
    )


def get_entry(entry_id, community_id, conn=None):
    row = query_one(
        """SELECT t.*, c.code AS course_code
           FROM timetable_entries t LEFT JOIN courses c ON c.id = t.course_id
           WHERE t.id = ? AND t.community_id = ?""",
        (entry_id, community_id), conn=conn,
    )
    if row is None:
        raise NotFoundError("Timetable entry not found.")
    return row


def find_for_course(community_id, course_id, conn=None):
    return query_all(
        """SELECT * FROM timetable_entries
           WHERE community_id = ? AND course_id = ? AND status = 'ACTIVE'""",
        (community_id, course_id), conn=conn,
    )


def create_entry(actor_id, community_id, data, notify=False, conn=None):
    from .event_service import validate_time
    day = validate_day(data.get("day_of_week"))
    start_time = validate_time(data.get("start_time"))
    end_time = validate_time(data.get("end_time"))

    def _work(conn):
        authz.assert_rep(actor_id, community_id, conn, "manage the timetable")
        course_id = data.get("course_id")
        if course_id is not None:
            course_service.get_course(course_id, community_id, conn=conn)
        now = clock.now_iso()
        entry_id = insert_returning_id(
            """INSERT INTO timetable_entries
               (community_id, course_id, title, day_of_week, start_time, end_time, venue,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (community_id, course_id, (data.get("title") or None), day, start_time, end_time,
             data.get("venue") or None, now, now), conn=conn)
        entry = query_one("SELECT * FROM timetable_entries WHERE id = ?", (entry_id,), conn=conn)
        record_change(community_id, "timetable_entry", entry_id, "TIMETABLE_CREATED", None,
                      _snapshot(entry), actor_id=actor_id,
                      source_message=data.get("original_message"), conn=conn)
        if notify:
            notification_service.notify_community(
                community_id, "Timetable updated",
                f"A class has been added to the timetable: {_describe(entry)}",
                dedupe_key=f"timetable:{entry_id}:created", conn=conn,
                **notification_copy.timetable_added(entry))
        return entry

    if conn is not None:
        return _work(conn)
    with transaction() as new_conn:
        return _work(new_conn)


def update_entry(actor_id, community_id, entry_id, changes, expected_version=None,
                 source_message=None, notify=True, conn=None):
    from .event_service import validate_time

    def _work(conn):
        authz.assert_rep(actor_id, community_id, conn, "manage the timetable")
        current = get_entry(entry_id, community_id, conn=conn)
        if current["status"] != "ACTIVE":
            raise ConflictError("This timetable entry has been cancelled and cannot be edited.",
                                details={"status": current["status"]})
        if expected_version is not None and int(expected_version) != current["version"]:
            raise ConflictError(
                "This timetable entry changed since the proposal was generated.",
                details={"expected_version": int(expected_version),
                         "current_version": current["version"]})

        updates, old_values, new_values = {}, {}, {}
        for field in MUTABLE_FIELDS:
            if field not in changes:
                continue
            value = changes[field]
            if field == "day_of_week":
                value = validate_day(value)
            elif field in ("start_time", "end_time"):
                value = validate_time(value)
            elif field == "course_id" and value is not None:
                course_service.get_course(value, community_id, conn=conn)
            if value != current[field]:
                updates[field] = value
                old_values[field] = current[field]
                new_values[field] = value

        if not updates:
            return current, {}

        assignments = ", ".join(f"{f} = ?" for f in updates)
        execute(
            f"""UPDATE timetable_entries SET {assignments}, version = version + 1, updated_at = ?
                WHERE id = ? AND version = ?""",
            tuple(updates.values()) + (clock.now_iso(), entry_id, current["version"]), conn=conn)
        updated = query_one("SELECT * FROM timetable_entries WHERE id = ?", (entry_id,), conn=conn)

        change_type = "TIMETABLE_DAY_CHANGED" if "day_of_week" in updates else "TIMETABLE_UPDATED"
        record_change(community_id, "timetable_entry", entry_id, change_type,
                      old_values, new_values, actor_id=actor_id,
                      source_message=source_message, conn=conn)
        if notify:
            notification_service.enqueue(
                notification_service.recipients_for(community_id, updated["course_id"], conn=conn),
                community_id, "Timetable changed",
                _change_email(updated, old_values, new_values),
                dedupe_key=f"timetable:{entry_id}:v{updated['version']}", conn=conn,
                **notification_copy.timetable_changed(updated))
        return updated, new_values

    if conn is not None:
        return _work(conn)
    with transaction() as new_conn:
        return _work(new_conn)


def cancel_entry(actor_id, community_id, entry_id, notify=True):
    with transaction() as conn:
        authz.assert_rep(actor_id, community_id, conn, "manage the timetable")
        current = get_entry(entry_id, community_id, conn=conn)
        if current["status"] != "ACTIVE":
            # Cancelling twice would bump the version again and record a second
            # ACTIVE -> CANCELLED transition that never happened.
            raise ConflictError("This timetable entry is already cancelled.",
                                details={"status": current["status"]})
        execute("""UPDATE timetable_entries SET status = 'CANCELLED', version = version + 1,
                   updated_at = ? WHERE id = ?""",
                (clock.now_iso(), entry_id), conn=conn)
        record_change(community_id, "timetable_entry", entry_id, "TIMETABLE_CANCELLED",
                      {"status": "ACTIVE"}, {"status": "CANCELLED"}, actor_id=actor_id, conn=conn)
        if notify:
            notification_service.notify_community(
                community_id, "Class removed from timetable",
                f"This class has been removed: {_describe(current)}",
                dedupe_key=f"timetable:{entry_id}:cancelled", conn=conn,
                **notification_copy.timetable_removed(current))
        return True


def _snapshot(entry):
    return {"day_of_week": entry["day_of_week"], "start_time": entry["start_time"],
            "end_time": entry["end_time"], "venue": entry["venue"], "title": entry["title"]}


def _describe(entry):
    parts = [entry["title"] or "Class", entry["day_of_week"].title()]
    if entry["start_time"]:
        parts.append(entry["start_time"])
    if entry["venue"]:
        parts.append(f"venue {entry['venue']}")
    return ", ".join(parts)


def _change_email(entry, old_values, new_values):
    readable = {"day_of_week": "Day", "start_time": "Start time", "end_time": "End time",
                "venue": "Venue", "title": "Title"}
    lines = [f"The timetable has changed for {entry['title'] or 'a class'}.", ""]
    for field, new in new_values.items():
        old = old_values.get(field)
        lines.append(f"{readable.get(field, field)}: {old or 'not specified'} "
                     f"-> {new or 'not specified'}")
    return "\n".join(lines)


def entry_payload(row):
    return {
        "id": row["id"],
        "course_id": row["course_id"],
        "course_code": row["course_code"] if "course_code" in row.keys() else None,
        "title": row["title"],
        "day_of_week": row["day_of_week"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "venue": row["venue"],
        "version": row["version"],
    }
