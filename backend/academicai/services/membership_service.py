"""Community membership, approval and transfers (spec 8, 9, 10).

Membership is community-specific and is never implied by account verification.
A student holds at most one ACTIVE membership at a time; during a transfer the
old membership stays ACTIVE until the destination approves, so a rejected
transfer never strands the student.
"""
from .. import clock
from ..db.connection import execute, insert_returning_id, query_all, query_one, transaction
from ..errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from . import auth_service, community_service, email_domain_service
from .change_history import record_change


def _require_eligible(user):
    """The account gate for joining a community.

    MVP SCOPE: student ID-card verification was removed from the product, so a
    confirmed institutional email address is the whole of this check. The
    university-specific part of it is not lost - registration only accepts an
    address on that university's approved domain (email_domain_service,
    "Gate 1") - but it is evidence of controlling an address, not of identity.

    Membership itself is still not granted by this: an existing community
    approves or rejects the request, which is a separate gate below.
    """
    if not user["email_verified"]:
        raise AuthorizationError("Email verification is required before joining a community.")


def active_membership(user_id, conn=None):
    return query_one(
        "SELECT * FROM community_members WHERE user_id = ? AND status = 'ACTIVE' LIMIT 1",
        (user_id,), conn=conn,
    )


def pending_request(user_id, conn=None):
    return query_one(
        """SELECT * FROM community_members
           WHERE user_id = ? AND status = 'PENDING_APPROVAL'
           ORDER BY id DESC LIMIT 1""",
        (user_id,), conn=conn,
    )


def membership_for(user_id, community_id, conn=None):
    return query_one(
        "SELECT * FROM community_members WHERE user_id = ? AND community_id = ?",
        (user_id, community_id), conn=conn,
    )


def join_or_request(user_id, community_id):
    """Join a community, or request membership in one.

    PENDING community: an eligible student joins immediately. This bootstrap
    path exists only so a first rep election is possible at all (spec 8).
    ACTIVE community: the student is queued for rep approval (spec 9).
    """
    with transaction() as conn:
        user = query_one("SELECT * FROM users WHERE id = ?", (user_id,), conn=conn)
        if user is None:
            raise NotFoundError("Account not found.")
        _require_eligible(user)
        community = community_service.get_community(community_id, conn=conn)
        if community["status"] == "ARCHIVED":
            raise ConflictError("That academic community has been archived.")

        existing = membership_for(user_id, community_id, conn=conn)
        if existing is not None:
            if existing["status"] == "ACTIVE":
                raise ConflictError("You are already a member of this community.")
            if existing["status"] == "PENDING_APPROVAL":
                raise ConflictError("Your membership request is already awaiting approval.")

        current = active_membership(user_id, conn=conn)
        if current is not None and current["community_id"] == community_id:
            raise ConflictError("You are already a member of this community.")

        now = clock.now_iso()
        auto_join = community["status"] == "PENDING"
        status = "ACTIVE" if auto_join else "PENDING_APPROVAL"

        if auto_join and current is not None:
            # Joining a PENDING community completes immediately. End the old
            # membership FIRST: the database now enforces at most one ACTIVE
            # membership per user, so the two must never overlap - not even
            # momentarily inside this transaction.
            _end_membership(current, actor_id=user_id, reason="TRANSFER", conn=conn)

        if existing is not None:
            execute(
                """UPDATE community_members
                   SET status = ?, role = 'STUDENT', requested_at = ?, approved_by = NULL,
                       approved_at = ?, ended_at = NULL, rep_since = NULL
                   WHERE id = ?""",
                (status, now, now if auto_join else None, existing["id"]), conn=conn,
            )
            membership_id = existing["id"]
        else:
            membership_id = insert_returning_id(
                """INSERT INTO community_members
                   (community_id, user_id, role, status, requested_at, approved_at)
                   VALUES (?, ?, 'STUDENT', ?, ?, ?)""",
                (community_id, user_id, status, now, now if auto_join else None), conn=conn,
            )

        if auto_join:
            record_change(community_id, "community_member", membership_id, "JOINED",
                          None, {"status": "ACTIVE", "bootstrap": True},
                          actor_id=user_id, conn=conn)

        return query_one("SELECT * FROM community_members WHERE id = ?", (membership_id,), conn=conn)


def request_transfer(user_id, target):
    """Start a transfer to a different community (spec 10).

    The student's existing membership is untouched here; it only ends if and
    when the destination approves.
    """
    with transaction() as conn:
        user = query_one("SELECT * FROM users WHERE id = ?", (user_id,), conn=conn)
        if user is None:
            raise NotFoundError("Account not found.")
        _require_eligible(user)

        university_name = (target.get("university") or "").strip()
        department = (target.get("department") or "").strip()
        level = str(target.get("level") or "").strip()
        academic_session = (target.get("academic_session") or "").strip()
        if not all([university_name, department, level, academic_session]):
            raise ValidationError("University, department, level and academic session are required.")

        # A transfer can change university, so Gate 1 is re-checked here:
        # otherwise a Babcock-verified address could transfer into a Covenant
        # community and sidestep registration's domain rule entirely.
        email_domain_service.assert_domain_matches_university(
            university_name, user["email"], conn=conn)

        university_id = auth_service.registered_university_id(university_name, conn=conn)
        destination = community_service.find_community(
            university_id, department, level, academic_session, conn=conn)
        if destination is None:
            destination = community_service.create_community(
                university_id, department, level, academic_session, conn=conn)

        current = active_membership(user_id, conn=conn)
        if current is not None and current["community_id"] == destination["id"]:
            raise ConflictError("You are already a member of that community.")
    # join_or_request opens its own transaction; the lookup above is committed.
    return join_or_request(user_id, destination["id"]), destination


def pending_requests(community_id, conn=None):
    return query_all(
        """SELECT cm.*, u.full_name, u.email
           FROM community_members cm JOIN users u ON u.id = cm.user_id
           WHERE cm.community_id = ? AND cm.status = 'PENDING_APPROVAL'
           ORDER BY cm.requested_at""",
        (community_id,), conn=conn,
    )


def approve_request(rep_user_id, community_id, target_user_id):
    """Approve a membership request. Approval does NOT make the student a rep;
    the role remains STUDENT (spec 9)."""
    from ..security import authz
    with transaction() as conn:
        community = community_service.get_community(community_id, conn=conn)
        if not authz.is_rep(rep_user_id, community_id, conn=conn):
            raise AuthorizationError("Only a verified course rep can approve membership.")
        if community["status"] != "ACTIVE":
            raise ConflictError("Membership approval applies only to an active community.")

        request_row = membership_for(target_user_id, community_id, conn=conn)
        if request_row is None or request_row["status"] != "PENDING_APPROVAL":
            raise NotFoundError("No pending membership request for that student.")

        target = query_one("SELECT * FROM users WHERE id = ?", (target_user_id,), conn=conn)
        _require_eligible(target)

        now = clock.now_iso()

        # Completing a transfer ends the old membership (spec 10). This runs
        # BEFORE the new membership is activated so the two never coexist.
        previous = query_one(
            """SELECT * FROM community_members
               WHERE user_id = ? AND status = 'ACTIVE' AND community_id != ?""",
            (target_user_id, community_id), conn=conn,
        )
        if previous is not None:
            _end_membership(previous, actor_id=rep_user_id, reason="TRANSFER", conn=conn)

        execute(
            """UPDATE community_members
               SET status = 'ACTIVE', role = 'STUDENT', approved_by = ?, approved_at = ?
               WHERE id = ?""",
            (rep_user_id, now, request_row["id"]), conn=conn,
        )

        record_change(community_id, "community_member", request_row["id"], "MEMBERSHIP_APPROVED",
                      {"status": "PENDING_APPROVAL"}, {"status": "ACTIVE", "role": "STUDENT"},
                      actor_id=rep_user_id, conn=conn)
        return query_one("SELECT * FROM community_members WHERE id = ?",
                         (request_row["id"],), conn=conn)


def reject_request(rep_user_id, community_id, target_user_id, reason=None):
    """Reject a membership request. The student keeps any existing membership,
    so a rejected transfer leaves them where they were (spec 10)."""
    from ..security import authz
    with transaction() as conn:
        if not authz.is_rep(rep_user_id, community_id, conn=conn):
            raise AuthorizationError("Only a verified course rep can reject membership.")
        request_row = membership_for(target_user_id, community_id, conn=conn)
        if request_row is None or request_row["status"] != "PENDING_APPROVAL":
            raise NotFoundError("No pending membership request for that student.")
        execute("UPDATE community_members SET status = 'REJECTED', ended_at = ? WHERE id = ?",
                (clock.now_iso(), request_row["id"]), conn=conn)
        record_change(community_id, "community_member", request_row["id"], "MEMBERSHIP_REJECTED",
                      {"status": "PENDING_APPROVAL"}, {"status": "REJECTED", "reason": reason},
                      actor_id=rep_user_id, conn=conn)
        return query_one("SELECT * FROM community_members WHERE id = ?",
                         (request_row["id"],), conn=conn)


def leave_community(user_id):
    with transaction() as conn:
        membership = active_membership(user_id, conn=conn)
        if membership is None:
            raise NotFoundError("You are not a member of any community.")
        _end_membership(membership, actor_id=user_id, reason="LEFT", conn=conn)
        return True


def _end_membership(membership, actor_id, reason, conn):
    """End a membership and clean up everything scoped to it (spec 10).

    Rep authority is revoked, course enrollments are removed so stale
    notifications stop, and outstanding sessions are invalidated when the member
    held authority that no longer applies.
    """
    was_rep = membership["role"] == "VERIFIED_REP"
    now = clock.now_iso()
    execute(
        """UPDATE community_members
           SET status = 'ENDED', role = 'STUDENT', rep_since = NULL, ended_at = ?
           WHERE id = ?""",
        (now, membership["id"]), conn=conn,
    )
    execute(
        """DELETE FROM course_enrollments
           WHERE user_id = ? AND course_id IN (SELECT id FROM courses WHERE community_id = ?)""",
        (membership["user_id"], membership["community_id"]), conn=conn,
    )
    # Stop queued notifications for a community the student has left.
    execute(
        """UPDATE notifications SET status = 'FAILED', last_error = 'recipient left community'
           WHERE user_id = ? AND community_id = ? AND status = 'PENDING'""",
        (membership["user_id"], membership["community_id"]), conn=conn,
    )
    if was_rep:
        auth_service.revoke_all_sessions(membership["user_id"], conn=conn)
    record_change(membership["community_id"], "community_member", membership["id"],
                  f"MEMBERSHIP_{reason}", {"status": "ACTIVE", "was_rep": was_rep},
                  {"status": "ENDED", "role": "STUDENT"}, actor_id=actor_id, conn=conn)


def membership_payload(membership, conn=None):
    if membership is None:
        return None
    return {
        "id": membership["id"],
        "community_id": membership["community_id"],
        "user_id": membership["user_id"],
        "role": membership["role"],
        "status": membership["status"],
        "requested_at": membership["requested_at"],
        "approved_at": membership["approved_at"],
    }


def members(community_id, conn=None):
    return query_all(
        """SELECT cm.*, u.full_name, u.email
           FROM community_members cm JOIN users u ON u.id = cm.user_id
           WHERE cm.community_id = ? AND cm.status = 'ACTIVE'
           ORDER BY cm.role DESC, u.full_name""",
        (community_id,), conn=conn,
    )
