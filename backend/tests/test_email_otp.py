"""Email verification by six-digit code.

WHY THIS FILE EXISTS SEPARATELY from test_auth.py: the account gate was a
256-bit link token, and moving it to six digits changed what makes it safe. A
long token is safe because it cannot be guessed. A six-digit code is safe only
because of the rules below, all of which must hold at once:

    it dies after ten minutes
    it dies after a handful of wrong guesses
    it dies when a newer code is issued
    it dies when it is used
    it is stored so a database read cannot recover it
    it is scoped to one account, so the search space is not shared

Remove any one of them and six digits is not enough. Each has a test here, and
each test says which rule it is holding up.
"""
from datetime import timedelta

import pytest

from academicai import clock
from academicai.db.connection import query_all, query_one
from academicai.services import email_service
from academicai.services.auth_service import TERMS_VERSION  # noqa: E402
# What the sign-up form sends when its Terms box is ticked.
TERMS_ACCEPTED = {"accept_terms": True, "terms_version": TERMS_VERSION}


def register_account(client, register):
    email_service.clear()
    return register(client)


def verify(client, actor, code):
    return client.post("/api/auth/verify-email",
                       json={"email": actor.email, "code": code})


def wrong_code(actual):
    """A code that is definitely not the right one, same shape."""
    return "000000" if actual != "000000" else "111111"


# ── Registration issues a code ─────────────────────────────────────────────

def test_registration_creates_an_unverified_account(client, register):
    actor = register_account(client, register)
    row = None
    resp = client.post("/api/auth/login",
                       json={"email": actor.email, "password": "Password123"})
    assert resp.status_code == 200
    assert resp.get_json()["user"]["email_verified"] is False
    assert row is None


def test_registration_generates_a_six_digit_code(client, register):
    actor = register_account(client, register)
    assert actor.otp.isdigit()
    assert len(actor.otp) == 6


def test_the_code_is_emailed_to_the_address_that_registered(client, register):
    actor = register_account(client, register)
    messages = [m for m in email_service.sent_messages() if m["to"] == actor.email]
    assert len(messages) == 1, "exactly one verification email, to the account's address"
    message = messages[0]
    # The code is in the message the student actually receives - both parts.
    assert actor.otp in message["body"]
    assert actor.otp in (message["html"] or "")
    assert "expires in 10 minutes" in message["body"]
    # And nobody else was mailed.
    assert {m["to"] for m in email_service.sent_messages()} == {actor.email}


def test_the_email_reads_like_a_verification_email(client, register):
    actor = register_account(client, register)
    message = email_service.sent_messages()[0]
    assert actor.otp in message["subject"], "the code is previewable in the subject"
    for phrase in ("AcademicAI", "Verify your email",
                   "did not create", "Do not share this code"):
        assert phrase in message["body"], phrase


# ── The happy path ─────────────────────────────────────────────────────────

def test_the_correct_code_verifies_the_account(client, register):
    actor = register_account(client, register)
    resp = verify(client, actor, actor.otp)
    assert resp.status_code == 200
    assert resp.get_json()["user"]["email_verified"] is True
    assert resp.get_json()["next_step"] == "community_setup"


def test_a_verified_user_can_log_in_and_proceed(client, register):
    actor = register_account(client, register)
    assert verify(client, actor, actor.otp).status_code == 200
    resp = client.post("/api/auth/login",
                       json={"email": actor.email, "password": "Password123"})
    assert resp.status_code == 200
    assert resp.get_json()["user"]["email_verified"] is True
    actor.token = resp.get_json()["token"]
    # Past the gate: onboarding moves on instead of sending them back.
    assert actor.get("/api/auth/me").get_json()["next_step"] == "community_setup"


def test_spaces_in_a_pasted_code_are_tolerated(client, register):
    """People paste "482 917" from a mail client that broke the run."""
    actor = register_account(client, register)
    spaced = f"{actor.otp[:3]} {actor.otp[3:]}"
    assert verify(client, actor, spaced).status_code == 200


# ── The rules that make six digits safe ────────────────────────────────────

def test_an_incorrect_code_fails(client, register):
    actor = register_account(client, register)
    resp = verify(client, actor, wrong_code(actor.otp))
    assert resp.status_code == 400
    assert resp.get_json()["details"]["reason"] == "incorrect"
    # And the account is untouched.
    assert client.post("/api/auth/login",
                       json={"email": actor.email, "password": "Password123"}
                       ).get_json()["user"]["email_verified"] is False


def test_an_expired_code_fails(client, register):
    actor = register_account(client, register)
    clock.advance(timedelta(minutes=10, seconds=1))
    resp = verify(client, actor, actor.otp)
    assert resp.status_code == 400
    assert resp.get_json()["details"]["reason"] == "expired"


def test_a_code_is_still_valid_just_before_it_expires(client, register):
    """The boundary in the useful direction, so the TTL is not accidentally zero."""
    actor = register_account(client, register)
    clock.advance(timedelta(minutes=9, seconds=30))
    assert verify(client, actor, actor.otp).status_code == 200


def test_a_used_code_cannot_be_used_again(client, register):
    actor = register_account(client, register)
    assert verify(client, actor, actor.otp).status_code == 200
    assert verify(client, actor, actor.otp).status_code == 400


def test_issuing_a_new_code_invalidates_the_previous_one(client, register, app):
    actor = register_account(client, register)
    actor.relogin()
    clock.advance(timedelta(seconds=61))          # past the resend cooldown
    fresh = actor.post("/api/auth/resend-verification").get_json()["verification_code"]
    assert fresh != actor.otp

    assert verify(client, actor, actor.otp).status_code == 400, "the old code must be dead"
    assert verify(client, actor, fresh).status_code == 200

    with app.app_context():
        live = query_all(
            """SELECT id FROM email_verification_tokens
               WHERE user_id = ? AND used_at IS NULL""", (actor.user_id,))
    assert live == [], "no code outlives its replacement"


def test_wrong_guesses_are_capped_and_burn_the_code(client, register):
    """The attempt ceiling is the whole reason six digits is defensible.

    Five wrong guesses out of a million is not a meaningful search - but only
    because the sixth is refused even if it happens to be right.
    """
    actor = register_account(client, register)
    for _ in range(5):
        assert verify(client, actor, wrong_code(actor.otp)).status_code == 400

    resp = verify(client, actor, actor.otp)
    assert resp.status_code == 400, "the correct code must not work after the ceiling"
    assert resp.get_json()["details"]["reason"] in ("too_many_attempts", "no_active_code")


def test_the_response_counts_down_remaining_attempts(client, register):
    actor = register_account(client, register)
    first = verify(client, actor, wrong_code(actor.otp)).get_json()
    second = verify(client, actor, wrong_code(actor.otp)).get_json()
    assert first["details"]["attempts_remaining"] == 4
    assert second["details"]["attempts_remaining"] == 3


def test_resend_is_rate_limited_by_a_cooldown(client, register):
    actor = register_account(client, register)
    actor.relogin()
    # Registration issued one moments ago, so another is refused.
    resp = actor.post("/api/auth/resend-verification")
    assert resp.status_code == 429
    assert resp.get_json()["details"]["retry_after_seconds"] > 0

    clock.advance(timedelta(seconds=61))
    assert actor.post("/api/auth/resend-verification").status_code == 200


def test_the_code_is_not_stored_in_plaintext(client, register, app):
    """A database read must not yield a working code.

    Checked against the stored row rather than by inspecting the hashing
    helper: the property that matters is what is on disk.
    """
    actor = register_account(client, register)
    with app.app_context():
        row = query_one(
            """SELECT * FROM email_verification_tokens
               WHERE user_id = ? ORDER BY id DESC LIMIT 1""", (actor.user_id,))
    stored = " ".join(str(v) for v in dict(row).values())
    assert actor.otp not in stored, "the code itself must not appear in the row"

    # Nor is it a bare digest anybody can reverse by hashing a million values:
    # without SECRET_KEY the digest cannot be reproduced.
    import hashlib
    assert hashlib.sha256(actor.otp.encode()).hexdigest() != row["token_hash"]
    assert row["code_salt"], "each row is salted, so equal codes store differently"


def test_two_accounts_with_the_same_code_store_different_digests(client, register, app):
    """Otherwise a digest would reveal that two people hold the same code."""
    from flask import current_app
    from academicai.security.tokens import hash_code
    a = register(client)
    b = register(client)
    with app.app_context():
        secret = current_app.config["SECRET_KEY"]
        rows = {}
        for actor in (a, b):
            rows[actor.user_id] = query_one(
                """SELECT * FROM email_verification_tokens
                   WHERE user_id = ? ORDER BY id DESC LIMIT 1""", (actor.user_id,))
        # Force the same plaintext code through both rows' salts.
        digest_a = hash_code("123456", rows[a.user_id]["code_salt"], a.user_id, secret)
        digest_b = hash_code("123456", rows[b.user_id]["code_salt"], b.user_id, secret)
    assert digest_a != digest_b


# ── Whose code, and which address ──────────────────────────────────────────

def test_one_accounts_code_cannot_verify_another_account(client, register):
    """A six-digit code is only safe because it is scoped to one account."""
    mine = register(client)
    theirs = register(client)
    resp = client.post("/api/auth/verify-email",
                       json={"email": theirs.email, "code": mine.otp})
    assert resp.status_code == 400
    assert client.post("/api/auth/login",
                       json={"email": theirs.email, "password": "Password123"}
                       ).get_json()["user"]["email_verified"] is False


def test_a_signed_in_caller_cannot_name_another_account(client, register):
    """The session wins over the body, so a verified session cannot be pointed
    at somebody else's pending account."""
    mine = register(client)
    theirs = register(client)
    mine.relogin()
    # Signed in as `mine`, but asking to verify `theirs` with their own code.
    resp = mine.post("/api/auth/verify-email",
                     json={"email": theirs.email, "code": theirs.otp})
    assert resp.status_code == 400, "the body's address must be ignored"
    assert client.post("/api/auth/login",
                       json={"email": theirs.email, "password": "Password123"}
                       ).get_json()["user"]["email_verified"] is False


def test_an_unknown_address_answers_like_a_wrong_code(client, register):
    """So the endpoint cannot be used to discover who has an account."""
    actor = register_account(client, register)
    unknown = client.post("/api/auth/verify-email",
                          json={"email": "nobody@student.babcock.edu.ng", "code": "123456"})
    wrong = client.post("/api/auth/verify-email",
                        json={"email": actor.email, "code": wrong_code(actor.otp)})
    assert unknown.status_code == wrong.status_code == 400
    assert unknown.get_json()["message"] == wrong.get_json()["message"]


def test_verification_never_accepts_a_substitute_address(client, register):
    """The code verifies the address on the account, and only that one."""
    actor = register_account(client, register)
    actor.relogin()
    actor.post("/api/auth/verify-email",
               json={"email": "someone.else@student.babcock.edu.ng", "code": actor.otp})
    resp = client.post("/api/auth/login",
                       json={"email": actor.email, "password": "Password123"})
    # Their own address is what got verified; no other row was touched.
    assert resp.get_json()["user"]["email_verified"] is True
    assert resp.get_json()["user"]["email"] == actor.email


# ── The gate ───────────────────────────────────────────────────────────────

def test_an_unverified_account_cannot_bypass_the_gate(client, register):
    """Logging in is allowed; USING the product is not.

    The session exists so the client can drive the verification screen. It
    reaches nothing else, and `next_step` sends it straight back.
    """
    actor = register_account(client, register)
    actor.relogin()
    assert actor.get("/api/auth/me").get_json()["next_step"] == "verify_email"

    for method, path in (("post", "/api/communities/join"),
                         ("get", "/api/dashboard"),
                         ("get", "/api/events")):
        resp = getattr(actor, method)(path, json={} if method == "post" else None)
        assert resp.status_code in (401, 403, 404), f"{path} answered {resp.status_code}"
        assert resp.status_code != 200, f"{path} let an unverified account through"


def test_verification_is_required_again_after_an_email_change(client, register):
    actor = register_account(client, register)
    assert verify(client, actor, actor.otp).status_code == 200
    actor.relogin()
    resp = actor.post("/api/auth/change-email",
                      json={"email": "moved@student.babcock.edu.ng"})
    assert resp.status_code == 200
    assert resp.get_json()["user"]["email_verified"] is False
    # A fresh code went to the NEW address, not the old one.
    assert email_service.sent_messages()[-1]["to"] == "moved@student.babcock.edu.ng"


# ── Delivery is reported truthfully ────────────────────────────────────────

def test_registration_does_not_claim_delivery_on_a_simulated_backend(client, register):
    """The suite runs on `memory`, which sends nothing. The response says so."""
    email_service.clear()
    actor = register(client)
    resp = client.post("/api/auth/login",
                       json={"email": actor.email, "password": "Password123"})
    assert resp.status_code == 200
    # Registration's own response carried the honest flag.
    fresh = client.post("/api/auth/register", json={**TERMS_ACCEPTED, 
        **{k: v for k, v in actor.profile.items()},
        "email": "another@student.babcock.edu.ng",
        "student_id_number": "BU/SEN/9911",
    })
    assert fresh.status_code == 201
    assert fresh.get_json()["email_delivered"] is False
    assert fresh.get_json()["email_backend"] == "memory"


def test_an_account_is_still_created_when_the_email_cannot_be_sent(client, register):
    """A provider outage must not cost the student their registration - they
    can ask for another code. It must also not be silent."""
    email_service.set_failure_hook(
        lambda to, subject, body: (_ for _ in ()).throw(RuntimeError("provider down")))
    try:
        actor = register(client)
    finally:
        email_service.set_failure_hook(None)

    resp = client.post("/api/auth/login",
                       json={"email": actor.email, "password": "Password123"})
    assert resp.status_code == 200, "the account exists"
    assert resp.get_json()["user"]["email_verified"] is False


@pytest.mark.parametrize("backend,expected", [("memory", False), ("console", False)])
def test_development_backends_never_report_delivery(app, backend, expected):
    """`is_delivering()` is what callers branch on; it must not be generous."""
    with app.app_context():
        app.config["EMAIL_BACKEND"] = backend
        result = email_service.send("someone@example.com", "s", "b")
        assert result.delivered is expected
        assert email_service.is_delivering() is expected


# ── The development bypass for the institutional-domain check ──────────────
#
# It exists so end-to-end delivery can be exercised: a provider in test mode
# only delivers to the account owner's own address, which is rarely an
# institutional one. It must be impossible to reach production.

def test_the_domain_bypass_is_off_by_default(client, app):
    from academicai.config import Config
    assert Config.ALLOW_ANY_EMAIL_DOMAIN is False
    resp = client.post("/api/auth/register", json={**TERMS_ACCEPTED, 
        "full_name": "Consumer Address", "email": "someone@gmail.com",
        "password": "Password123", "confirm_password": "Password123",
        "university": "Babcock University", "department": "Software Engineering",
        "level": "200", "academic_session": "2026/2027",
        "student_id_number": "BU/SEN/5150"})
    assert resp.status_code == 400
    assert "approved student email domain" in resp.get_json()["message"]


def test_the_bypass_lets_development_register_any_address(client, app):
    app.config["ALLOW_ANY_EMAIL_DOMAIN"] = True
    try:
        resp = client.post("/api/auth/register", json={**TERMS_ACCEPTED, 
            "full_name": "Consumer Address", "email": "someone@gmail.com",
            "password": "Password123", "confirm_password": "Password123",
            "university": "Babcock University", "department": "Software Engineering",
            "level": "200", "academic_session": "2026/2027",
            "student_id_number": "BU/SEN/5151"})
    finally:
        app.config["ALLOW_ANY_EMAIL_DOMAIN"] = False
    assert resp.status_code == 201
    # And the code still goes to the address that registered - the bypass
    # widens WHICH addresses may register, nothing else.
    assert email_service.sent_messages()[-1]["to"] == "someone@gmail.com"


def test_the_bypass_is_ignored_when_env_is_production(client, app):
    """Defence in depth: the check is safe on its own, not merely because
    startup would have refused."""
    app.config["ALLOW_ANY_EMAIL_DOMAIN"] = True
    app.config["ENV"] = "production"
    try:
        resp = client.post("/api/auth/register", json={**TERMS_ACCEPTED, 
            "full_name": "Consumer Address", "email": "someone@gmail.com",
            "password": "Password123", "confirm_password": "Password123",
            "university": "Babcock University", "department": "Software Engineering",
            "level": "200", "academic_session": "2026/2027",
            "student_id_number": "BU/SEN/5152"})
    finally:
        app.config["ALLOW_ANY_EMAIL_DOMAIN"] = False
        app.config["ENV"] = "development"
    assert resp.status_code == 400, "production must enforce the domain rule"


def test_production_refuses_to_start_with_the_bypass_set():
    """And it never gets that far, because the app will not boot."""
    import tempfile

    from academicai.app import create_app
    from academicai.config import Config

    class ProdConfig(Config):
        ENV = "production"
        TESTING = False
        SECRET_KEY = "a-real-production-secret"
        DATABASE_PATH = tempfile.mkdtemp() + "/academicai.db"
        EMAIL_BACKEND = "resend"
        RESEND_API_KEY = "re_test_key"
        ALLOW_ANY_EMAIL_DOMAIN = True

    with pytest.raises(RuntimeError) as excinfo:
        create_app(ProdConfig)
    assert "ACADEMICAI_ALLOW_ANY_EMAIL_DOMAIN" in str(excinfo.value)
