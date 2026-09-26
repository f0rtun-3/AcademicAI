"""Authentication and account lifecycle (spec 7, 25).

Registration captures the student's declared academic profile but grants no
membership and no authority. Email verification is the account gate that must
pass before community membership is possible, and membership itself is still a
separate decision made by the community.

MVP SCOPE: student ID-card verification has been removed from the product, so
email verification is the ONLY account-level gate. The address must sit on the
selected university's approved institutional domain, which is real evidence of
affiliation - but it is evidence of controlling an address, not of identity,
and nothing here should be described as verifying who the student is.
"""
import re
from contextlib import contextmanager

from .. import clock
from ..db.connection import execute, insert_returning_id, query_one, transaction
from ..errors import (ApiError, AuthenticationError, ConflictError, NotFoundError,
                      RateLimitError, ValidationError)
from ..security.passwords import hash_password, validate_password, verify_password
from ..security.tokens import (codes_equal, generate_code, generate_salt,
                               generate_token, hash_code, hash_token)
from . import email_domain_service

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STUDENT_ID_RE = re.compile(r"^[A-Za-z0-9/\-\s]{4,32}$")


def normalize_email(email):
    if not isinstance(email, str) or not EMAIL_RE.match(email.strip()):
        raise ValidationError("A valid email address is required.")
    return email.strip().lower()


def _require_text(value, field, max_len=200):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} is required.")
    cleaned = value.strip()
    if len(cleaned) > max_len:
        raise ValidationError(f"{field} is too long.")
    return cleaned


def get_or_create_university(name, conn=None):
    name = _require_text(name, "University")
    row = query_one("SELECT * FROM universities WHERE name = ?", (name,), conn=conn)
    if row:
        return row["id"]
    return insert_returning_id(
        "INSERT INTO universities (name, created_at) VALUES (?, ?)",
        (name, clock.now_iso()),
        conn=conn,
    )


@contextmanager
def _about(field):
    """Tag a refusal with the sign-up field it concerns.

    The message is unchanged; `details.field` only tells the form which input
    to put it beside, so the student is not left hunting a long form for the
    one value that was refused.
    """
    try:
        yield
    except ApiError as exc:
        if "field" not in exc.details:
            exc.details = {**exc.details, "field": field}
        raise


def register(data):
    """Create an account.

    Returns (user_row, verification_code). The code is None when the
    deployment has email verification switched off - see the note at the
    INSERT below, and Config.EMAIL_VERIFICATION_REQUIRED.

    Everything else is unconditional: the institutional-domain rule, the
    duplicate check and password hashing all run exactly as before, whichever
    way the switch is set.
    """
    from flask import current_app
    with _about("full_name"):
        full_name = _require_text(data.get("full_name"), "Full name")
    with _about("email"):
        email = normalize_email(data.get("email"))
    with _about("password"):
        validate_password(data.get("password"))
    with _about("confirm_password"):
        validate_password(data.get("password"), data.get("confirm_password"))
    with _about("university"):
        university = _require_text(data.get("university"), "University")
    with _about("department"):
        department = _require_text(data.get("department"), "Department")
    with _about("level"):
        level = _require_text(str(data.get("level") or ""), "Level", max_len=20)
    with _about("academic_session"):
        academic_session = _require_text(data.get("academic_session"), "Academic session",
                                         max_len=40)
    # The student's own declared Matric Number. It is INFORMATIONAL only: it
    # used to be the account-side value an ID card was compared against, and
    # with card verification out of MVP scope nothing checks it. It is still
    # collected because it is part of the student's academic profile, and it is
    # still validated for shape so the record stays clean - but it is not
    # evidence of anything and must never be displayed as verified.
    # The field is named student_id_number in the schema and on the wire; the
    # user-facing word is "Matric Number" everywhere (UI spec C·12).
    with _about("student_id_number"):
        student_id_number = _require_text(data.get("student_id_number"),
                                          "Matric Number", max_len=32)
        if not STUDENT_ID_RE.match(student_id_number):
            # A format check on the student's own entry, not a verification.
            # The old wording ("characters we can't read") implied something
            # was reading the value; nothing does.
            raise ValidationError(
                "Your Matric Number can only contain letters, numbers, spaces, "
                "slashes and hyphens.")

    now = clock.now_iso()
    with transaction() as conn:
        # Gate 1, checked BEFORE any account exists and before any verification
        # email is sent: the address must sit on a domain approved for the
        # selected university. Backend-enforced; the client cannot influence
        # the registry (see services/email_domain_service.py).
        try:
            email_domain_service.assert_domain_matches_university(university, email, conn=conn)
        except ApiError as exc:
            # An unsupported university is about the university; a domain
            # that does not match it is about the address typed.
            unsupported = "supported_universities" in exc.details
            exc.details = {**exc.details, "field": "university" if unsupported else "email"}
            raise

        with _about("email"):
            if query_one("SELECT id FROM users WHERE email = ?", (email,), conn=conn):
                raise ConflictError("An account with that email already exists.")
        university_id = get_or_create_university(university, conn=conn)
        # users.identity_status is a LEGACY column: student ID-card verification
        # is out of MVP scope and nothing reads it any more. It is left in the
        # schema rather than dropped (the migrator can add columns but not
        # remove them, and rebuilding the table on a live database is a risk
        # with no upside), so its NOT NULL DEFAULT supplies the value here.
        # THE ONE PLACE THE VERIFICATION SWITCH ACTS.
        #
        # email_verified is read in nine places, three of them inside SQL that
        # cannot consult configuration ("AND u.email_verified = 1"). Making the
        # GATES conditional would mean changing all nine and still leaving
        # those three unreachable. Deciding the initial STATE here instead
        # leaves every gate, every query and the whole OTP implementation
        # exactly as they are - the flow is simply not started.
        verification_required = current_app.config["EMAIL_VERIFICATION_REQUIRED"]
        verified = 0 if verification_required else 1
        # Recorded so that "verified" never quietly means two different things.
        method = "OTP" if verification_required else "SKIPPED_NO_VERIFICATION"

        user_id = insert_returning_id(
            """INSERT INTO users
               (full_name, email, password_hash, email_verified,
                email_verification_method,
                university_id, department, level, academic_session,
                student_id_number, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (full_name, email, hash_password(data["password"]), verified, method,
             university_id, department, level, academic_session,
             student_id_number, now, now),
            conn=conn,
        )
        # No code is minted when none will be asked for. A code sitting unused
        # in the database is a credential nobody is watching.
        token = _issue_email_token(user_id, conn=conn) if verification_required else None
        user = query_one("SELECT * FROM users WHERE id = ?", (user_id,), conn=conn)
    return user, token


def _issue_email_token(user_id, conn=None):
    """Mint a fresh six-digit verification code for one account.

    ISSUING A CODE DESTROYS EVERY EARLIER ONE. Without that, "send me another
    one" would widen the guessable set with each press instead of replacing it,
    and a code the user abandoned would stay live for its full lifetime. The
    newest code is the only code.

    Returns the plaintext code. It is never stored and cannot be recovered from
    the database - see security/tokens.hash_code.
    """
    from flask import current_app
    now = clock.now_iso()

    # Spend the outstanding ones first, in the SAME transaction as the insert:
    # a reader can never observe two live codes for one account.
    execute(
        """UPDATE email_verification_tokens SET used_at = ?
           WHERE user_id = ? AND used_at IS NULL""",
        (now, user_id), conn=conn,
    )

    code = generate_code(current_app.config["OTP_LENGTH"])
    salt = generate_salt()
    ttl = current_app.config["OTP_TTL_MINUTES"]
    execute(
        """INSERT INTO email_verification_tokens
           (user_id, token_hash, code_salt, attempts, expires_at, created_at)
           VALUES (?, ?, ?, 0, ?, ?)""",
        (user_id, hash_code(code, salt, user_id, current_app.config["SECRET_KEY"]),
         salt, clock.to_iso(clock.now() + clock.minutes(ttl)), now),
        conn=conn,
    )
    return code


def find_by_email(email, conn=None):
    """Look up an account by address, tolerating a malformed one.

    Returns None rather than raising for a bad address: the callers that use
    this must answer identically whether the account is missing or the input
    was nonsense, so neither can be used to probe for registered addresses.
    """
    try:
        email = normalize_email(email)
    except ValidationError:
        return None
    return query_one("SELECT * FROM users WHERE email = ?", (email,), conn=conn)


def active_code_row(user_id, conn=None):
    """The one live code for an account, or None. Newest first, defensively."""
    return query_one(
        """SELECT * FROM email_verification_tokens
           WHERE user_id = ? AND used_at IS NULL
           ORDER BY id DESC LIMIT 1""",
        (user_id,), conn=conn,
    )


def seconds_until_resend_allowed(user_id, conn=None):
    """How long the account must wait before another code may be sent.

    The cooldown is measured from the last code ISSUED rather than from the
    last request, so a burst of requests cannot walk the window forward.
    """
    from flask import current_app
    row = query_one(
        """SELECT created_at FROM email_verification_tokens
           WHERE user_id = ? ORDER BY id DESC LIMIT 1""",
        (user_id,), conn=conn,
    )
    if row is None:
        return 0
    cooldown = current_app.config["OTP_RESEND_COOLDOWN_SECONDS"]
    elapsed = (clock.now() - clock.parse_iso(row["created_at"])).total_seconds()
    return max(0, int(round(cooldown - elapsed)))


def resend_email_verification(user_id):
    with transaction() as conn:
        user = query_one("SELECT * FROM users WHERE id = ?", (user_id,), conn=conn)
        if user is None:
            raise NotFoundError("Account not found.")
        if user["email_verified"]:
            raise ConflictError("Email is already verified.")
        wait = seconds_until_resend_allowed(user_id, conn=conn)
        if wait > 0:
            # A cooldown, not a rate limit: the caller is told exactly how long,
            # because the screen shows a countdown and a vague refusal would
            # leave it guessing.
            raise RateLimitError(
                f"Please wait {wait} seconds before requesting another code.",
                details={"retry_after_seconds": wait},
            )
        return _issue_email_token(user_id, conn=conn)


def verify_email(user_id, code):
    """Check a six-digit code against the one live code for `user_id`.

    WHY THIS TAKES A user_id
    ------------------------
    The old link token was 256 bits and globally unique, so it identified the
    account by itself. Six digits cannot: a code looked up globally would be
    one of a million values shared across every account on the system, and
    guessing it would verify SOMEBODY. Scoping the lookup to one account is
    what keeps the search space per-account, and it is what the attempt ceiling
    and the per-account rate limit are counted against.

    The address is never a parameter. A code verifies the address already on
    the account and nothing else, so there is no way to point verification at
    a different mailbox.
    """
    from flask import current_app
    if not isinstance(code, str) or not code.strip():
        raise ValidationError("Enter the 6-digit code from your email.")
    code = code.strip().replace(" ", "")

    # DELIBERATELY NOT ONE TRANSACTION.
    #
    # Recording a wrong guess and then raising inside a single transaction
    # rolls the counter back with the exception - which silently removed the
    # attempt ceiling entirely, leaving a six-digit code with unlimited tries.
    # A failed attempt is a fact that must survive the refusal, so each write
    # commits on its own and the rejection is raised afterwards.
    user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if user is None:
        raise NotFoundError("Account not found.")

    row = active_code_row(user_id)
    if row is None:
        raise ValidationError(
            "That code is no longer valid. Request a new one.",
            details={"reason": "no_active_code"})

    def spend(row_id):
        with transaction() as conn:
            execute("UPDATE email_verification_tokens SET used_at = ? WHERE id = ?",
                    (clock.now_iso(), row_id), conn=conn)

    if clock.parse_iso(row["expires_at"]) < clock.now():
        spend(row["id"])   # an expired code cannot be retried into existence
        raise ValidationError("That code has expired. Request a new one.",
                              details={"reason": "expired"})

    max_attempts = current_app.config["OTP_MAX_ATTEMPTS"]
    if row["attempts"] >= max_attempts:
        spend(row["id"])
        raise ValidationError("Too many incorrect attempts. Request a new code.",
                              details={"reason": "too_many_attempts"})

    # A legacy row from before codes existed has no salt. It cannot be verified
    # as a code and must not be treated as one.
    expected = None
    if row["code_salt"]:
        expected = hash_code(code, row["code_salt"], user_id,
                             current_app.config["SECRET_KEY"])

    if expected is None or not codes_equal(expected, row["token_hash"]):
        attempts = row["attempts"] + 1
        exhausted = attempts >= max_attempts
        with transaction() as conn:
            execute(
                """UPDATE email_verification_tokens
                   SET attempts = ?, used_at = ? WHERE id = ?""",
                (attempts, clock.now_iso() if exhausted else None, row["id"]),
                conn=conn,
            )
        raise ValidationError(
            "Too many incorrect attempts. Request a new code." if exhausted
            else "That code is not correct.",
            details={"reason": "too_many_attempts" if exhausted else "incorrect",
                     "attempts_remaining": max(0, max_attempts - attempts)},
        )

    # Correct. Spending the code and verifying the account are one transaction,
    # and the UPDATE is conditional on the code still being unused so that two
    # simultaneous submissions cannot both succeed.
    with transaction() as conn:
        now = clock.now_iso()
        cursor = execute(
            """UPDATE email_verification_tokens SET used_at = ?
               WHERE id = ? AND used_at IS NULL""",
            (now, row["id"]), conn=conn,
        )
        if cursor.rowcount != 1:
            raise ValidationError("That code is no longer valid. Request a new one.",
                                  details={"reason": "no_active_code"})
        execute("UPDATE users SET email_verified = 1, updated_at = ? WHERE id = ?",
                (now, user_id), conn=conn)
        return query_one("SELECT * FROM users WHERE id = ?", (user_id,), conn=conn)


def login(email, password):
    """Returns (user_row, session_token). Failure messages never reveal which
    half was wrong, and never reveal whether an account exists."""
    from flask import current_app
    try:
        email = normalize_email(email)
    except ValidationError:
        raise AuthenticationError("Invalid email or password.")
    user = query_one("SELECT * FROM users WHERE email = ?", (email,))
    if user is None or not verify_password(user["password_hash"], password or ""):
        raise AuthenticationError("Invalid email or password.")

    token = generate_token()
    ttl = current_app.config["SESSION_TTL_HOURS"]
    with transaction() as conn:
        execute(
            """INSERT INTO sessions (user_id, token_hash, token_epoch, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user["id"], hash_token(token), user["token_epoch"], clock.now_iso(),
             clock.to_iso(clock.now() + clock.hours(ttl))),
            conn=conn,
        )
    return user, token


def resolve_session(token):
    """Return the user for a session token, or None.

    Checks expiry, explicit revocation, and the token epoch. Bumping a user's
    epoch invalidates every outstanding session for that user, which is how rep
    authority changes and transfers force re-authentication (spec 10).
    """
    if not token:
        return None
    row = query_one(
        """SELECT s.*, u.token_epoch AS current_epoch
           FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ?""",
        (hash_token(token),),
    )
    if row is None or row["revoked_at"] is not None:
        return None
    if clock.parse_iso(row["expires_at"]) < clock.now():
        return None
    if row["token_epoch"] != row["current_epoch"]:
        return None
    return query_one("SELECT * FROM users WHERE id = ?", (row["user_id"],))


def logout(token):
    if not token:
        return
    with transaction() as conn:
        execute("UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (clock.now_iso(), hash_token(token)), conn=conn)


def revoke_all_sessions(user_id, conn=None):
    """Invalidate every session for a user by advancing the token epoch."""
    execute("UPDATE users SET token_epoch = token_epoch + 1, updated_at = ? WHERE id = ?",
            (clock.now_iso(), user_id), conn=conn)


def request_password_reset(email):
    """Always succeeds from the caller's perspective; returns a token only when
    the account exists, so the endpoint cannot be used to enumerate accounts."""
    from flask import current_app
    try:
        email = normalize_email(email)
    except ValidationError:
        return None
    user = query_one("SELECT * FROM users WHERE email = ?", (email,))
    if user is None:
        return None
    token = generate_token()
    ttl = current_app.config["RESET_TOKEN_TTL_HOURS"]
    with transaction() as conn:
        execute(
            """INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, created_at)
               VALUES (?, ?, ?, ?)""",
            (user["id"], hash_token(token),
             clock.to_iso(clock.now() + clock.hours(ttl)), clock.now_iso()),
            conn=conn,
        )
    return token


def reset_password(token, new_password, confirm_password=None):
    validate_password(new_password, confirm_password)
    with transaction() as conn:
        row = query_one("SELECT * FROM password_reset_tokens WHERE token_hash = ?",
                        (hash_token(token or ""),), conn=conn)
        if row is None or row["used_at"] is not None:
            raise ValidationError("Invalid or expired reset link.")
        if clock.parse_iso(row["expires_at"]) < clock.now():
            raise ValidationError("Invalid or expired reset link.")
        now = clock.now_iso()
        execute("UPDATE password_reset_tokens SET used_at = ? WHERE id = ?", (now, row["id"]), conn=conn)
        execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (hash_password(new_password), now, row["user_id"]), conn=conn)
        # A password reset invalidates existing sessions.
        revoke_all_sessions(row["user_id"], conn=conn)
        return query_one("SELECT * FROM users WHERE id = ?", (row["user_id"],), conn=conn)


def change_email(user_id, new_email):
    """Change an account's email address, re-running Gate 1 and resetting
    verification.

    There is no HTTP route for this today; it exists so that the invariant
    lives with the data rather than with whichever endpoint is added later.
    An email change:

      * must pass institutional-domain validation for the account's university
      * always clears email_verified
      * invalidates outstanding verification tokens and every session

    A verified institutional email can therefore never be traded for a
    personal address while keeping email_verified = 1.
    """
    email = normalize_email(new_email)
    now = clock.now_iso()
    with transaction() as conn:
        user = query_one("SELECT * FROM users WHERE id = ?", (user_id,), conn=conn)
        if user is None:
            raise NotFoundError("Account not found.")

        university = query_one("SELECT name FROM universities WHERE id = ?",
                               (user["university_id"],), conn=conn)
        email_domain_service.assert_domain_matches_university(
            university["name"] if university else None, email, conn=conn)

        if email != user["email"] and query_one(
                "SELECT id FROM users WHERE email = ?", (email,), conn=conn):
            raise ConflictError("An account with that email already exists.")

        execute(
            """UPDATE users SET email = ?, email_verified = 0, updated_at = ?
               WHERE id = ?""",
            (email, now, user_id), conn=conn,
        )
        # Outstanding links for the old address must not verify the new one.
        execute(
            """UPDATE email_verification_tokens SET used_at = ?
               WHERE user_id = ? AND used_at IS NULL""",
            (now, user_id), conn=conn,
        )
        revoke_all_sessions(user_id, conn=conn)
        token = _issue_email_token(user_id, conn=conn)
        return query_one("SELECT * FROM users WHERE id = ?", (user_id,), conn=conn), token


def public_user(user):
    """Profile projection. Never exposes the password hash (spec 25).

    `identity_status` is deliberately NOT projected. The column still exists as
    legacy schema, but student ID-card verification is out of MVP scope, so
    reporting a status the product no longer establishes would be a false
    claim - and a client could easily mistake it for a permission.

    `student_id_number` remains: the student typed it at registration and it is
    their own profile data. It is now purely informational - nothing compares
    it against anything - so it must never be presented as verified.
    """
    if user is None:
        return None
    return {
        "id": user["id"],
        "full_name": user["full_name"],
        "email": user["email"],
        "email_verified": bool(user["email_verified"]),
        "university_id": user["university_id"],
        "department": user["department"],
        "level": user["level"],
        "academic_session": user["academic_session"],
        "student_id_number": user["student_id_number"],
    }
