"""Community, membership and transfer endpoints (spec 27)."""
from flask import Blueprint, g

from ..security import authz
from ..services import community_service, membership_service
from ..services.change_history import change_payload
from .helpers import body, int_arg, ok

bp = Blueprint("community", __name__, url_prefix="/api/community")


@bp.post("/setup")
@authz.require_email_verified
def setup():
    """Community determination step of onboarding (spec 7).

    Returns whether the community already existed so the client can show either
    "Your academic community is ready." or the not-yet-set-up choice.
    """
    community, created = community_service.ensure_community_for_user(g.current_user["id"])
    return ok({
        "community": community_service.community_payload(community),
        "created": created,
        "existed": not created,
        "message": ("Your academic community hasn't been set up yet."
                    if created else "Your academic community is ready."),
    }, 201 if created else 200)


@bp.post("/join")
@authz.require_email_verified
def join():
    data = body() if _has_body() else {}
    community_id = data.get("community_id")
    if community_id is None:
        community, _ = community_service.ensure_community_for_user(g.current_user["id"])
        community_id = community["id"]
    membership = membership_service.join_or_request(g.current_user["id"], community_id)
    community = community_service.get_community(community_id)
    return ok({
        "membership": membership_service.membership_payload(membership),
        "community": community_service.community_payload(
            community, viewer_id=g.current_user["id"]),
        "awaiting_approval": membership["status"] == "PENDING_APPROVAL",
    }, 201)


@bp.post("/transfer")
@authz.require_email_verified
def transfer():
    """Request a transfer. The existing membership stays ACTIVE until the
    destination approves, so a rejection never strands the student (spec 10)."""
    membership, destination = membership_service.request_transfer(g.current_user["id"], body())
    return ok({
        "membership": membership_service.membership_payload(membership),
        "destination": community_service.community_payload(destination),
        "awaiting_approval": membership["status"] == "PENDING_APPROVAL",
    }, 201)


@bp.post("/leave")
@authz.require_auth
def leave():
    membership_service.leave_community(g.current_user["id"])
    return ok({"status": "left"})


@bp.get("")
@authz.require_member
def get_community():
    community = community_service.get_community(g.community_id)
    return ok({
        "community": community_service.community_payload(
            community, viewer_id=g.current_user["id"]),
        "membership": membership_service.membership_payload(g.membership),
    })


@bp.get("/members")
@authz.require_member
def members():
    rows = membership_service.members(g.community_id)
    return ok({"members": [
        {"user_id": r["user_id"], "full_name": r["full_name"], "role": r["role"],
         "status": r["status"]}
        for r in rows
    ]})


@bp.get("/changes")
@authz.require_member
def changes():
    limit = int_arg("limit", default=50, maximum=200)
    rows = community_service.recent_changes(g.community_id, limit=limit)
    return ok({"changes": [change_payload(r) for r in rows]})


@bp.get("/requests")
@authz.require_rep
def list_requests():
    rows = membership_service.pending_requests(g.community_id)
    return ok({"requests": [
        {"user_id": r["user_id"], "full_name": r["full_name"], "requested_at": r["requested_at"]}
        for r in rows
    ]})


@bp.post("/requests/<int:user_id>/approve")
@authz.require_rep
def approve_request(user_id):
    membership = membership_service.approve_request(g.current_user["id"], g.community_id, user_id)
    return ok({"membership": membership_service.membership_payload(membership)})


@bp.post("/requests/<int:user_id>/reject")
@authz.require_rep
def reject_request(user_id):
    reason = (body().get("reason") if _has_body() else None)
    membership = membership_service.reject_request(
        g.current_user["id"], g.community_id, user_id, reason=reason)
    return ok({"membership": membership_service.membership_payload(membership)})


def _has_body():
    from flask import request
    return request.get_json(silent=True) is not None
