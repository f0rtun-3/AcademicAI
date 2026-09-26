"""Supporting material attached to an academic event.

WHAT THIS IS FOR
----------------
An assignment or project brief that a lecturer handed out as a photo, a PDF or
a Word document. AcademicAI keeps the structured record - title, instructions,
course, deadline - because that is what can be searched, filtered and reminded
on. This keeps the ORIGINAL beside it, so nobody has to scroll back through
WhatsApp in week nine to find the exact paper.

The two are not alternatives. The record is never replaced by the file.

OPTIONAL, ALWAYS
----------------
An event with no attachments is complete and normal. Nothing in this module is
reachable from the publishing path, and no write to academic_events consults
it. Adding material is a separate, later, entirely skippable action.

AUTHORITY
---------
Unchanged from every other official write (spec 11): only a verified rep of the
event's own community may add or remove material, and `assert_rep` is called
INSIDE the writing transaction rather than trusted from the route decorator.
Reading requires membership of that community, which `get_event` enforces by
scoping on community_id - an id from another community is a 404, not a leak.

A student can never modify official material. There is no endpoint that would
let them, and the service would refuse if there were.
"""
import os

from flask import current_app

from .. import clock
from ..db.connection import insert_returning_id, query_all, query_one, transaction
from ..errors import ConflictError, NotFoundError, ValidationError
from ..security import authz
from . import attachment_storage, event_service
from .change_history import record_change

MAX_NAME_LENGTH = 180


def _root():
    return current_app.config["UPLOAD_DIR"]


def _max_bytes():
    return current_app.config["MAX_ATTACHMENT_BYTES"]


def _max_per_event():
    return current_app.config["MAX_ATTACHMENTS_PER_EVENT"]


def _display_name(raw):
    """Keep the lecturer's filename for display, stripped of anything that
    could be read as a path. It never reaches the filesystem - see
    attachment_storage - but it is rendered in a browser and echoed in an
    HTTP header, so it is cleaned here rather than at each call site."""
    name = os.path.basename((raw or "").strip().replace("\\", "/"))
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '"\r\n')
    name = name.strip(". ")
    if not name:
        name = "attachment"
    return name[:MAX_NAME_LENGTH]


def attachment_payload(row):
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "filename": row["original_name"],
        "content_type": row["content_type"],
        "byte_size": row["byte_size"],
        "uploaded_at": row["created_at"],
        "uploaded_by": row["uploaded_by"],
        # Deliberately NOT the storage key and not a path. The client addresses
        # material by its id through an authorised route; where the bytes live
        # is not the client's business and must not become a URL it can guess.
    }


def list_attachments(event_id, conn=None):
    return query_all(
        """SELECT * FROM event_attachments
           WHERE event_id = ? AND status = 'ACTIVE'
           ORDER BY id""",
        (event_id,), conn=conn,
    )


def attachments_for_payload(event_id, conn=None):
    return [attachment_payload(r) for r in list_attachments(event_id, conn=conn)]


def attachments_by_event(event_ids, conn=None):
    """One query for a whole page of events, not one per row.

    A calendar or dashboard needs to show that the original paper exists, which
    means the list endpoints need this too; doing it per event would be a query
    per row for a fact that is usually empty.
    """
    ids = [int(i) for i in event_ids]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = query_all(
        f"""SELECT * FROM event_attachments
            WHERE status = 'ACTIVE' AND event_id IN ({placeholders})
            ORDER BY id""",
        tuple(ids), conn=conn,
    )
    grouped = {}
    for row in rows:
        grouped.setdefault(row["event_id"], []).append(attachment_payload(row))
    return grouped


def get_attachment(attachment_id, event_id, community_id, conn=None):
    """Scoped through the event, so a stray id cannot reach another community."""
    event_service.get_event(event_id, community_id, conn=conn)
    row = query_one(
        """SELECT * FROM event_attachments
           WHERE id = ? AND event_id = ? AND status = 'ACTIVE'""",
        (attachment_id, event_id), conn=conn,
    )
    if row is None:
        raise NotFoundError("Supporting material not found.")
    return row


def add_attachment(actor_id, community_id, event_id, upload):
    """Store one file against an event. Rep only.

    `upload` is a Werkzeug FileStorage. The bytes are written first and the row
    second; if the row fails the bytes are removed, so a file never outlives
    the record that points at it.
    """
    if upload is None or not getattr(upload, "filename", ""):
        raise ValidationError("Choose a file to attach.")

    with transaction() as conn:
        event = event_service.get_event(event_id, community_id, conn=conn)
        authz.assert_rep(actor_id, community_id, conn, "manage supporting material")
        if event["status"] == "CANCELLED":
            raise ConflictError(
                "This event is cancelled, so its supporting material cannot be changed.")
        existing = list_attachments(event_id, conn=conn)
        if len(existing) >= _max_per_event():
            raise ValidationError(
                f"An event can hold {_max_per_event()} pieces of supporting material. "
                "Remove one before adding another.")

        display = _display_name(upload.filename)
        storage_key, content_type, size, checksum = attachment_storage.save(
            _root(), upload.stream, upload.mimetype, _max_bytes())

        try:
            attachment_id = insert_returning_id(
                """INSERT INTO event_attachments
                   (event_id, storage_key, original_name, content_type, byte_size,
                    checksum, status, uploaded_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)""",
                (event_id, storage_key, display, content_type, size, checksum,
                 actor_id, clock.now_iso()),
                conn=conn,
            )
        except Exception:
            attachment_storage.delete(_root(), storage_key)
            raise

        # Part of the official record, so it is part of the audit trail the
        # community can already see.
        record_change(community_id, "academic_event", event_id, "MATERIAL_ATTACHED",
                      None, display, actor_id=actor_id, conn=conn)
        return query_one("SELECT * FROM event_attachments WHERE id = ?",
                         (attachment_id,), conn=conn)


def remove_attachment(actor_id, community_id, event_id, attachment_id):
    """Withdraw material. Rep only.

    The ROW is kept and marked REMOVED while the bytes are deleted: the record
    should still be able to say that material was published and later withdrawn,
    which a hard delete would erase.
    """
    with transaction() as conn:
        row = get_attachment(attachment_id, event_id, community_id, conn=conn)
        authz.assert_rep(actor_id, community_id, conn, "manage supporting material")
        conn.execute(
            """UPDATE event_attachments
               SET status = 'REMOVED', removed_by = ?, removed_at = ?
               WHERE id = ?""",
            (actor_id, clock.now_iso(), attachment_id),
        )
        record_change(community_id, "academic_event", event_id, "MATERIAL_REMOVED",
                      row["original_name"], None, actor_id=actor_id, conn=conn)
        storage_key = row["storage_key"]

    # Outside the transaction: losing the bytes must not roll back the record,
    # and an orphaned file is a smaller problem than a row pointing at nothing.
    attachment_storage.delete(_root(), storage_key)
    return True


def open_attachment(community_id, event_id, attachment_id):
    """Return (row, stream) for a member of the event's community.

    Authorisation is the event's: `get_attachment` resolves through
    `get_event`, which is scoped by community_id, and the route requires
    membership. There is no public URL and no path traversal surface, because
    the caller supplies an id and never a name.
    """
    row = get_attachment(attachment_id, event_id, community_id)
    stream = attachment_storage.open_stream(_root(), row["storage_key"])
    if stream is None:
        raise NotFoundError("That file is no longer stored.")
    return row, stream
