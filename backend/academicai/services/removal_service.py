"""Rep removal ballots (spec 12).

Any verified rep may initiate removal of another verified rep in the same
community. The electorate is deliberately broader than the rep bench: every
identity-verified, active member of that exact community may vote, except the
target.

Removal is community-specific. A successful removal revokes rep authority
immediately but leaves the target a community member as a STUDENT.
"""
from flask import current_app

from .. import clock
from ..db.connection import execute, insert_returning_id, query_all, query_one, transaction
from ..errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from ..security import authz
from . import community_service, notification_copy, notification_service
from .ballots import PASS, tally_outcome
from .change_history import record_change


def open_removal(actor_id, community_id, target_user_id):
    duration_h = current_app.config["BALLOT_DURATION_HOURS"]
    cooldown_days = current_app.config["REMOVAL_RETRY_COOLDOWN_DAYS"]
    with transaction() as conn:
        community_service.get_community(community_id, conn=conn)
        if not authz.is_rep(actor_id, community_id, conn=conn):
            raise AuthorizationError("Only a verified rep can initiate a removal.")
        if actor_id == target_user_id:
            raise ValidationError("A rep cannot open a removal ballot against themselves.")
        if not authz.is_rep(target_user_id, community_id, conn=conn):
            raise ValidationError("The target must be a verified rep in this community.")

        existing = query_one(
            """SELECT id FROM rep_removals
               WHERE community_id = ? AND target_user_id = ? AND status = 'OPEN'""",
            (community_id, target_user_id), conn=conn,
        )
        if existing is not None:
            raise ConflictError("A removal ballot against that rep is already open.")

        # After a failed attempt the same target cannot be re-targeted for 7 days.
        threshold = clock.to_iso(clock.now() - clock.days(cooldown_days))
        recent_failure = query_one(
            """SELECT resolved_at FROM rep_removals
               WHERE community_id = ? AND target_user_id = ? AND status = 'FAILED'
                 AND resolved_at IS NOT NULL AND resolved_at > ?
               ORDER BY resolved_at DESC LIMIT 1""",
            (community_id, target_user_id, threshold), conn=conn,
        )
        if recent_failure is not None:
            raise ConflictError(
                f"Another removal ballot against this rep cannot open for {cooldown_days} days "
                "after a failed attempt.",
                details={"cooldown_until": clock.to_iso(
                    clock.parse_iso(recent_failure["resolved_at"]) + clock.days(cooldown_days))},
            )

        now = clock.now()
        removal_id = insert_returning_id(
            """INSERT INTO rep_removals
               (community_id, target_user_id, initiated_by, status, opened_at, closes_at)
               VALUES (?, ?, ?, 'OPEN', ?, ?)""",
            (community_id, target_user_id, actor_id, clock.to_iso(now),
             clock.to_iso(now + clock.hours(duration_h))), conn=conn,
        )
        record_change(community_id, "rep_removal", removal_id, "REMOVAL_OPENED",
                      None, {"target_user_id": target_user_id}, actor_id=actor_id, conn=conn)
        notification_service.notify_community(
            community_id,
            subject="A rep removal vote has opened",
            body="A vote to remove one of your verified course reps is now open for 24 hours.",
            dedupe_key=f"removal:{removal_id}:opened",
            exclude_user_ids=(target_user_id,), conn=conn,
            **notification_copy.course_reps(
                "Rep removal vote open",
                "A vote to remove one of your course reps is open for 24 hours."),
        )
        return query_one("SELECT * FROM rep_removals WHERE id = ?", (removal_id,), conn=conn)


def cast_vote(voter_id, removal_id, vote):
    if vote not in ("YES", "NO"):
        raise ValidationError("Vote must be YES or NO.")
    with transaction() as conn:
        ballot = query_one("SELECT * FROM rep_removals WHERE id = ?", (removal_id,), conn=conn)
        if ballot is None:
            raise NotFoundError("Removal ballot not found.")
        if ballot["status"] != "OPEN":
            raise ConflictError("This ballot is closed.")
        if clock.parse_iso(ballot["closes_at"]) <= clock.now():
            raise ConflictError("This ballot has expired.")
        if voter_id == ballot["target_user_id"]:
            raise AuthorizationError("The target cannot vote on their own removal.")

        membership = authz.membership_in(voter_id, ballot["community_id"], conn=conn)
        if membership is None or membership["status"] != "ACTIVE":
            raise AuthorizationError("Only active members of this community can vote.")
        voter = query_one("SELECT * FROM users WHERE id = ?", (voter_id,), conn=conn)
        if not voter["email_verified"]:
            raise AuthorizationError("Only students with a verified email can vote.")

        if query_one("SELECT id FROM rep_removal_votes WHERE removal_id = ? AND voter_id = ?",
                     (removal_id, voter_id), conn=conn) is not None:
            raise ConflictError("You have already voted on this removal.")

        execute(
            """INSERT INTO rep_removal_votes (removal_id, voter_id, vote, created_at)
               VALUES (?, ?, ?, ?)""",
            (removal_id, voter_id, vote, clock.now_iso()), conn=conn,
        )
        return tally(removal_id, conn=conn)


def tally(removal_id, conn=None):
    rows = query_all(
        "SELECT vote, COUNT(*) AS n FROM rep_removal_votes WHERE removal_id = ? GROUP BY vote",
        (removal_id,), conn=conn,
    )
    counts = {r["vote"]: r["n"] for r in rows}
    return {"yes": counts.get("YES", 0), "no": counts.get("NO", 0)}


def results(user_id, removal_id):
    ballot = query_one("SELECT * FROM rep_removals WHERE id = ?", (removal_id,))
    if ballot is None:
        raise NotFoundError("Removal ballot not found.")
    membership = authz.membership_in(user_id, ballot["community_id"])
    if membership is None or membership["status"] != "ACTIVE":
        raise AuthorizationError("You do not have access to this ballot.")
    counts = tally(removal_id)
    return {
        "id": ballot["id"],
        "community_id": ballot["community_id"],
        "target_user_id": ballot["target_user_id"],
        "status": ballot["status"],
        "opened_at": ballot["opened_at"],
        "closes_at": ballot["closes_at"],
        "resolved_at": ballot["resolved_at"],
        "yes_votes": ballot["yes_votes"] if ballot["status"] != "OPEN" else counts["yes"],
        "no_votes": ballot["no_votes"] if ballot["status"] != "OPEN" else counts["no"],
        "min_votes_required": current_app.config["BALLOT_MIN_VOTES"],
    }


def close_ballot(removal_id, conn=None):
    """Resolve one expired removal ballot. Idempotent (spec 21)."""
    min_votes = current_app.config["BALLOT_MIN_VOTES"]
    ballot = query_one("SELECT * FROM rep_removals WHERE id = ?", (removal_id,), conn=conn)
    if ballot is None or ballot["status"] != "OPEN":
        return None

    counts = tally(removal_id, conn=conn)
    outcome, reason = tally_outcome(counts["yes"], counts["no"], min_votes)
    now = clock.now_iso()

    cur = execute(
        """UPDATE rep_removals SET status = ?, resolved_at = ?, yes_votes = ?, no_votes = ?
           WHERE id = ? AND status = 'OPEN'""",
        (outcome, now, counts["yes"], counts["no"], removal_id), conn=conn,
    )
    if cur.rowcount == 0:
        return None

    if outcome == PASS:
        # Authority is revoked; membership is not. The target stays a STUDENT.
        execute(
            """UPDATE community_members SET role = 'STUDENT', rep_since = NULL
               WHERE community_id = ? AND user_id = ? AND status = 'ACTIVE'""",
            (ballot["community_id"], ballot["target_user_id"]), conn=conn,
        )

    record_change(ballot["community_id"], "rep_removal", removal_id, f"REMOVAL_{outcome}",
                  {"status": "OPEN"},
                  {"status": outcome, "reason": reason,
                   "target_user_id": ballot["target_user_id"], **counts},
                  actor_id=None, conn=conn)

    subject = ("A course rep has been removed" if outcome == PASS
               else "Rep removal vote closed")
    body = _removal_email(ballot, outcome, reason, counts, conn=conn)
    notification_service.notify_community(
        ballot["community_id"], subject=subject, body=body,
        dedupe_key=f"removal:{removal_id}:{outcome}",
        conn=conn,
        **notification_copy.course_reps(
            "Course rep removed" if outcome == PASS else "Rep removal vote closed", body),
    )
    return {"status": outcome, "reason": reason, **counts}


def _removal_email(ballot, outcome, reason, counts, conn=None):
    target = query_one("SELECT full_name FROM users WHERE id = ?",
                       (ballot["target_user_id"],), conn=conn)
    name = target["full_name"] if target else "The rep"
    if outcome == PASS:
        return (f"{name} is no longer a verified course rep for your community. "
                f"They remain a member as a student.\n\n"
                f"Final votes: {counts['yes']} yes, {counts['no']} no.")
    reasons = {
        "not_enough_votes": "the ballot did not reach the minimum number of votes",
        "tie": "the vote was tied",
        "majority_no": "a majority voted no",
    }
    return (f"The vote to remove {name} did not pass because "
            f"{reasons.get(reason, reason)}.\n\n"
            f"Final votes: {counts['yes']} yes, {counts['no']} no.")


def close_expired_ballots(conn=None):
    due = query_all(
        "SELECT id FROM rep_removals WHERE status = 'OPEN' AND closes_at <= ?",
        (clock.now_iso(),), conn=conn,
    )
    resolved = []
    for row in due:
        outcome = close_ballot(row["id"], conn=conn)
        if outcome is not None:
            resolved.append((row["id"], outcome))
    return resolved


def list_removals(community_id):
    return query_all(
        """SELECT r.*, u.full_name AS target_name
           FROM rep_removals r JOIN users u ON u.id = r.target_user_id
           WHERE r.community_id = ? ORDER BY r.id DESC""",
        (community_id,),
    )


def my_vote(voter_id, removal_id, conn=None):
    row = query_one(
        "SELECT vote FROM rep_removal_votes WHERE removal_id = ? AND voter_id = ?",
        (removal_id, voter_id), conn=conn,
    )
    return row["vote"] if row else None


def removal_view(viewer_id, row, conn=None):
    """A removal ballot as one member sees it. Read-only; cast_vote re-checks."""
    counts = tally(row["id"], conn=conn)
    is_open = row["status"] == "OPEN"
    expired = clock.parse_iso(row["closes_at"]) <= clock.now()
    voted = my_vote(viewer_id, row["id"], conn=conn)
    return {
        "id": row["id"],
        "target_user_id": row["target_user_id"],
        "target_name": row["target_name"],
        "status": row["status"],
        "opened_at": row["opened_at"],
        "closes_at": row["closes_at"],
        "resolved_at": row["resolved_at"],
        "yes_votes": row["yes_votes"] if not is_open else counts["yes"],
        "no_votes": row["no_votes"] if not is_open else counts["no"],
        "min_votes_required": current_app.config["BALLOT_MIN_VOTES"],
        "is_me": row["target_user_id"] == viewer_id,
        "my_vote": voted,
        "can_vote": bool(is_open and not expired and voted is None
                         and row["target_user_id"] != viewer_id),
    }
