"""Academic event endpoints (spec 27), including optional supporting material.

Supporting material lives UNDER an event rather than in its own resource tree:
`/api/events/<id>/attachments`. That is deliberate - a file here is only ever
meaningful as part of an academic record, so it inherits that record's
authorisation instead of carrying a second, parallel one.
"""
import urllib.parse

from flask import Blueprint, Response, g, request, stream_with_context

from .. import academic_time
from ..errors import ValidationError
from ..security import authz
from ..services import attachment_service, event_service, reminder_service
from ..services.change_history import change_payload, history_for
from .helpers import body, int_arg, ok

bp = Blueprint("events", __name__, url_prefix="/api/events")


@bp.get("")
@authz.require_member
def list_events():
    course_id = int_arg("course_id")
    rows = event_service.list_events(g.community_id, course_id=course_id)
    completed = event_service.completed_event_ids(g.current_user["id"])
    # One query for the page, so a list can show that the original paper exists
    # without a round trip per row.
    materials = attachment_service.attachments_by_event([r["id"] for r in rows])
    return ok({"events": [
        event_service.event_payload(r, r["id"] in completed, materials.get(r["id"]))
        for r in rows]})


@bp.get("/<int:event_id>")
@authz.require_member
def get_event(event_id):
    event = event_service.get_event(event_id, g.community_id)
    completed = event_service.completed_event_ids(g.current_user["id"])
    return ok({
        "event": event_service.event_payload(
            event, event["id"] in completed,
            attachment_service.attachments_for_payload(event_id)),
        "history": [change_payload(h) for h in history_for("academic_event", event_id)],
        # The same wall-clock moment the official reminder uses (REMINDER_HOUR
        # on the academic day before), on the university's clock. The page
        # offers it as the default for a personal reminder, so the rule lives
        # in one place instead of being re-derived in the browser.
        "reminder_default_local": _format_or_none(
            reminder_service.default_reminder_local(event["event_date"])),
    })


def _format_or_none(local):
    return academic_time.format_local(local) if local is not None else None


@bp.post("")
@authz.require_rep
def create_event():
    event = event_service.create_event(g.current_user["id"], g.community_id, body())
    return ok({"event": event_service.event_payload(
        event_service.get_event(event["id"], g.community_id))}, 201)


@bp.put("/<int:event_id>")
@authz.require_rep
def update_event(event_id):
    data = body()
    changes = {f: data[f] for f in event_service.MUTABLE_FIELDS if f in data}
    if not changes:
        raise ValidationError("No changes were supplied.")
    event, applied = event_service.update_event(
        g.current_user["id"], g.community_id, event_id, changes,
        expected_version=data.get("expected_version"))
    return ok({"event": event_service.event_payload(
        event_service.get_event(event["id"], g.community_id)), "applied_changes": applied})


@bp.post("/<int:event_id>/cancel")
@authz.require_rep
def cancel_event(event_id):
    data = body() if _has_body() else {}
    event = event_service.cancel_event(
        g.current_user["id"], g.community_id, event_id,
        expected_version=data.get("expected_version"))
    return ok({"event": event_service.event_payload(
        event_service.get_event(event["id"], g.community_id))})


@bp.post("/<int:event_id>/complete")
@authz.require_member
def mark_complete(event_id):
    """Personal completion state. Never mutates the official event (spec 28)."""
    data = body() if _has_body() else {}
    complete = data.get("complete", True)
    event_service.mark_complete(g.current_user["id"], g.community_id, event_id, bool(complete))
    return ok({"event_id": event_id, "completed": bool(complete)})


def _has_body():
    return request.get_json(silent=True) is not None


# ── Supporting material (optional) ──────────────────────────────────────────
#
# Never part of publishing. An event is created and published without ever
# touching these endpoints; material is added afterwards, by a rep, if the
# lecturer happened to give the brief as a file.


@bp.post("/<int:event_id>/attachments")
@authz.require_rep
def add_attachment(event_id):
    """Attach one file to an event. Verified rep only.

    `require_rep` is the outer gate; the service re-checks inside the writing
    transaction, because a role can change between the two (C·9).
    """
    upload = request.files.get("file")
    row = attachment_service.add_attachment(
        g.current_user["id"], g.community_id, event_id, upload)
    return ok({"attachment": attachment_service.attachment_payload(row)}, 201)


@bp.delete("/<int:event_id>/attachments/<int:attachment_id>")
@authz.require_rep
def remove_attachment(event_id, attachment_id):
    attachment_service.remove_attachment(
        g.current_user["id"], g.community_id, event_id, attachment_id)
    return ok({"removed": True})


@bp.get("/<int:event_id>/attachments/<int:attachment_id>")
@authz.require_member
def download_attachment(event_id, attachment_id):
    """Serve the bytes to a member of the event's community.

    Everything about this response is defensive:
      * the file is read through the application, never served from a static
        path, so there is no URL that maps to the storage directory;
      * `nosniff` stops a browser re-interpreting the declared type;
      * `Content-Disposition: attachment` means nothing renders in-page, so a
        stored document cannot execute in the application's origin;
      * the filename is quoted and also sent RFC 5987-encoded, because it came
        from a person and may be non-ASCII.
    """
    row, stream = attachment_service.open_attachment(
        g.community_id, event_id, attachment_id)
    name = row["original_name"]
    ascii_name = name.encode("ascii", "replace").decode("ascii")
    quoted = urllib.parse.quote(name, safe="")

    def _chunks():
        with stream as fh:
            while True:
                data = fh.read(64 * 1024)
                if not data:
                    break
                yield data

    response = Response(stream_with_context(_chunks()), mimetype=row["content_type"])
    response.headers["Content-Length"] = str(row["byte_size"])
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quoted}')
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    # Official material, scoped to one community: never store it in a shared
    # cache, and never keep it after sign-out.
    response.headers["Cache-Control"] = "private, no-store"
    return response
