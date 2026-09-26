"""Dashboard aggregates (spec 28).

One request per screen, so the client does not need to orchestrate six calls
and can render loading/empty/error states from a single response.
"""
from datetime import timedelta

from flask import Blueprint, g

from .. import clock
from ..security import authz
from ..services import (announcement_service, community_service, course_service,
                        event_service, membership_service, reminder_service,
                        rep_service, timetable_service)
from ..services.change_history import change_payload
from .helpers import ok

bp = Blueprint("dashboard", __name__, url_prefix="/api")

UPCOMING_WINDOW_DAYS = 14


@bp.get("/dashboard")
@authz.require_member
def dashboard():
    user = g.current_user
    community = community_service.get_community(g.community_id)
    today = clock.now().date()
    horizon = today + timedelta(days=UPCOMING_WINDOW_DAYS)

    completed = event_service.completed_event_ids(user["id"])
    upcoming = []
    for row in event_service.list_events(g.community_id, include_cancelled=False):
        if not row["event_date"]:
            continue
        if today.isoformat() <= row["event_date"] <= horizon.isoformat():
            upcoming.append(event_service.event_payload(row, row["id"] in completed))

    payload = {
        "greeting": f"Welcome back, {user['full_name'].split(' ')[0]}",
        "user": {"id": user["id"], "full_name": user["full_name"]},
        "community": community_service.community_payload(
            community, viewer_id=user["id"]),
        "membership": membership_service.membership_payload(g.membership),
        "upcoming": upcoming,
        "recent_changes": [change_payload(c)
                           for c in community_service.recent_changes(g.community_id, limit=10)],
        "announcements": [announcement_service.announcement_payload(a)
                          for a in announcement_service.list_announcements(g.community_id, limit=5)],
        "reminders": [reminder_service.reminder_payload(r)
                      for r in reminder_service.list_personal(user["id"])],
    }

    if g.membership["role"] == "VERIFIED_REP":
        requests = membership_service.pending_requests(g.community_id)
        payload["rep"] = {
            "student_count": community_service.member_count(g.community_id),
            "rep_count": rep_service.rep_count(g.community_id),
            "pending_requests": [
                {"user_id": r["user_id"], "full_name": r["full_name"],
                 "requested_at": r["requested_at"]} for r in requests],
            "course_count": len(course_service.list_courses(g.community_id)),
            "timetable_count": len(timetable_service.list_entries(g.community_id)),
        }
    return ok(payload)


@bp.get("/calendar")
@authz.require_member
def calendar_view():
    """Everything that appears on the calendar screen (spec 28)."""
    completed = event_service.completed_event_ids(g.current_user["id"])
    events = event_service.list_events(g.community_id)
    timetable = timetable_service.list_entries(g.community_id)
    return ok({
        "events": [event_service.event_payload(e, e["id"] in completed) for e in events],
        "timetable": [timetable_service.entry_payload(t) for t in timetable],
    })
