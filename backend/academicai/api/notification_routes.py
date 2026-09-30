"""In-app notifications (spec 19, 21).

These endpoints read the SAME `notifications` rows the worker writes for email:
a row is one event with two outputs. Nothing here enqueues, sends, retries or
touches delivery state - that is the worker's.

Only the caller's rows, enforced in the query rather than by a check the route
is trusted to have performed. No endpoint accepts a user id: the identity comes
from the bearer token via `require_auth`, and every statement in
notification_service filters on it. Another person's notification id returns
404, the same as an id that does not exist, so existence cannot be probed.

`require_auth`, not `require_member`: a student between communities still has a
history to read, and the bell must not 403 mid-transfer.
"""
from flask import Blueprint, g

from ..errors import NotFoundError
from ..security import authz
from ..services import notification_service, reminder_service
from .helpers import int_arg, ok

bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")


@bp.get("")
@authz.require_auth
def list_notifications():
    """The bell's payload: recent rows, the unread badge, and when to look next.

    All in one response because the client polls this, and two round trips to
    render one bell is one too many.

    `next_reminder_at` is the soonest reminder still waiting to fire for this
    user (UTC ISO-8601), or null. It is a hint for WHEN to ask again - the bell
    polls just after it, so a reminder's notification is seen the moment the
    worker creates it. It decides nothing: the notification still exists only
    once the worker has processed the reminder.
    """
    user_id = g.current_user["id"]
    limit = int_arg("limit", default=20, maximum=50)
    rows = notification_service.list_for_user(user_id, limit=limit)
    return ok({
        "notifications": [notification_service.notification_payload(r) for r in rows],
        "unread": notification_service.unread_count(user_id),
        "next_reminder_at": reminder_service.next_due_for_user(user_id),
    })


@bp.post("/<int:notification_id>/read")
@authz.require_auth
def read_one(notification_id):
    user_id = g.current_user["id"]
    if not notification_service.mark_read(user_id, notification_id):
        # Either it is not theirs, or it was already read. Distinguish the two
        # only for rows that ARE theirs, so a stranger's id never produces a
        # different answer from a missing one.
        if not notification_service.exists_for_user(user_id, notification_id):
            raise NotFoundError("Notification not found.")
    return ok({"id": notification_id, "unread": notification_service.unread_count(user_id)})


@bp.post("/read-all")
@authz.require_auth
def read_all():
    user_id = g.current_user["id"]
    marked = notification_service.mark_all_read(user_id)
    return ok({"marked": marked, "unread": notification_service.unread_count(user_id)})
