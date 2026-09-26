"""Courses, timetable and announcements (spec 27, 28).

Reads are open to any active member of the community. Writes require rep
authority in that same community.
"""
from flask import Blueprint, g

from ..security import authz
from ..services import announcement_service, course_service, timetable_service
from .helpers import body, int_arg, ok

bp = Blueprint("academic", __name__, url_prefix="/api/community")


# --- Courses --------------------------------------------------------------

@bp.get("/courses")
@authz.require_member
def list_courses():
    enrolled = {c["id"] for c in
                course_service.enrollments_for(g.current_user["id"], g.community_id)}
    rows = course_service.list_courses(g.community_id)
    return ok({"courses": [course_service.course_payload(r, r["id"] in enrolled) for r in rows]})


@bp.post("/courses")
@authz.require_rep
def create_course():
    course = course_service.create_course(g.current_user["id"], g.community_id, body())
    return ok({"course": course_service.course_payload(course)}, 201)


@bp.put("/courses/<int:course_id>")
@authz.require_rep
def update_course(course_id):
    course = course_service.update_course(g.current_user["id"], g.community_id, course_id, body())
    return ok({"course": course_service.course_payload(course)})


@bp.delete("/courses/<int:course_id>")
@authz.require_rep
def remove_course(course_id):
    course_service.remove_course(g.current_user["id"], g.community_id, course_id)
    return ok({"status": "removed"})


@bp.post("/courses/<int:course_id>/enroll")
@authz.require_member
def enroll(course_id):
    course_service.enroll(g.current_user["id"], g.community_id, course_id)
    return ok({"status": "enrolled"}, 201)


@bp.delete("/courses/<int:course_id>/enroll")
@authz.require_member
def unenroll(course_id):
    course_service.unenroll(g.current_user["id"], g.community_id, course_id)
    return ok({"status": "unenrolled"})


# --- Timetable ------------------------------------------------------------

@bp.get("/timetable")
@authz.require_member
def list_timetable():
    rows = timetable_service.list_entries(g.community_id)
    return ok({"timetable": [timetable_service.entry_payload(r) for r in rows]})


@bp.post("/timetable")
@authz.require_rep
def create_timetable_entry():
    entry = timetable_service.create_entry(g.current_user["id"], g.community_id, body())
    return ok({"timetable_entry": timetable_service.entry_payload(
        timetable_service.get_entry(entry["id"], g.community_id))}, 201)


@bp.put("/timetable/<int:entry_id>")
@authz.require_rep
def update_timetable_entry(entry_id):
    data = body()
    entry, applied = timetable_service.update_entry(
        g.current_user["id"], g.community_id, entry_id, data,
        expected_version=data.get("expected_version"))
    return ok({"timetable_entry": timetable_service.entry_payload(
        timetable_service.get_entry(entry["id"], g.community_id)), "applied_changes": applied})


@bp.delete("/timetable/<int:entry_id>")
@authz.require_rep
def cancel_timetable_entry(entry_id):
    timetable_service.cancel_entry(g.current_user["id"], g.community_id, entry_id)
    return ok({"status": "cancelled"})


# --- Announcements --------------------------------------------------------

@bp.get("/announcements")
@authz.require_member
def list_announcements():
    limit = int_arg("limit", default=50, maximum=200)
    rows = announcement_service.list_announcements(g.community_id, limit=limit)
    return ok({"announcements": [announcement_service.announcement_payload(r) for r in rows]})


@bp.post("/announcements")
@authz.require_rep
def create_announcement():
    announcement = announcement_service.create_announcement(
        g.current_user["id"], g.community_id, body())
    return ok({"announcement": announcement_service.announcement_payload(announcement)}, 201)


@bp.put("/announcements/<int:announcement_id>")
@authz.require_rep
def update_announcement(announcement_id):
    data = body()
    announcement = announcement_service.update_announcement(
        g.current_user["id"], g.community_id, announcement_id, data,
        expected_version=data.get("expected_version"))
    return ok({"announcement": announcement_service.announcement_payload(announcement)})


@bp.delete("/announcements/<int:announcement_id>")
@authz.require_rep
def withdraw_announcement(announcement_id):
    announcement_service.withdraw_announcement(
        g.current_user["id"], g.community_id, announcement_id)
    return ok({"status": "withdrawn"})


# --- Academic calendar / session lifecycle (spec 23) ----------------------

@bp.get("/calendar")
@authz.require_member
def get_calendar():
    from ..services import calendar_service
    return ok({"calendar": calendar_service.calendar_payload(
        calendar_service.current(g.community_id))})


@bp.post("/calendar")
@authz.require_rep
def upload_calendar():
    from ..services import calendar_service
    calendar = calendar_service.upload(g.current_user["id"], g.community_id, body())
    return ok({"calendar": calendar_service.calendar_payload(calendar)}, 201)


@bp.post("/archive")
@authz.require_rep
def archive_session():
    """End the academic session. Nothing carries into the next one (spec 23)."""
    from ..services import calendar_service, community_service
    community = calendar_service.archive_session(g.current_user["id"], g.community_id)
    return ok({"community": community_service.community_payload(community)})
