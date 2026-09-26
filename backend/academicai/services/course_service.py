"""Courses and enrollments (spec 24).

Enrollment exists so course-scoped notifications know exactly who is affected.
Membership of a community does NOT imply enrollment in every one of its courses.
"""
from .. import clock
from ..db.connection import execute, insert_returning_id, query_all, query_one, transaction
from ..errors import ConflictError, NotFoundError, ValidationError
from ..security import authz
from .change_history import record_change


def _clean_code(code):
    if not isinstance(code, str) or not code.strip():
        raise ValidationError("A course code is required.")
    return code.strip().upper().replace(" ", "")


def list_courses(community_id, conn=None):
    return query_all(
        """SELECT * FROM courses WHERE community_id = ? AND status = 'ACTIVE'
           ORDER BY code""",
        (community_id,), conn=conn,
    )


def get_course(course_id, community_id, conn=None, include_removed=False):
    """Always scoped by community, so a course id from another community is a 404.

    A REMOVED course is treated as absent by default. It has been withdrawn
    from the community's course list, its enrolments were dropped, and it must
    not be re-enrolled into or attached to new official records - otherwise a
    course nobody can see keeps driving notification targeting.

    `include_removed=True` is for the few callers that legitimately need the
    row itself (re-creating a course under the same code, reading history).
    """
    sql = "SELECT * FROM courses WHERE id = ? AND community_id = ?"
    if not include_removed:
        sql += " AND status = 'ACTIVE'"
    row = query_one(sql, (course_id, community_id), conn=conn)
    if row is None:
        raise NotFoundError("Course not found.")
    return row


def find_by_code(community_id, code, conn=None):
    return query_one(
        "SELECT * FROM courses WHERE community_id = ? AND code = ? AND status = 'ACTIVE'",
        (community_id, _clean_code(code)), conn=conn,
    )


def create_course(actor_id, community_id, data):
    code = _clean_code(data.get("code"))
    title = (data.get("title") or "").strip() or None
    with transaction() as conn:
        authz.assert_rep(actor_id, community_id, conn, "manage courses")
        existing = query_one("SELECT * FROM courses WHERE community_id = ? AND code = ?",
                             (community_id, code), conn=conn)
        if existing is not None:
            if existing["status"] == "ACTIVE":
                raise ConflictError("That course already exists in this community.")
            execute("""UPDATE courses SET status = 'ACTIVE', title = ?, version = version + 1,
                       updated_at = ? WHERE id = ?""",
                    (title, clock.now_iso(), existing["id"]), conn=conn)
            course_id = existing["id"]
        else:
            now = clock.now_iso()
            course_id = insert_returning_id(
                """INSERT INTO courses (community_id, code, title, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (community_id, code, title, now, now), conn=conn)
        record_change(community_id, "course", course_id, "COURSE_CREATED",
                      None, {"code": code, "title": title}, actor_id=actor_id, conn=conn)
        return query_one("SELECT * FROM courses WHERE id = ?", (course_id,), conn=conn)


def update_course(actor_id, community_id, course_id, data):
    with transaction() as conn:
        authz.assert_rep(actor_id, community_id, conn, "manage courses")
        course = get_course(course_id, community_id, conn=conn)
        title = (data.get("title") or "").strip() or course["title"]
        code = _clean_code(data["code"]) if data.get("code") else course["code"]
        # Compare-and-swap on the version that was read, for the same reason as
        # announcements above.
        cursor = execute(
            """UPDATE courses SET code = ?, title = ?, version = version + 1, updated_at = ?
               WHERE id = ? AND version = ?""",
            (code, title, clock.now_iso(), course_id, course["version"]), conn=conn)
        if cursor.rowcount == 0:
            raise ConflictError(
                "This course changed while it was being edited.",
                details={"current_version": course["version"]})
        record_change(community_id, "course", course_id, "COURSE_UPDATED",
                      {"code": course["code"], "title": course["title"]},
                      {"code": code, "title": title}, actor_id=actor_id, conn=conn)
        return query_one("SELECT * FROM courses WHERE id = ?", (course_id,), conn=conn)


def blocking_records(course_id, community_id, conn=None):
    """Official records that still depend on this course.

    Course-scoped notifications are targeted through active enrolments.
    Removing a course drops those enrolments, so anything still attached to it
    would keep existing while reaching nobody - a rep would see a successful
    deadline change that no student ever received. Rather than guess what the
    rep meant, removal is refused until these are dealt with.
    """
    events = query_all(
        """SELECT id, title, event_type, event_date FROM academic_events
           WHERE course_id = ? AND community_id = ? AND status = 'SCHEDULED'
           ORDER BY event_date IS NULL, event_date, id""",
        (course_id, community_id), conn=conn,
    )
    entries = query_all(
        """SELECT id, day_of_week, start_time FROM timetable_entries
           WHERE course_id = ? AND community_id = ? AND status = 'ACTIVE'
           ORDER BY id""",
        (course_id, community_id), conn=conn,
    )
    return (
        [{"id": r["id"], "title": r["title"], "event_type": r["event_type"],
          "event_date": r["event_date"]} for r in events],
        [{"id": r["id"], "day_of_week": r["day_of_week"],
          "start_time": r["start_time"]} for r in entries],
    )


def remove_course(actor_id, community_id, course_id):
    with transaction() as conn:
        authz.assert_rep(actor_id, community_id, conn, "manage courses")
        course = get_course(course_id, community_id, conn=conn)

        events, entries = blocking_records(course_id, community_id, conn=conn)
        if events or entries:
            parts = []
            if events:
                parts.append(f"{len(events)} scheduled "
                             f"event{'s' if len(events) != 1 else ''}")
            if entries:
                parts.append(f"{len(entries)} active timetable "
                             f"entr{'ies' if len(entries) != 1 else 'y'}")
            raise ConflictError(
                f"This course still has {' and '.join(parts)}. Cancel or reschedule "
                "them before removing the course.",
                details={"blocking_events": events,
                         "blocking_timetable_entries": entries},
            )
        execute("UPDATE courses SET status = 'REMOVED', updated_at = ? WHERE id = ?",
                (clock.now_iso(), course_id), conn=conn)
        execute("UPDATE course_enrollments SET status = 'DROPPED' WHERE course_id = ?",
                (course_id,), conn=conn)
        record_change(community_id, "course", course_id, "COURSE_REMOVED",
                      {"code": course["code"], "status": "ACTIVE"}, {"status": "REMOVED"},
                      actor_id=actor_id, conn=conn)
        return True


def enroll(user_id, community_id, course_id):
    with transaction() as conn:
        get_course(course_id, community_id, conn=conn)
        existing = query_one("SELECT * FROM course_enrollments WHERE course_id = ? AND user_id = ?",
                             (course_id, user_id), conn=conn)
        if existing is not None:
            if existing["status"] == "ACTIVE":
                raise ConflictError("You are already enrolled in that course.")
            execute("UPDATE course_enrollments SET status = 'ACTIVE' WHERE id = ?",
                    (existing["id"],), conn=conn)
            return query_one("SELECT * FROM course_enrollments WHERE id = ?",
                             (existing["id"],), conn=conn)
        enrollment_id = insert_returning_id(
            """INSERT INTO course_enrollments (course_id, user_id, status, created_at)
               VALUES (?, ?, 'ACTIVE', ?)""",
            (course_id, user_id, clock.now_iso()), conn=conn)
        return query_one("SELECT * FROM course_enrollments WHERE id = ?", (enrollment_id,), conn=conn)


def unenroll(user_id, community_id, course_id):
    with transaction() as conn:
        get_course(course_id, community_id, conn=conn)
        execute("""UPDATE course_enrollments SET status = 'DROPPED'
                   WHERE course_id = ? AND user_id = ?""",
                (course_id, user_id), conn=conn)
        return True


def enrollments_for(user_id, community_id, conn=None):
    return query_all(
        """SELECT c.* FROM course_enrollments ce JOIN courses c ON c.id = ce.course_id
           WHERE ce.user_id = ? AND ce.status = 'ACTIVE' AND c.community_id = ?
             AND c.status = 'ACTIVE'
           ORDER BY c.code""",
        (user_id, community_id), conn=conn,
    )


def course_payload(row, enrolled=None):
    payload = {"id": row["id"], "code": row["code"], "title": row["title"],
               "version": row["version"]}
    if enrolled is not None:
        payload["enrolled"] = enrolled
    return payload
