"""Personal reminder endpoints (spec 27)."""
from flask import Blueprint, g

from ..security import authz
from ..services import reminder_service
from .helpers import body, ok

bp = Blueprint("reminders", __name__, url_prefix="/api/reminders")


@bp.get("")
@authz.require_auth
def list_reminders():
    user_id = g.current_user["id"]
    return ok({"reminders": reminder_service.payloads_for_user(
        user_id, reminder_service.list_personal(user_id))})


@bp.post("")
@authz.require_auth
def create_reminder():
    user_id = g.current_user["id"]
    reminder = reminder_service.create_personal(user_id, body())
    return ok({"reminder": reminder_service.payloads_for_user(user_id, [reminder])[0]}, 201)


@bp.put("/<int:reminder_id>")
@authz.require_auth
def update_reminder(reminder_id):
    user_id = g.current_user["id"]
    reminder = reminder_service.update_personal(user_id, reminder_id, body())
    return ok({"reminder": reminder_service.payloads_for_user(user_id, [reminder])[0]})


@bp.delete("/<int:reminder_id>")
@authz.require_auth
def delete_reminder(reminder_id):
    reminder_service.delete_personal(g.current_user["id"], reminder_id)
    return ok({"status": "cancelled"})
