"""Personal reminder endpoints (spec 27)."""
from flask import Blueprint, g

from ..security import authz
from ..services import reminder_service
from .helpers import body, ok

bp = Blueprint("reminders", __name__, url_prefix="/api/reminders")


@bp.get("")
@authz.require_auth
def list_reminders():
    rows = reminder_service.list_personal(g.current_user["id"])
    return ok({"reminders": [reminder_service.reminder_payload(r) for r in rows]})


@bp.post("")
@authz.require_auth
def create_reminder():
    reminder = reminder_service.create_personal(g.current_user["id"], body())
    return ok({"reminder": reminder_service.reminder_payload(reminder)}, 201)


@bp.put("/<int:reminder_id>")
@authz.require_auth
def update_reminder(reminder_id):
    reminder = reminder_service.update_personal(g.current_user["id"], reminder_id, body())
    return ok({"reminder": reminder_service.reminder_payload(reminder)})


@bp.delete("/<int:reminder_id>")
@authz.require_auth
def delete_reminder(reminder_id):
    reminder_service.delete_personal(g.current_user["id"], reminder_id)
    return ok({"status": "cancelled"})
