"""AI analysis and publishing endpoints (spec 27).

analyze-message only ever returns a proposal. Nothing is written here.
publish is the single path through which a proposal becomes official data, and
it re-authorises from scratch.
"""
from flask import Blueprint, g

from ..security import authz, rate_limit
from ..services import ai_service, publishing_service
from .helpers import body, ok

bp = Blueprint("ai", __name__, url_prefix="/api/ai")


@bp.post("/analyze-message")
@authz.require_member
def analyze_message():
    rate_limit.limit("ai_analyze", max_hits=30, per_seconds=3600,
                     key=str(g.current_user["id"]))
    payload = body()
    if g.membership["role"] == "VERIFIED_REP":
        proposal = ai_service.analyze_message(g.current_user, g.community_id, payload)
        proposal["publishable"] = proposal["action"] in publishing_service.PUBLISHABLE_ACTIONS
    else:
        # A student's paste is interpreted for their own use only (spec 13).
        proposal = ai_service.interpret_for_student(g.current_user, g.community_id, payload)
    return ok({"proposal": proposal})


@bp.post("/publish")
@authz.require_rep
def publish():
    rate_limit.limit("ai_publish", max_hits=60, per_seconds=3600,
                     key=str(g.current_user["id"]))
    result = publishing_service.publish(g.current_user["id"], g.community_id, body())
    return ok({"published": result}, 201)
