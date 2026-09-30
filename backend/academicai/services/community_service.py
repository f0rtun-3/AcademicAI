"""Academic communities (spec 4, 7, 8).

A community is uniquely identified by university + department + level + session.
New communities start PENDING and become ACTIVE when their first rep is verified.
"""
from .. import clock
from ..db.connection import execute, insert_returning_id, query_all, query_one, transaction
from ..errors import NotFoundError, ValidationError


def find_community(university_id, department, level, academic_session, conn=None):
    return query_one(
        """SELECT * FROM academic_communities
           WHERE university_id = ? AND department = ? AND level = ? AND academic_session = ?""",
        (university_id, department, level, academic_session), conn=conn,
    )


def find_for_user(user, conn=None):
    """The community matching the student's declared academic profile."""
    if user["university_id"] is None:
        return None
    return find_community(user["university_id"], user["department"], user["level"],
                          user["academic_session"], conn=conn)


def get_community(community_id, conn=None):
    row = query_one("SELECT * FROM academic_communities WHERE id = ?", (community_id,), conn=conn)
    if row is None:
        raise NotFoundError("Academic community not found.")
    return row


def create_community(university_id, department, level, academic_session, conn=None):
    """Create a PENDING community. It has no rep and no authority until a ballot
    resolves in favour of a candidate (spec 8, 11)."""
    now = clock.now_iso()
    community_id = insert_returning_id(
        """INSERT INTO academic_communities
           (university_id, department, level, academic_session, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'PENDING', ?, ?)""",
        (university_id, department, level, academic_session, now, now), conn=conn,
    )
    return query_one("SELECT * FROM academic_communities WHERE id = ?", (community_id,), conn=conn)


def ensure_community_for_user(user_id):
    """Community determination step of onboarding (spec 7).

    Returns (community_row, created_flag). Creating a community grants nothing
    on its own; membership is handled separately.
    """
    with transaction() as conn:
        user = query_one("SELECT * FROM users WHERE id = ?", (user_id,), conn=conn)
        if user is None:
            raise NotFoundError("Account not found.")
        if not all([user["university_id"], user["department"], user["level"],
                    user["academic_session"]]):
            raise ValidationError("Your academic profile is incomplete.")
        existing = find_for_user(user, conn=conn)
        if existing is not None:
            return existing, False
        created = create_community(user["university_id"], user["department"],
                                   user["level"], user["academic_session"], conn=conn)
        return created, True


def activate_community(community_id, conn=None):
    """PENDING -> ACTIVE. Called when the first rep is verified (spec 8, 11)."""
    execute(
        """UPDATE academic_communities SET status = 'ACTIVE', updated_at = ?
           WHERE id = ? AND status = 'PENDING'""",
        (clock.now_iso(), community_id), conn=conn,
    )


def archive_community(community_id, conn=None):
    execute("UPDATE academic_communities SET status = 'ARCHIVED', updated_at = ? WHERE id = ?",
            (clock.now_iso(), community_id), conn=conn)


def eligible_electorate(community_id, conn=None):
    """Active, email-verified members - the voters for any ballot in this
    community (spec 11, 12).

    The ballot RULES are untouched by the removal of ID-card verification: the
    24h window, the three-actual-vote minimum, YES>NO, the tie failing, the
    rep cap and the cooldowns all still apply to whoever this returns.
    """
    return query_all(
        """SELECT u.* FROM community_members cm
           JOIN users u ON u.id = cm.user_id
           WHERE cm.community_id = ? AND cm.status = 'ACTIVE'
             AND u.email_verified = 1""",
        (community_id,), conn=conn,
    )


def current_reps(community_id, conn=None):
    return query_all(
        """SELECT u.id, u.full_name, u.email, cm.rep_since
           FROM community_members cm JOIN users u ON u.id = cm.user_id
           WHERE cm.community_id = ? AND cm.status = 'ACTIVE' AND cm.role = 'VERIFIED_REP'
           ORDER BY cm.rep_since""",
        (community_id,), conn=conn,
    )


def member_count(community_id, conn=None):
    row = query_one(
        "SELECT COUNT(*) AS n FROM community_members WHERE community_id = ? AND status = 'ACTIVE'",
        (community_id,), conn=conn,
    )
    return row["n"] if row else 0


def election_readiness(community_id, viewer_id=None, conn=None):
    """Whether a rep election can actually be opened here (spec 8, 11).

    A candidate cannot vote for themselves and a ballot needs BALLOT_MIN_VOTES
    actual votes, so the community needs that many eligible voters besides the
    candidate. The UI uses this to explain the requirement up front instead of
    surfacing a 409 when someone tries to stand.

    EVERY FIELD HERE IS INFORMATIONAL. Nothing in this dict authorizes anything.
    nominate() re-derives all of it inside its own transaction and refuses on
    its own findings, so a stale, missing or tampered-with value can only
    mis-draw a screen. The client is required to submit regardless of what this
    says and to render the backend's refusal.

    `viewer_id` adds `cooldown_until` for that one person: when they may
    next stand here, or None if now. Read-only, self-only, and omitted entirely
    when no viewer is supplied - it is never returned for anybody else, because
    when a named classmate last failed a ballot is not this caller's business.
    """
    from flask import current_app

    from . import rep_service

    min_votes = current_app.config["BALLOT_MIN_VOTES"]
    preparation = current_app.config["MIN_ELECTION_PREPARATION"]
    eligible = len(eligible_electorate(community_id, conn=conn))
    required = min_votes + 1
    readiness = {
        "eligible_members": eligible,
        "required_members": required,
        "preparation_threshold": preparation,
        "in_preparation": eligible >= preparation,
        "can_start_election": eligible >= required,
        "members_needed": max(0, required - eligible),
    }
    if viewer_id is not None:
        readiness["cooldown_until"] = rep_service.candidate_cooldown_until(
            community_id, viewer_id, conn=conn)
    return readiness


def community_payload(community, viewer_id=None, conn=None):
    university = query_one("SELECT name, timezone FROM universities WHERE id = ?",
                           (community["university_id"],), conn=conn)
    return {
        "id": community["id"],
        "university": university["name"] if university else None,
        # The community's academic clock: every date and time it shows is
        # read in this IANA zone (academic_time.py).
        "timezone": university["timezone"] if university else None,
        "department": community["department"],
        "level": community["level"],
        "academic_session": community["academic_session"],
        "status": community["status"],
        "member_count": member_count(community["id"], conn=conn),
        "election": election_readiness(community["id"], viewer_id=viewer_id, conn=conn),
        "reps": [
            {"id": r["id"], "full_name": r["full_name"], "rep_since": r["rep_since"]}
            for r in current_reps(community["id"], conn=conn)
        ],
    }


def recent_changes(community_id, limit=50, conn=None):
    """Newest first, with the SUBJECT each row is about.

    A change row stores only what changed - a deadline change holds two dates
    and nothing else - so "The deadline was updated" would not say whose
    deadline. The subject columns name the current record the row points at
    (an event, a class, an announcement or a course), which is what lets the
    interface say "The deadline for COS202 Quiz was updated".
    """
    return query_all(
        """SELECT ch.*, u.full_name AS actor_name,
                  COALESCE(e.title, t.title, a.title, c.title) AS subject_title,
                  COALESCE(ec.code, tc.code, c.code) AS subject_course_code,
                  e.event_type AS subject_event_type
           FROM change_history ch
           LEFT JOIN users u ON u.id = ch.actor_id
           LEFT JOIN academic_events e
                  ON ch.entity_type = 'academic_event' AND e.id = ch.entity_id
           LEFT JOIN courses ec ON ec.id = e.course_id
           LEFT JOIN timetable_entries t
                  ON ch.entity_type = 'timetable_entry' AND t.id = ch.entity_id
           LEFT JOIN courses tc ON tc.id = t.course_id
           LEFT JOIN announcements a
                  ON ch.entity_type = 'announcement' AND a.id = ch.entity_id
           LEFT JOIN courses c ON ch.entity_type = 'course' AND c.id = ch.entity_id
           WHERE ch.community_id = ?
           ORDER BY ch.id DESC LIMIT ?""",
        (community_id, limit), conn=conn,
    )
