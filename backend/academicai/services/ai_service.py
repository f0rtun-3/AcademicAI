"""AI orchestration (spec 15, 16).

The backend decides what the AI is allowed to see. It selects the records for
exactly one community - the caller's own - and hands them to the provider along
with the sanitised message. The provider returns a proposal, which is
normalised and then annotated with the CURRENT version of any record it points
at, so the publishing step can detect a stale proposal (spec 17).

Nothing in this module writes academic data.
"""
from flask import current_app

from .. import clock
from ..ai import provider as ai_provider
from ..ai.prompts import sanitize_untrusted
from ..ai.schemas import normalize
from ..db.connection import query_one
from ..errors import ValidationError
from . import community_service, course_service, event_service, timetable_service

MAX_CONTEXT_EVENTS = 100


def _community_context(community_id, selected_course_id=None):
    """Everything the AI may see, scoped to one community (spec 25)."""
    courses = course_service.list_courses(community_id)
    timetable = timetable_service.list_entries(community_id)
    events = event_service.list_events(community_id, include_cancelled=False)

    course_payloads = [{"id": c["id"], "code": c["code"], "title": c["title"]} for c in courses]
    timetable_payloads = [
        {"id": t["id"], "course_id": t["course_id"], "title": t["title"],
         "day_of_week": t["day_of_week"], "start_time": t["start_time"],
         "venue": t["venue"], "version": t["version"]}
        for t in timetable
    ]
    event_payloads = [
        {"id": e["id"], "course_id": e["course_id"], "event_type": e["event_type"],
         "title": e["title"], "event_date": e["event_date"], "event_time": e["event_time"],
         "venue": e["venue"], "status": e["status"], "version": e["version"]}
        for e in events
    ]
    if selected_course_id is not None:
        event_payloads.sort(key=lambda e: e["course_id"] != selected_course_id)
    return course_payloads, timetable_payloads, event_payloads[:MAX_CONTEXT_EVENTS]


def _explicit_fields(payload):
    """Rep-entered values. An explicit "not specified" is a real answer, not a
    missing one, and must stay null (spec 14)."""
    return {
        "event_date": payload.get("event_date") or None,
        "event_time": payload.get("event_time") or None,
        "venue": payload.get("venue") or None,
        "no_date": bool(payload.get("no_date")),
        "no_time": bool(payload.get("no_time")),
        "no_venue": bool(payload.get("no_venue")),
    }


def analyze_message(user, community_id, payload):
    max_length = current_app.config["MAX_MESSAGE_LENGTH"]
    raw_message = payload.get("message")
    if not isinstance(raw_message, str) or not raw_message.strip():
        raise ValidationError("A message is required.")
    if len(raw_message) > max_length:
        raise ValidationError(f"Message must be {max_length} characters or fewer.")

    message = sanitize_untrusted(raw_message, max_length)
    community = community_service.get_community(community_id)

    selected_course = None
    if payload.get("course_id") is not None:
        course = course_service.get_course(payload["course_id"], community_id)
        selected_course = {"id": course["id"], "code": course["code"], "title": course["title"]}

    courses, timetable, events = _community_context(
        community_id, selected_course["id"] if selected_course else None)

    now = clock.now()
    request = {
        "message": message,
        "context": payload.get("context"),
        "information_type": payload.get("information_type"),
        "selected_course": selected_course,
        "today": now.date().isoformat(),
        "now": clock.to_iso(now),
        "max_length": max_length,
        "community": {
            "department": community["department"],
            "level": community["level"],
            "academic_session": community["academic_session"],
        },
        "courses": courses,
        "timetable": timetable,
        "events": events,
        "explicit": _explicit_fields(payload),
    }

    raw = ai_provider.get_provider().interpret(request)
    proposal = normalize(raw)
    return _annotate(proposal, community_id, message)


def _annotate(proposal, community_id, message):
    """Attach the matched record and its CURRENT version.

    A proposal is only ever publishable against the version recorded here; if
    the record moves on before publishing, the publish is rejected (spec 17).
    """
    proposal["community_id"] = community_id
    proposal["original_message"] = message
    proposal["matched_record"] = None
    proposal["expected_version"] = None

    match_id = proposal.get("possible_match_id")
    if match_id is None:
        return proposal

    table = "timetable_entries" if proposal["scope"] == "TIMETABLE" else "academic_events"
    row = query_one(
        f"SELECT * FROM {table} WHERE id = ? AND community_id = ?", (match_id, community_id))
    if row is None:
        # A provider may not point at a record outside the caller's community.
        proposal["possible_match_id"] = None
        proposal["action"] = "CLARIFICATION"
        proposal["needs_clarification"] = True
        proposal["clarification_question"] = "Which existing record does this refer to?"
        proposal["explanation"] = "The proposed match is not a record in this community."
        return proposal

    proposal["expected_version"] = row["version"]
    if proposal["scope"] == "TIMETABLE":
        proposal["matched_record"] = timetable_service.entry_payload(
            timetable_service.get_entry(match_id, community_id))
    else:
        proposal["matched_record"] = event_service.event_payload(
            event_service.get_event(match_id, community_id))
    return proposal


def interpret_for_student(user, community_id, payload):
    """Personal interpretation for a student.

    Identical analysis, but the result is explicitly marked as personal: a
    student's paste can never become official academic information (spec 13).
    """
    proposal = analyze_message(user, community_id, payload)
    proposal["personal_only"] = True
    proposal["publishable"] = False
    proposal["note"] = ("This is a personal interpretation. Only a verified course rep "
                        "can publish official academic information.")
    return proposal
