"""Notifications: one row, two channels (spec 19).

A row is one thing that happened to one person, and it reaches them two ways:

  in the app   the bell reads the row the moment it is inserted - the worker's
               reminder job inserts it at the reminder's time. Nothing about
               email can remove, hide or delay this.
  by email     `dispatch_pending` sends the same row afterwards. `status`,
               `attempts`, `sent_at` and `last_error` are the EMAIL's delivery
               state and nothing else; the bell never reads them.

Spec 19 named email as the MVP's only channel; the bell was added on top of
the same outbox rows, so every notification - reminders included - is both
shown in the app and emailed. An email that fails is recorded as failed and
logged; the in-app notification is untouched.

Recipients are resolved at publish time and written as concrete outbox rows,
which is what stops a student who joins later from receiving a "new
assignment" notice published before they arrived.

Course-scoped recipients are the INTERSECTION of active community members and
active course enrollments, so neither a stale enrollment row nor a former
member can be notified.
"""
import logging

from .. import clock
from ..db.connection import execute, query_all, query_one, transaction
from . import email_service

MAX_ATTEMPTS = 5

log = logging.getLogger("academicai.notifications")


def _insert(user_id, community_id, subject, body, dedupe_key, conn,
            kind=None, link=None, app_subject=None, app_body=None):
    """Insert one outbox row, ignoring an exact duplicate.

    The unique dedupe_key is what makes re-running a job idempotent: a second
    attempt to queue the same message for the same recipient is dropped by the
    database rather than by a race-prone application check (spec 21).

    ON CONFLICT (dedupe_key) DO NOTHING drops that duplicate and only that: any
    other failure (a missing user, a broken constraint) still raises. It also
    raises nothing for the duplicate, which matters inside a transaction - an
    error there aborts the whole PostgreSQL transaction, not just the insert.
    Whether the row went in is the affected-row count. A NULL key never
    conflicts, so a message without one is always queued, as before.
    """
    cursor = execute(
        """INSERT INTO notifications
           (user_id, community_id, subject, body, status, dedupe_key, created_at,
            kind, link, app_subject, app_body)
           VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?)
           ON CONFLICT (dedupe_key) DO NOTHING""",
        (user_id, community_id, subject, body, dedupe_key, clock.now_iso(),
         kind, link, app_subject, app_body), conn=conn,
    )
    return cursor.rowcount == 1


def enqueue(user_ids, community_id, subject, body, dedupe_key=None, conn=None,
            kind=None, link=None, app_subject=None, app_body=None):
    """Queue one message per recipient.

    `subject` and `body` are the EMAIL, which must stand on its own (spec 19).
    `kind`, `link`, `app_subject` and `app_body` are what the BELL shows - what
    sort of thing happened, where it lives, and a short in-app wording of it
    (see notification_copy.py). They are optional so that every existing caller
    keeps working unchanged; a row without them still shows its email wording.
    """
    queued = 0
    for user_id in user_ids:
        key = f"{dedupe_key}:u{user_id}" if dedupe_key else None
        if _insert(user_id, community_id, subject, body, key, conn, kind, link,
                   app_subject, app_body):
            queued += 1
    return queued


# ── The bell ───────────────────────────────────────────────────────────────
#
# Reading is ALWAYS scoped by user_id, in the query, not by a check the caller
# is trusted to have done. There is no code path here that can return a row
# belonging to somebody else, and no endpoint takes a user id from the client.

def notification_payload(row):
    """What the bell reads. It prefers the in-app wording and falls back to the
    email wording for rows queued before the in-app columns existed."""
    keys = row.keys()
    in_app = "app_subject" in keys and row["app_subject"] is not None
    return {
        "id": row["id"],
        "subject": row["app_subject"] if in_app else row["subject"],
        "body": row["app_body"] if in_app else row["body"],
        "kind": row["kind"] if "kind" in row.keys() else None,
        "link": row["link"] if "link" in row.keys() else None,
        "created_at": row["created_at"],
        "read_at": row["read_at"] if "read_at" in row.keys() else None,
        # Deliberately NOT the delivery state. Whether the email left the
        # building is an operational fact about the outbox, not something to
        # report to a student as if it were about their reminder.
    }


def list_for_user(user_id, limit=20, conn=None):
    return query_all(
        """SELECT * FROM notifications
           WHERE user_id = ? ORDER BY id DESC LIMIT ?""",
        (user_id, max(1, min(int(limit), 100))), conn=conn,
    )


def unread_count(user_id, conn=None):
    row = query_one(
        "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read_at IS NULL",
        (user_id,), conn=conn,
    )
    return row["n"] if row else 0


def mark_read(user_id, notification_id, conn=None):
    """Returns True when THIS user's unread row was marked.

    The user_id is part of the WHERE clause, so another person's id simply
    matches nothing — the caller cannot mark, or learn about, a row that is
    not theirs.
    """
    cursor = execute(
        """UPDATE notifications SET read_at = ?
           WHERE id = ? AND user_id = ? AND read_at IS NULL""",
        (clock.now_iso(), notification_id, user_id), conn=conn,
    )
    return cursor.rowcount == 1


def mark_all_read(user_id, conn=None):
    cursor = execute(
        "UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL",
        (clock.now_iso(), user_id), conn=conn,
    )
    return cursor.rowcount


def exists_for_user(user_id, notification_id, conn=None):
    return query_one(
        "SELECT 1 FROM notifications WHERE id = ? AND user_id = ?",
        (notification_id, user_id), conn=conn,
    ) is not None


def community_recipients(community_id, exclude_user_ids=(), conn=None):
    rows = query_all(
        """SELECT cm.user_id FROM community_members cm
           WHERE cm.community_id = ? AND cm.status = 'ACTIVE'""",
        (community_id,), conn=conn,
    )
    excluded = set(exclude_user_ids)
    return [r["user_id"] for r in rows if r["user_id"] not in excluded]


def course_recipients(community_id, course_id, exclude_user_ids=(), conn=None):
    """Active members INTERSECT active enrollments (spec 19, 24)."""
    rows = query_all(
        """SELECT cm.user_id
           FROM community_members cm
           JOIN course_enrollments ce ON ce.user_id = cm.user_id AND ce.status = 'ACTIVE'
           JOIN courses c ON c.id = ce.course_id
           WHERE cm.community_id = ? AND cm.status = 'ACTIVE'
             AND ce.course_id = ? AND c.community_id = cm.community_id""",
        (community_id, course_id), conn=conn,
    )
    excluded = set(exclude_user_ids)
    return [r["user_id"] for r in rows if r["user_id"] not in excluded]


def recipients_for(community_id, course_id=None, exclude_user_ids=(), conn=None):
    if course_id is None:
        return community_recipients(community_id, exclude_user_ids, conn=conn)
    return course_recipients(community_id, course_id, exclude_user_ids, conn=conn)


def notify_community(community_id, subject, body, dedupe_key=None,
                     exclude_user_ids=(), conn=None, **in_app):
    return enqueue(community_recipients(community_id, exclude_user_ids, conn=conn),
                   community_id, subject, body, dedupe_key, conn=conn, **in_app)


def notify_course(community_id, course_id, subject, body, dedupe_key=None,
                  exclude_user_ids=(), conn=None, **in_app):
    return enqueue(course_recipients(community_id, course_id, exclude_user_ids, conn=conn),
                   community_id, subject, body, dedupe_key, conn=conn, **in_app)


def pending(limit=100, conn=None):
    return query_all(
        """SELECT n.*, u.email FROM notifications n JOIN users u ON u.id = n.user_id
           WHERE n.status = 'PENDING' AND n.attempts < ?
           ORDER BY n.id LIMIT ?""",
        (MAX_ATTEMPTS, limit), conn=conn,
    )


def dispatch_pending(limit=100):
    """Send queued email. Each message is committed independently so one bad
    address cannot roll back deliveries that already succeeded (spec 21)."""
    with transaction() as conn:
        batch = pending(limit, conn=conn)
        # Claim each row by compare-and-swap on the attempt counter it was read
        # with. Two workers that read the same PENDING row both try to move it
        # from attempts=N to N+1; BEGIN IMMEDIATE serialises them, so the first
        # succeeds and the second sees rowcount 0 and skips the row. Without
        # this the claim left the row PENDING, and a second worker reading
        # concurrently would send the same email again.
        claimed = []
        for row in batch:
            cursor = execute(
                """UPDATE notifications SET attempts = ?
                   WHERE id = ? AND attempts = ? AND status = 'PENDING'""",
                (row["attempts"] + 1, row["id"], row["attempts"]), conn=conn,
            )
            if cursor.rowcount == 1:
                claimed.append(dict(row))

    sent, failed, simulated = 0, 0, 0
    for row in claimed:
        try:
            result = email_service.send(row["email"], row["subject"], row["body"])
        except Exception as exc:  # delivery failure is expected, and usually retryable
            # A permanent refusal is not asked again; anything else is, up to
            # MAX_ATTEMPTS. Either way only the EMAIL is marked - the row stays
            # in the person's bell exactly as it was.
            attempt = row["attempts"] + 1
            permanent = getattr(exc, "permanent", False)
            status = "FAILED" if permanent or attempt >= MAX_ATTEMPTS else "PENDING"
            with transaction() as conn:
                execute("UPDATE notifications SET status = ?, last_error = ? WHERE id = ?",
                        (status, str(exc)[:200], row["id"]), conn=conn)
            log.warning("email not delivered: notification=%s attempt=%s/%s %s: %s",
                        row["id"], attempt, MAX_ATTEMPTS,
                        "permanent, not retried" if permanent
                        else ("giving up" if status == "FAILED" else "will retry"),
                        str(exc)[:200])
            failed += 1
        else:
            # SENT means a provider accepted the message. A development backend
            # that printed it to a terminal is recorded as SIMULATED, because
            # claiming delivery we did not make is how an outbox stops being
            # evidence of anything. Neither is retried: the row is finished.
            status = "SENT" if result.delivered else "SIMULATED"
            with transaction() as conn:
                execute("UPDATE notifications SET status = ?, sent_at = ? WHERE id = ?",
                        (status, clock.now_iso(), row["id"]), conn=conn)
            if result.delivered:
                sent += 1
            else:
                simulated += 1
    return {"sent": sent, "failed": failed, "simulated": simulated}


def for_user(user_id, limit=50, conn=None):
    return query_all(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit), conn=conn,
    )


def cancel_pending_for_community(user_id, community_id, reason, conn=None):
    execute(
        """UPDATE notifications SET status = 'FAILED', last_error = ?
           WHERE user_id = ? AND community_id = ? AND status = 'PENDING'""",
        (reason, user_id, community_id), conn=conn,
    )
