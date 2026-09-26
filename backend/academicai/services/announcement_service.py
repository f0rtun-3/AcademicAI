"""Official announcements (spec 13, 19)."""
from .. import clock
from ..db.connection import execute, insert_returning_id, query_all, query_one, transaction
from ..errors import ConflictError, NotFoundError, ValidationError
from ..security import authz
from . import notification_copy, notification_service
from .change_history import record_change


def list_announcements(community_id, limit=50, conn=None):
    return query_all(
        """SELECT a.*, u.full_name AS author_name
           FROM announcements a JOIN users u ON u.id = a.created_by
           WHERE a.community_id = ? AND a.status = 'PUBLISHED'
           ORDER BY a.id DESC LIMIT ?""",
        (community_id, limit), conn=conn,
    )


def get_announcement(announcement_id, community_id, conn=None):
    row = query_one("SELECT * FROM announcements WHERE id = ? AND community_id = ?",
                    (announcement_id, community_id), conn=conn)
    if row is None:
        raise NotFoundError("Announcement not found.")
    return row


def create_announcement(actor_id, community_id, data, notify=True, conn=None):
    title = (data.get("title") or "").strip()
    body_text = (data.get("body") or "").strip()
    if not title:
        raise ValidationError("An announcement title is required.")
    if not body_text:
        raise ValidationError("An announcement body is required.")

    def _work(conn):
        authz.assert_rep(actor_id, community_id, conn, "publish announcements")
        now = clock.now_iso()
        announcement_id = insert_returning_id(
            """INSERT INTO announcements
               (community_id, title, body, original_message, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (community_id, title, body_text, data.get("original_message"), actor_id, now, now),
            conn=conn)
        record_change(community_id, "announcement", announcement_id, "ANNOUNCEMENT_PUBLISHED",
                      None, {"title": title}, actor_id=actor_id,
                      source_message=data.get("original_message"), conn=conn)
        if notify:
            notification_service.notify_community(
                community_id, subject=f"Announcement: {title}",
                body=f"{title}\n\n{body_text}",
                dedupe_key=f"announcement:{announcement_id}:published", conn=conn,
                **notification_copy.announcement(title, body_text))
        return query_one("SELECT * FROM announcements WHERE id = ?", (announcement_id,), conn=conn)

    if conn is not None:
        return _work(conn)
    with transaction() as new_conn:
        return _work(new_conn)


def update_announcement(actor_id, community_id, announcement_id, data, expected_version=None):
    with transaction() as conn:
        authz.assert_rep(actor_id, community_id, conn, "edit announcements")
        current = get_announcement(announcement_id, community_id, conn=conn)
        if current["status"] != "PUBLISHED":
            # A withdrawn announcement is history. Editing it would silently
            # change what was withdrawn (spec 18).
            raise ConflictError("This announcement has been withdrawn and cannot be edited.",
                                details={"status": current["status"]})
        if expected_version is not None and int(expected_version) != current["version"]:
            raise ConflictError(
                "This announcement changed since it was loaded.",
                details={"expected_version": expected_version,
                         "current_version": current["version"]})
        title = (data.get("title") or current["title"]).strip()
        body_text = (data.get("body") or current["body"]).strip()
        # The version is part of the WHERE clause, not just an earlier check.
        # BEGIN IMMEDIATE already serialises this read-check-write on SQLite,
        # but a compare-and-swap keeps the guarantee on a database whose
        # transactions do not take the write lock up front (spec 32).
        cursor = execute(
            """UPDATE announcements SET title = ?, body = ?, version = version + 1,
               updated_at = ? WHERE id = ? AND version = ?""",
            (title, body_text, clock.now_iso(), announcement_id, current["version"]),
            conn=conn)
        if cursor.rowcount == 0:
            raise ConflictError(
                "This announcement changed while it was being edited.",
                details={"current_version": current["version"]})
        record_change(community_id, "announcement", announcement_id, "ANNOUNCEMENT_UPDATED",
                      {"title": current["title"], "body": current["body"]},
                      {"title": title, "body": body_text}, actor_id=actor_id, conn=conn)
        return query_one("SELECT * FROM announcements WHERE id = ?", (announcement_id,), conn=conn)


def withdraw_announcement(actor_id, community_id, announcement_id):
    with transaction() as conn:
        authz.assert_rep(actor_id, community_id, conn, "withdraw announcements")
        current = get_announcement(announcement_id, community_id, conn=conn)
        if current["status"] != "PUBLISHED":
            # Withdrawing twice would write a second PUBLISHED -> WITHDRAWN
            # history row describing a transition that never happened.
            raise ConflictError("This announcement is already withdrawn.",
                                details={"status": current["status"]})
        execute("UPDATE announcements SET status = 'WITHDRAWN', updated_at = ? WHERE id = ?",
                (clock.now_iso(), announcement_id), conn=conn)
        record_change(community_id, "announcement", announcement_id, "ANNOUNCEMENT_WITHDRAWN",
                      {"status": "PUBLISHED"}, {"status": "WITHDRAWN"},
                      actor_id=actor_id, conn=conn)
        return True


def announcement_payload(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "status": row["status"],
        "version": row["version"],
        "created_at": row["created_at"],
        "author_name": row["author_name"] if "author_name" in row.keys() else None,
        "original_message": row["original_message"],
    }
