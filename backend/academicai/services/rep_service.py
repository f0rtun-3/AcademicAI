"""Rep verification ballots (spec 8, 11).

Nomination grants nothing. Authority begins only when a ballot resolves in the
candidate's favour, and resolution is idempotent: running it twice can never
promote a candidate twice or emit a second set of notifications.
"""
from flask import current_app

from .. import clock
from ..db.connection import execute, insert_returning_id, query_all, query_one, transaction
from ..errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from ..security import authz
from . import community_service, notification_copy, notification_service
from .ballots import FAIL, PASS, tally_outcome
from .change_history import record_change


def _config():
    return (
        current_app.config["BALLOT_DURATION_HOURS"],
        current_app.config["BALLOT_MIN_VOTES"],
        current_app.config["MAX_REPS_PER_COMMUNITY"],
        current_app.config["FAILED_CANDIDATE_COOLDOWN_DAYS"],
        current_app.config["MIN_ELECTION_PREPARATION"],
    )


def rep_count(community_id, conn=None):
    row = query_one(
        """SELECT COUNT(*) AS n FROM community_members
           WHERE community_id = ? AND status = 'ACTIVE' AND role = 'VERIFIED_REP'""",
        (community_id,), conn=conn,
    )
    return row["n"] if row else 0


def _assert_no_cooldown(community_id, user_id, cooldown_days, conn):
    """A failed candidacy and a successful removal both impose a 7-day wait
    before the same person may stand again in that community (spec 11, 12)."""
    threshold = clock.to_iso(clock.now() - clock.days(cooldown_days))
    failed = query_one(
        """SELECT resolved_at FROM rep_nominations
           WHERE community_id = ? AND user_id = ? AND status = 'FAILED'
             AND resolved_at IS NOT NULL AND resolved_at > ?
           ORDER BY resolved_at DESC LIMIT 1""",
        (community_id, user_id, threshold), conn=conn,
    )
    if failed is not None:
        raise ConflictError(
            f"This candidate must wait {cooldown_days} days after a failed ballot.",
            details={"cooldown_until": clock.to_iso(
                clock.parse_iso(failed["resolved_at"]) + clock.days(cooldown_days))},
        )
    removed = query_one(
        """SELECT resolved_at FROM rep_removals
           WHERE community_id = ? AND target_user_id = ? AND status = 'PASSED'
             AND resolved_at IS NOT NULL AND resolved_at > ?
           ORDER BY resolved_at DESC LIMIT 1""",
        (community_id, user_id, threshold), conn=conn,
    )
    if removed is not None:
        raise ConflictError(
            f"A removed rep must wait {cooldown_days} days before standing again.",
            details={"cooldown_until": clock.to_iso(
                clock.parse_iso(removed["resolved_at"]) + clock.days(cooldown_days))},
        )


def candidate_cooldown_until(community_id, user_id, conn=None):
    """When this person may next stand here, or None if they may stand now (J·4).

    READ-ONLY, and deliberately a separate function from _assert_no_cooldown.
    This one answers a display question; that one enforces the rule inside the
    nominating transaction. Duplicating the lookup rather than sharing a code
    path with the enforcer keeps it impossible for a UI-facing helper to become
    load-bearing: nominate() never consults this, and a wrong answer here can
    only mis-draw a screen, never admit a candidacy the rules refuse.
    """
    cooldown_days = current_app.config["FAILED_CANDIDATE_COOLDOWN_DAYS"]
    threshold = clock.to_iso(clock.now() - clock.days(cooldown_days))
    row = query_one(
        """SELECT MAX(resolved_at) AS resolved_at FROM (
               SELECT resolved_at FROM rep_nominations
               WHERE community_id = ? AND user_id = ? AND status = 'FAILED'
                 AND resolved_at IS NOT NULL AND resolved_at > ?
               UNION ALL
               SELECT resolved_at FROM rep_removals
               WHERE community_id = ? AND target_user_id = ? AND status = 'PASSED'
                 AND resolved_at IS NOT NULL AND resolved_at > ?
           )""",
        (community_id, user_id, threshold, community_id, user_id, threshold), conn=conn,
    )
    if row is None or row["resolved_at"] is None:
        return None
    return clock.to_iso(clock.parse_iso(row["resolved_at"]) + clock.days(cooldown_days))


def nominate(actor_id, community_id, candidate_id):
    """Open a verification ballot.

    A student may nominate themselves. Nominating someone else requires existing
    rep authority in that same community (spec 5).
    """
    duration_h, _min_votes, max_reps, cooldown_days, min_electorate = _config()
    with transaction() as conn:
        community = community_service.get_community(community_id, conn=conn)
        if community["status"] == "ARCHIVED":
            raise ConflictError("That academic community has been archived.")

        actor_membership = authz.membership_in(actor_id, community_id, conn=conn)
        if actor_membership is None or actor_membership["status"] != "ACTIVE":
            raise AuthorizationError("Only an active member of this community can nominate.")

        if candidate_id != actor_id and not authz.is_rep(actor_id, community_id, conn=conn):
            raise AuthorizationError("Only a verified rep can nominate another student.")

        candidate_membership = authz.membership_in(candidate_id, community_id, conn=conn)
        if candidate_membership is None or candidate_membership["status"] != "ACTIVE":
            raise ValidationError("A candidate must be an active member of this community.")
        candidate = query_one("SELECT * FROM users WHERE id = ?", (candidate_id,), conn=conn)
        if candidate is None or not candidate["email_verified"]:
            raise ValidationError("A candidate must have a verified email address.")
        if candidate_membership["role"] == "VERIFIED_REP":
            raise ConflictError("That student is already a verified rep.")

        if rep_count(community_id, conn=conn) >= max_reps:
            raise ConflictError(f"This community already has {max_reps} verified reps.")

        open_ballot = query_one(
            """SELECT id FROM rep_nominations
               WHERE community_id = ? AND user_id = ? AND status = 'OPEN'""",
            (community_id, candidate_id), conn=conn,
        )
        if open_ballot is not None:
            raise ConflictError("A verification ballot for that candidate is already open.")

        _assert_no_cooldown(community_id, candidate_id, cooldown_days, conn=conn)

        # An election must be winnable before it is opened.
        #
        # A candidate may not vote for themselves and a ballot needs
        # BALLOT_MIN_VOTES actual votes, so the community needs that many
        # eligible voters BESIDES the candidate. With the default of 3 that
        # means at least 4 eligible members in total. Opening a ballot below
        # that threshold would guarantee a 24-hour wait followed by a failure
        # that no one could have prevented (spec 8, 11).
        electorate = community_service.eligible_electorate(community_id, conn=conn)
        eligible_voters = len([u for u in electorate if u["id"] != candidate_id])
        if eligible_voters < _min_votes:
            raise ConflictError(
                f"A rep election needs at least {_min_votes} eligible voters besides the "
                f"candidate, so this community needs at least {_min_votes + 1} eligible "
                "members before an election can start.",
                details={
                    "eligible_members": len(electorate),
                    "eligible_voters": eligible_voters,
                    "required_voters": _min_votes,
                    "required_members": _min_votes + 1,
                    "preparation_threshold": min_electorate,
                },
            )

        now = clock.now()
        nomination_id = insert_returning_id(
            """INSERT INTO rep_nominations
               (community_id, user_id, nominated_by, status, opened_at, closes_at)
               VALUES (?, ?, ?, 'OPEN', ?, ?)""",
            (community_id, candidate_id, actor_id, clock.to_iso(now),
             clock.to_iso(now + clock.hours(duration_h))), conn=conn,
        )
        record_change(community_id, "rep_nomination", nomination_id, "NOMINATION_OPENED",
                      None, {"candidate_id": candidate_id}, actor_id=actor_id, conn=conn)
        return query_one("SELECT * FROM rep_nominations WHERE id = ?", (nomination_id,), conn=conn)


def cast_vote(voter_id, nomination_id, vote):
    """One vote per eligible voter. A candidate may not vote for themselves."""
    if vote not in ("YES", "NO"):
        raise ValidationError("Vote must be YES or NO.")
    with transaction() as conn:
        ballot = query_one("SELECT * FROM rep_nominations WHERE id = ?", (nomination_id,), conn=conn)
        if ballot is None:
            raise NotFoundError("Nomination not found.")
        if ballot["status"] != "OPEN":
            raise ConflictError("This ballot is closed.")
        if clock.parse_iso(ballot["closes_at"]) <= clock.now():
            raise ConflictError("This ballot has expired.")
        if voter_id == ballot["user_id"]:
            raise AuthorizationError("A candidate cannot vote on their own nomination.")

        membership = authz.membership_in(voter_id, ballot["community_id"], conn=conn)
        if membership is None or membership["status"] != "ACTIVE":
            raise AuthorizationError("Only active members of this community can vote.")
        voter = query_one("SELECT * FROM users WHERE id = ?", (voter_id,), conn=conn)
        if not voter["email_verified"]:
            raise AuthorizationError("Only students with a verified email can vote.")

        existing = query_one(
            "SELECT id FROM rep_verification_votes WHERE nomination_id = ? AND voter_id = ?",
            (nomination_id, voter_id), conn=conn,
        )
        if existing is not None:
            raise ConflictError("You have already voted on this nomination.")

        execute(
            """INSERT INTO rep_verification_votes (nomination_id, voter_id, vote, created_at)
               VALUES (?, ?, ?, ?)""",
            (nomination_id, voter_id, vote, clock.now_iso()), conn=conn,
        )
        return tally(nomination_id, conn=conn)


def tally(nomination_id, conn=None):
    rows = query_all(
        "SELECT vote, COUNT(*) AS n FROM rep_verification_votes WHERE nomination_id = ? GROUP BY vote",
        (nomination_id,), conn=conn,
    )
    counts = {r["vote"]: r["n"] for r in rows}
    return {"yes": counts.get("YES", 0), "no": counts.get("NO", 0)}


def results(user_id, nomination_id):
    ballot = query_one("SELECT * FROM rep_nominations WHERE id = ?", (nomination_id,))
    if ballot is None:
        raise NotFoundError("Nomination not found.")
    membership = authz.membership_in(user_id, ballot["community_id"])
    if membership is None or membership["status"] != "ACTIVE":
        raise AuthorizationError("You do not have access to this ballot.")
    counts = tally(nomination_id)
    return {
        "id": ballot["id"],
        "community_id": ballot["community_id"],
        "candidate_id": ballot["user_id"],
        "status": ballot["status"],
        "opened_at": ballot["opened_at"],
        "closes_at": ballot["closes_at"],
        "resolved_at": ballot["resolved_at"],
        "yes_votes": ballot["yes_votes"] if ballot["status"] != "OPEN" else counts["yes"],
        "no_votes": ballot["no_votes"] if ballot["status"] != "OPEN" else counts["no"],
        "min_votes_required": current_app.config["BALLOT_MIN_VOTES"],
    }


def list_candidates(community_id):
    return query_all(
        """SELECT n.*, u.full_name
           FROM rep_nominations n JOIN users u ON u.id = n.user_id
           WHERE n.community_id = ? ORDER BY n.id DESC""",
        (community_id,),
    )


def my_vote(voter_id, nomination_id, conn=None):
    """How this voter voted on a ballot, or None. Read-only."""
    row = query_one(
        "SELECT vote FROM rep_verification_votes WHERE nomination_id = ? AND voter_id = ?",
        (nomination_id, voter_id), conn=conn,
    )
    return row["vote"] if row else None


def ballot_view(viewer_id, row, conn=None):
    """A ballot as one member sees it.

    Includes whether the viewer may still vote so the client can avoid
    offering an action that would be refused. This is a convenience, not a
    control: cast_vote re-checks every condition itself.
    """
    counts = tally(row["id"], conn=conn)
    is_open = row["status"] == "OPEN"
    expired = clock.parse_iso(row["closes_at"]) <= clock.now()
    voted = my_vote(viewer_id, row["id"], conn=conn)
    return {
        "id": row["id"],
        "candidate_id": row["user_id"],
        "full_name": row["full_name"],
        "status": row["status"],
        "opened_at": row["opened_at"],
        "closes_at": row["closes_at"],
        "resolved_at": row["resolved_at"],
        "yes_votes": row["yes_votes"] if not is_open else counts["yes"],
        "no_votes": row["no_votes"] if not is_open else counts["no"],
        "min_votes_required": current_app.config["BALLOT_MIN_VOTES"],
        "is_me": row["user_id"] == viewer_id,
        "my_vote": voted,
        "can_vote": bool(is_open and not expired and voted is None
                         and row["user_id"] != viewer_id),
    }


def close_ballot(nomination_id, conn=None):
    """Resolve one expired ballot. Safe to call repeatedly (spec 21).

    The status transition is a conditional UPDATE guarded on status='OPEN', so a
    second caller finds nothing to update and performs no side effects at all.
    """
    _duration, min_votes, max_reps, _cooldown, _electorate = _config()
    ballot = query_one("SELECT * FROM rep_nominations WHERE id = ?", (nomination_id,), conn=conn)
    if ballot is None or ballot["status"] != "OPEN":
        return None

    counts = tally(nomination_id, conn=conn)
    outcome, reason = tally_outcome(counts["yes"], counts["no"], min_votes)

    # A ballot decides a vote, not eligibility. Both can change during the 24
    # hours it is open, so re-check before promoting anyone (spec 10, 11).
    if outcome == PASS and rep_count(ballot["community_id"], conn=conn) >= max_reps:
        outcome, reason = FAIL, "no_rep_vacancy"
    if outcome == PASS and not authz.is_eligible_member(
            ballot["user_id"], ballot["community_id"], conn=conn):
        # The candidate left, transferred, or stopped being email-verified.
        outcome, reason = FAIL, "candidate_no_longer_eligible"
    if outcome == PASS:
        # The session can be archived while a ballot is still open. Promoting
        # into an archived community would hand rep authority to someone in a
        # session that has already ended (spec 23).
        community = query_one("SELECT status FROM academic_communities WHERE id = ?",
                              (ballot["community_id"],), conn=conn)
        if community is None or community["status"] == "ARCHIVED":
            outcome, reason = FAIL, "community_archived"

    now = clock.now_iso()
    cur = execute(
        """UPDATE rep_nominations
           SET status = ?, resolved_at = ?, yes_votes = ?, no_votes = ?
           WHERE id = ? AND status = 'OPEN'""",
        (outcome, now, counts["yes"], counts["no"], nomination_id), conn=conn,
    )
    if cur.rowcount == 0:
        # Another worker resolved it first. Do nothing else.
        return None

    if outcome == PASS:
        execute(
            """UPDATE community_members SET role = 'VERIFIED_REP', rep_since = ?
               WHERE community_id = ? AND user_id = ? AND status = 'ACTIVE'""",
            (now, ballot["community_id"], ballot["user_id"]), conn=conn,
        )
        # The first verified rep activates a PENDING community (spec 8, 11).
        community_service.activate_community(ballot["community_id"], conn=conn)

    record_change(ballot["community_id"], "rep_nomination", nomination_id,
                  f"NOMINATION_{outcome}",
                  {"status": "OPEN"},
                  {"status": outcome, "reason": reason, **counts},
                  actor_id=None, conn=conn)

    subject = ("A new verified course rep has been confirmed"
               if outcome == PASS else "Rep verification ballot closed")
    body = _ballot_email(ballot, outcome, reason, counts, conn=conn)
    notification_service.notify_community(
        ballot["community_id"], subject=subject, body=body,
        dedupe_key=f"nomination:{nomination_id}:{outcome}",
        conn=conn,
        **notification_copy.course_reps(
            "New course rep confirmed" if outcome == PASS else "Course rep election closed",
            body),
    )
    return {"status": outcome, "reason": reason, **counts}


def _ballot_email(ballot, outcome, reason, counts, conn=None):
    candidate = query_one("SELECT full_name FROM users WHERE id = ?", (ballot["user_id"],), conn=conn)
    name = candidate["full_name"] if candidate else "The candidate"
    if outcome == PASS:
        return (f"{name} has been verified as a course rep for your community.\n\n"
                f"Final votes: {counts['yes']} yes, {counts['no']} no.")
    reasons = {
        "not_enough_votes": "the ballot did not reach the minimum number of votes",
        "tie": "the vote was tied",
        "majority_no": "a majority voted no",
        "no_rep_vacancy": "there is no remaining rep vacancy",
        "candidate_no_longer_eligible": "the candidate is no longer an eligible member",
        "community_archived": "the academic session was archived before the ballot closed",
    }
    return (f"The rep verification ballot for {name} did not pass because "
            f"{reasons.get(reason, reason)}.\n\n"
            f"Final votes: {counts['yes']} yes, {counts['no']} no.")


def close_expired_ballots(conn=None):
    """Close every ballot whose window has elapsed. Used by the worker."""
    due = query_all(
        "SELECT id FROM rep_nominations WHERE status = 'OPEN' AND closes_at <= ?",
        (clock.now_iso(),), conn=conn,
    )
    resolved = []
    for row in due:
        outcome = close_ballot(row["id"], conn=conn)
        if outcome is not None:
            resolved.append((row["id"], outcome))
    return resolved
