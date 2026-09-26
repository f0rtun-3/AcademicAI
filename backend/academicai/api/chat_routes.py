"""AI Chat endpoints (spec 27)."""
from flask import Blueprint, g

from ..security import authz, rate_limit
from ..services import chat_service
from .helpers import body, int_arg, ok

bp = Blueprint("chat", __name__, url_prefix="/api/chat")


@bp.post("")
@authz.require_member
def ask():
    rate_limit.limit("chat", max_hits=60, per_seconds=3600, key=str(g.current_user["id"]))
    result = chat_service.ask(g.current_user["id"], g.community_id, body())
    return ok(result, 201)


@bp.get("/history")
@authz.require_member
def history():
    conversation_id = int_arg("conversation_id")
    limit = int_arg("limit", default=50, maximum=200)
    return ok(chat_service.history(g.current_user["id"], conversation_id, limit))


@bp.get("/prompts")
@authz.require_member
def prompts():
    return ok({"prompts": chat_service.SUGGESTED_PROMPTS})
