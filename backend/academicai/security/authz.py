"""Authorization gates (spec 6, 25).

Account verification, community membership and rep authority are SEPARATE
gates and are never collapsed into a single "is authorized" helper. A caller
must state which gate it needs:

    @require_auth                -> authenticated account
    @require_email_verified      -> institutional email confirmed
    @require_member              -> ACTIVE membership of a community
    @require_rep                 -> VERIFIED_REP in that same community

The account-level evidence that a caller studies at a university is exactly
one thing: control of an address on that university's approved domain
(services/email_domain_service.py, "Gate 1"). Nothing here reads the legacy
users.identity_status. @require_member builds on @require_email_verified, not
@require_auth, so membership always implies a confirmed address.

Every gate reads live database state on each request. Nothing about authority
is carried in the session token, so a revoked or transferred rep loses
authority immediately (spec 25).
"""
from functools import wraps

from flask import g, request

from ..db.connection import query_one
from ..errors import AuthenticationError, AuthorizationError
from ..services import auth_service


def _bearer_token():
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return None


def load_current_user():
    """Populate g.current_user from the request token. Never raises."""
    if "current_user" in g:
        return g.current_user
    g.current_user = auth_service.resolve_session(_bearer_token())
    return g.current_user


def current_user():
    return load_current_user()


def active_membership(user_id, conn=None):
    """The user's single ACTIVE membership, or None.

    The system maintains at most one ACTIVE membership per user; a transfer only
    ends the old one once the destination approves (spec 10).
    """
    return query_one(
        """SELECT cm.*, c.status AS community_status, c.department, c.level,
                  c.academic_session, c.university_id
           FROM community_members cm
           JOIN academic_communities c ON c.id = cm.community_id
           WHERE cm.user_id = ? AND cm.status = 'ACTIVE'
           ORDER BY cm.id LIMIT 1""",
        (user_id,), conn=conn,
    )


def membership_in(user_id, community_id, conn=None):
    return query_one(
        "SELECT * FROM community_members WHERE user_id = ? AND community_id = ?",
        (user_id, community_id), conn=conn,
    )


def is_rep(user_id, community_id, conn=None):
    """Live rep-authority check, scoped to one community (spec 5).

    Requires a verified email as well as the role, so an account whose email
    verification was cleared (a change of address does that) cannot continue to
    exercise rep authority.
    """
    row = query_one(
        """SELECT 1 FROM community_members cm
           JOIN users u ON u.id = cm.user_id
           WHERE cm.user_id = ? AND cm.community_id = ?
             AND cm.status = 'ACTIVE' AND cm.role = 'VERIFIED_REP'
             AND u.email_verified = 1""",
        (user_id, community_id), conn=conn,
    )
    return row is not None


def is_eligible_member(user_id, community_id, conn=None):
    """Active membership of this community plus the account gate passed."""
    row = query_one(
        """SELECT 1 FROM community_members cm
           JOIN users u ON u.id = cm.user_id
           WHERE cm.user_id = ? AND cm.community_id = ? AND cm.status = 'ACTIVE'
             AND u.email_verified = 1""",
        (user_id, community_id), conn=conn,
    )
    return row is not None


def assert_rep(actor_id, community_id, conn=None, action="publish official information"):
    """Re-check rep authority INSIDE the caller's transaction.

    The require_rep decorator reads membership when the request arrives; the
    write happens later, in its own transaction. Between those two moments a
    removal ballot can close, a transfer can complete, or the session can be
    archived, and the decorator's answer goes stale. Calling this at the top of
    a write - inside the same transaction that performs it - closes that
    window, because the state it reads is the state the write commits against
    (spec 12, 23).

    An ARCHIVED community accepts no official writes: the academic session has
    ended, its records are history, and rep authority does not carry into a new
    session. Archiving already demotes every sitting rep, so this is the guard
    for authority acquired some other way - a ballot that was still open when
    the session closed.
    """
    if not is_rep(actor_id, community_id, conn=conn):
        raise AuthorizationError(f"Only a verified course rep can {action}.")

    community = query_one("SELECT status FROM academic_communities WHERE id = ?",
                          (community_id,), conn=conn)
    if community is None:
        raise AuthorizationError("Academic community not found.")
    if community["status"] == "ARCHIVED":
        raise AuthorizationError(
            "This academic session has been archived and no longer accepts changes.",
            details={"community_status": "ARCHIVED"},
        )


def assert_email_verified(user):
    """The account-level gate, assertable inside a transaction.

    The decorator form reads the user when the request arrives; a write that
    happens later re-checks here against the row its own transaction sees.
    """
    if not user["email_verified"]:
        raise AuthorizationError("Email verification is required.")


def assert_same_community(membership, community_id):
    """Community isolation: refuse any cross-community read or write (spec 4)."""
    if membership is None or int(membership["community_id"]) != int(community_id):
        raise AuthorizationError("You do not have access to this academic community.")


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = load_current_user()
        if user is None:
            raise AuthenticationError("Authentication is required.")
        return fn(*args, **kwargs)
    return wrapper


def optional_auth(fn):
    """Populate g.current_user when a valid session is presented, else leave it
    unset. Never refuses.

    For endpoints that behave the same either way but are SAFER with a session:
    email verification uses it so that a signed-in caller is pinned to their own
    account and cannot name another one in the request body.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        load_current_user()
        return fn(*args, **kwargs)
    return wrapper


def require_email_verified(fn):
    @wraps(fn)
    @require_auth
    def wrapper(*args, **kwargs):
        if not g.current_user["email_verified"]:
            raise AuthorizationError("Email verification is required.")
        return fn(*args, **kwargs)
    return wrapper


def require_member(fn):
    """Requires a verified email AND an ACTIVE membership.

    A student awaiting approval is NOT a member and receives a distinct,
    non-403 signal via the awaiting-approval endpoint so the UI can show the
    right state rather than a bare error (spec 9).

    The email gate is re-checked here as well as at join time, so if an account
    stops being email-verified - which changing the address does - access to
    protected community data stops on the very next request instead of
    surviving until the membership is separately revoked.
    """
    @wraps(fn)
    @require_email_verified
    def wrapper(*args, **kwargs):
        membership = active_membership(g.current_user["id"])
        if membership is None:
            raise AuthorizationError(
                "You are not an active member of an academic community.",
                details={"reason": "no_active_membership"},
            )
        g.membership = membership
        g.community_id = membership["community_id"]
        return fn(*args, **kwargs)
    return wrapper


def require_rep(fn):
    """Rep authority, scoped to the caller's own community. Checked live."""
    @wraps(fn)
    @require_member
    def wrapper(*args, **kwargs):
        if g.membership["role"] != "VERIFIED_REP":
            raise AuthorizationError("Only a verified course rep can do this.")
        return fn(*args, **kwargs)
    return wrapper
