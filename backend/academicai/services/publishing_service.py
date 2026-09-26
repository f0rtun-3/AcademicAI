"""Publishing an AI proposal (spec 2, 17).

The AI proposes; the backend authorises; the database is the source of truth.

Publishing revalidates, inside one transaction, in this order:
  1. the caller still holds rep authority in this exact community
  2. the community is one the caller is an active member of
  3. the current database state still matches the version the proposal was
     generated against - otherwise 409, requiring re-analysis
  4. the proposed values are valid in their own right

Only then does anything change, and the change, its history entry, its reminder
adjustment and its notifications all land in the same transaction.
"""
from ..db.connection import query_one, transaction
from ..errors import AuthorizationError, ConflictError, StaleProposalError, ValidationError
from ..security import authz
from . import announcement_service, course_service, event_service, timetable_service

PUBLISHABLE_ACTIONS = ("CREATE", "UPDATE", "CANCEL")


def publish(actor_id, community_id, payload):
    action = (payload.get("action") or "").strip().upper()
    scope = (payload.get("scope") or "EVENT").strip().upper()

    if action in ("CLARIFICATION", "DUPLICATE"):
        raise ValidationError(
            f"A {action} proposal cannot be published. Resolve it first.",
            details={"action": action})
    if action not in PUBLISHABLE_ACTIONS:
        raise ValidationError(f"Action must be one of: {', '.join(PUBLISHABLE_ACTIONS)}.")

    with transaction() as conn:
        # 1 & 2: every gate is re-checked live, never trusted from the proposal.
        # Account verification, community membership and rep authority are
        # checked separately and in that order (spec 6, 16). The account gate is
        # now the email one - ID-card verification is out of MVP scope - but it
        # is still checked here, inside this transaction, rather than inherited.
        actor = query_one("SELECT * FROM users WHERE id = ?", (actor_id,), conn=conn)
        if actor is None:
            raise AuthorizationError("Account not found.")
        authz.assert_email_verified(actor)

        membership = authz.membership_in(actor_id, community_id, conn=conn)
        if membership is None or membership["status"] != "ACTIVE":
            raise AuthorizationError("You are not an active member of this community.")
        if membership["role"] != "VERIFIED_REP":
            raise AuthorizationError("Only a verified course rep can publish official information.")

        if scope == "ANNOUNCEMENT":
            return _publish_announcement(actor_id, community_id, action, payload, conn)
        if scope == "TIMETABLE":
            return _publish_timetable(actor_id, community_id, action, payload, conn)
        return _publish_event(actor_id, community_id, action, payload, conn)


def _expected_version(payload):
    value = payload.get("expected_version")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError("expected_version must be an integer.")


def _require_target(payload):
    target = payload.get("target_id", payload.get("possible_match_id"))
    if target is None:
        raise ValidationError("A target record is required for this action.")
    try:
        return int(target)
    except (TypeError, ValueError):
        raise ValidationError("target_id must be an integer.")


def _resolve_course_id(payload, community_id, conn):
    if payload.get("course_id") is not None:
        course_service.get_course(payload["course_id"], community_id, conn=conn)
        return payload["course_id"]
    code = payload.get("course_code")
    if code:
        course = course_service.find_by_code(community_id, code, conn=conn)
        if course is None:
            raise ValidationError(
                f"Course {code} does not exist in this community. Add the course first.")
        return course["id"]
    return None


def _publish_event(actor_id, community_id, action, payload, conn):
    if action == "CREATE":
        data = {
            "title": payload.get("title"),
            "event_type": payload.get("event_type"),
            # Typed instructions, when the rep gave any. Optional: a one-line
            # WhatsApp message legitimately produces an event with none.
            "description": payload.get("description"),
            "event_date": payload.get("event_date"),
            "event_time": payload.get("event_time"),
            "venue": payload.get("venue"),
            "priority": payload.get("priority") or "NORMAL",
            "course_id": _resolve_course_id(payload, community_id, conn),
            "original_message": payload.get("original_message"),
        }
        event = event_service.create_event(actor_id, community_id, data, conn=conn)
        return {"action": "CREATE", "scope": "EVENT",
                "event": event_service.event_payload(
                    event_service.get_event(event["id"], community_id, conn=conn))}

    target_id = _require_target(payload)
    expected = _expected_version(payload)

    if action == "CANCEL":
        try:
            event = event_service.cancel_event(
                actor_id, community_id, target_id, expected_version=expected,
                source_message=payload.get("original_message"), conn=conn)
        except ConflictError as exc:
            raise _as_stale(exc)
        return {"action": "CANCEL", "scope": "EVENT",
                "event": event_service.event_payload(
                    event_service.get_event(event["id"], community_id, conn=conn))}

    changes = {}
    for field in ("title", "description", "event_date", "event_time", "venue", "priority"):
        if field in payload:
            changes[field] = payload[field]
    if payload.get("course_id") is not None or payload.get("course_code"):
        changes["course_id"] = _resolve_course_id(payload, community_id, conn)
    if not changes:
        raise ValidationError("No changes were supplied.")

    try:
        event, applied = event_service.update_event(
            actor_id, community_id, target_id, changes, expected_version=expected,
            source_message=payload.get("original_message"), conn=conn)
    except ConflictError as exc:
        raise _as_stale(exc)
    return {"action": "UPDATE", "scope": "EVENT", "applied_changes": applied,
            "event": event_service.event_payload(
                event_service.get_event(event["id"], community_id, conn=conn))}


def _publish_timetable(actor_id, community_id, action, payload, conn):
    if action == "CREATE":
        data = {
            "title": payload.get("title"),
            "day_of_week": payload.get("day_of_week"),
            "start_time": payload.get("start_time") or payload.get("event_time"),
            "end_time": payload.get("end_time"),
            "venue": payload.get("venue"),
            "course_id": _resolve_course_id(payload, community_id, conn),
            "original_message": payload.get("original_message"),
        }
        entry = timetable_service.create_entry(actor_id, community_id, data, notify=True, conn=conn)
        return {"action": "CREATE", "scope": "TIMETABLE",
                "timetable_entry": timetable_service.entry_payload(
                    timetable_service.get_entry(entry["id"], community_id, conn=conn))}

    target_id = _require_target(payload)
    expected = _expected_version(payload)

    if action == "CANCEL":
        timetable_service.cancel_entry(actor_id, community_id, target_id)
        return {"action": "CANCEL", "scope": "TIMETABLE", "timetable_entry_id": target_id}

    changes = {}
    for field in ("title", "day_of_week", "start_time", "end_time", "venue"):
        if field in payload:
            changes[field] = payload[field]
    if payload.get("course_id") is not None or payload.get("course_code"):
        changes["course_id"] = _resolve_course_id(payload, community_id, conn)
    if not changes:
        raise ValidationError("No changes were supplied.")

    try:
        entry, applied = timetable_service.update_entry(
            actor_id, community_id, target_id, changes, expected_version=expected,
            source_message=payload.get("original_message"), conn=conn)
    except ConflictError as exc:
        raise _as_stale(exc)
    return {"action": "UPDATE", "scope": "TIMETABLE", "applied_changes": applied,
            "timetable_entry": timetable_service.entry_payload(
                timetable_service.get_entry(entry["id"], community_id, conn=conn))}


def _publish_announcement(actor_id, community_id, action, payload, conn):
    if action != "CREATE":
        raise ValidationError("Announcements support only CREATE through publishing.")
    announcement = announcement_service.create_announcement(
        actor_id, community_id,
        {"title": payload.get("title") or "Announcement",
         "body": payload.get("body") or payload.get("original_message") or "",
         "original_message": payload.get("original_message")},
        conn=conn)
    return {"action": "CREATE", "scope": "ANNOUNCEMENT",
            "announcement": announcement_service.announcement_payload(announcement)}


def _as_stale(exc):
    """Re-label a version conflict so clients can distinguish it from other 409s."""
    if exc.details.get("current_version") is not None:
        return StaleProposalError(exc.message, details=exc.details)
    return exc
