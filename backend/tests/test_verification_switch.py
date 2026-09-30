"""Registration with email verification switched off.

WHAT THE SWITCH IS FOR: a transactional email provider in test mode delivers
only to the account owner's own address, so a public demo cannot mail its
students at all. Every registration would strand somebody on a verification
screen they could never pass. Turning verification off lets the demo run.

WHAT IT MUST NOT TOUCH: everything else. The institutional-domain rule, the
duplicate check, password hashing and every authorisation gate behave exactly
as they do with verification on. The tests below are mostly about that - the
switch must be the ONLY difference, and the OTP implementation must still be
sitting there intact, ready to be switched back on.
"""
import pytest

from academicai.db.connection import query_all, query_one
from academicai.services import email_service
from academicai.services.auth_service import TERMS_VERSION  # noqa: E402
# What the sign-up form sends when its Terms box is ticked.
TERMS_ACCEPTED = {"accept_terms": True, "terms_version": TERMS_VERSION}

PROFILE = {
    "full_name": "Demo Student",
    "password": "Password123", "confirm_password": "Password123",
    "university": "Babcock University", "department": "Software Engineering",
    "level": "200", "academic_session": "2026/2027",
}


@pytest.fixture
def verification_off(app):
    """The demo deployment's configuration, and nothing else changed."""
    app.config["EMAIL_VERIFICATION_REQUIRED"] = False
    email_service.clear()
    yield app
    app.config["EMAIL_VERIFICATION_REQUIRED"] = True


def register(client, email, student_id="BU/SEN/9001", **over):
    return client.post("/api/auth/register",
                       json={**TERMS_ACCEPTED, **PROFILE, "email": email,
                             "student_id_number": student_id, **over})


# ── With the switch off ────────────────────────────────────────────────────

def test_an_institutional_address_registers_and_works_immediately(client, verification_off):
    resp = register(client, "demo.one@student.babcock.edu.ng")
    assert resp.status_code == 201
    payload = resp.get_json()
    assert payload["user"]["email_verified"] is True
    assert payload["email_verification_required"] is False
    # Straight past the gate: the verification screen is never routed to.
    assert payload["next_step"] == "community_setup"


def test_the_new_account_can_log_in_at_once(client, verification_off):
    register(client, "demo.two@student.babcock.edu.ng", "BU/SEN/9002")
    resp = client.post("/api/auth/login",
                       json={"email": "demo.two@student.babcock.edu.ng",
                             "password": "Password123"})
    assert resp.status_code == 200
    token = resp.get_json()["token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.get_json()["next_step"] == "community_setup"
    # And the email gate genuinely opens, rather than the client merely being
    # pointed somewhere: this 403s for an unverified account.
    resp = client.get("/api/community", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code != 403 or "Email verification" not in resp.get_json()["message"]


def test_no_code_is_generated(client, verification_off, app):
    resp = register(client, "demo.three@student.babcock.edu.ng", "BU/SEN/9003")
    assert "verification_code" not in resp.get_json()
    with app.app_context():
        user = query_one("SELECT id FROM users WHERE email = ?",
                         ("demo.three@student.babcock.edu.ng",))
        codes = query_all("SELECT id FROM email_verification_tokens WHERE user_id = ?",
                          (user["id"],))
    assert codes == [], "an unused code is a credential nobody is watching"


def test_no_email_is_attempted(client, verification_off):
    register(client, "demo.four@student.babcock.edu.ng", "BU/SEN/9004")
    assert email_service.sent_messages() == []


def test_the_institutional_domain_rule_still_applies(client, verification_off):
    """The switch turns off OWNERSHIP proof, not the affiliation rule."""
    for address in ("someone@gmail.com", "someone@yahoo.com", "someone@hotmail.com"):
        resp = register(client, address, "BU/SEN/9005")
        assert resp.status_code == 400, address
        assert "approved student email domain" in resp.get_json()["message"]


def test_a_duplicate_address_is_still_refused(client, verification_off):
    assert register(client, "demo.dup@student.babcock.edu.ng", "BU/SEN/9006").status_code == 201
    resp = register(client, "demo.dup@student.babcock.edu.ng", "BU/SEN/9007")
    assert resp.status_code == 409
    assert "already exists" in resp.get_json()["message"]


def test_the_password_is_still_hashed(client, verification_off, app):
    register(client, "demo.pw@student.babcock.edu.ng", "BU/SEN/9008")
    with app.app_context():
        row = query_one("SELECT password_hash FROM users WHERE email = ?",
                        ("demo.pw@student.babcock.edu.ng",))
    stored = row["password_hash"]
    assert "Password123" not in stored, "the password must not be recoverable"
    # Still the project's PBKDF2 format, not something weaker introduced here.
    assert stored.startswith("pbkdf2"), stored[:24]
    from academicai.security.passwords import verify_password
    assert verify_password(stored, "Password123")
    assert not verify_password(stored, "Password124")


def test_an_invalid_address_is_still_refused(client, verification_off):
    assert register(client, "not-an-email", "BU/SEN/9009").status_code == 400


def test_how_the_account_was_verified_is_recorded(client, verification_off, app):
    """So that re-enabling verification can find the accounts that never had it."""
    register(client, "demo.method@student.babcock.edu.ng", "BU/SEN/9010")
    with app.app_context():
        row = query_one("SELECT email_verified, email_verification_method "
                        "FROM users WHERE email = ?",
                        ("demo.method@student.babcock.edu.ng",))
    assert row["email_verified"] == 1
    assert row["email_verification_method"] == "SKIPPED_NO_VERIFICATION"


def test_the_otp_endpoints_say_plainly_that_they_are_off(client, verification_off):
    """Rather than reporting every code incorrect, which is what would happen
    if they were left to run against an account that has no code."""
    resp = client.post("/api/auth/verify-email",
                       json={"email": "demo.one@student.babcock.edu.ng", "code": "123456"})
    assert resp.status_code == 409
    assert "not enabled on this deployment" in resp.get_json()["message"]


def _signed_in(client, email, student_id):
    register(client, email, student_id)
    token = client.post("/api/auth/login",
                        json={"email": email, "password": "Password123"}).get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_the_new_account_can_join_its_community(client, verification_off):
    """Proceeding normally means past the email gate and into a community,
    not merely being routed towards one."""
    headers = _signed_in(client, "demo.join@student.babcock.edu.ng", "BU/SEN/9011")
    assert client.post("/api/community/setup", headers=headers).status_code in (200, 201)
    resp = client.post("/api/community/join", headers=headers)
    assert resp.status_code == 201, resp.get_json()


def test_changing_email_is_refused_rather_than_locking_the_account_out(
        client, verification_off):
    """An email change clears email_verified, and with the OTP endpoints off
    nothing could set it again. So it is refused, and nothing changes."""
    headers = _signed_in(client, "demo.move@student.babcock.edu.ng", "BU/SEN/9012")
    email_service.clear()
    resp = client.post("/api/auth/change-email", headers=headers,
                       json={"email": "demo.moved@student.babcock.edu.ng"})
    assert resp.status_code == 409
    payload = resp.get_json()
    assert "switched off" in payload["message"]
    assert payload["details"] == {"email_verification_required": False}
    assert "verification_code" not in payload
    assert email_service.sent_messages() == []
    # The address, the verification and this very session are all intact.
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.get_json()["user"]["email"] == "demo.move@student.babcock.edu.ng"
    assert me.get_json()["user"]["email_verified"] is True
    assert me.get_json()["next_step"] == "community_setup"


def test_the_account_says_verification_was_not_required(client, verification_off):
    """Stored as verified so every gate opens, but it must not READ as verified."""
    resp = register(client, "demo.status@student.babcock.edu.ng", "BU/SEN/9013")
    assert resp.get_json()["user"]["email_verification"] == "not_required"
    headers = {"Authorization": "Bearer " + client.post(
        "/api/auth/login", json={"email": "demo.status@student.babcock.edu.ng",
                                 "password": "Password123"}).get_json()["token"]}
    assert client.get("/api/auth/me", headers=headers).get_json()["user"][
        "email_verification"] == "not_required"


# ── Registered while verification was ON, then it was switched off ────────
#
# The code never arrived, so the account is still email_verified = 0. Nothing
# rewrites that on its own: the gates read the stored state, the verification
# endpoints are off, and the account waits. This is the one-time migration an
# operator runs after switching verification off; it is the tested one.

STRANDED_ACCOUNTS_MIGRATION = """UPDATE users
   SET email_verified = 1, email_verification_method = 'SKIPPED_NO_VERIFICATION'
 WHERE email_verified = 0"""


def _stranded(client, app, email, student_id):
    """Register with verification on, never enter the code, then switch it off."""
    resp = register(client, email, student_id)
    assert resp.get_json()["next_step"] == "verify_email"
    app.config["EMAIL_VERIFICATION_REQUIRED"] = False
    token = client.post("/api/auth/login",
                        json={"email": email, "password": "Password123"}).get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_a_stranded_account_is_left_exactly_as_it_was(client, app):
    headers = _stranded(client, app, "stranded.one@student.babcock.edu.ng", "BU/SEN/9020")
    me = client.get("/api/auth/me", headers=headers).get_json()
    assert me["next_step"] == "verify_email"
    assert me["user"]["email_verified"] is False
    assert me["user"]["email_verification"] == "pending"
    # What the verification screen reads, so it does not claim a code was sent.
    assert me["email_verification_required"] is False
    # Its history is not rewritten behind anyone's back...
    with app.app_context():
        row = query_one("SELECT email_verified, email_verification_method FROM users "
                        "WHERE email = ?", ("stranded.one@student.babcock.edu.ng",))
    assert (row["email_verified"], row["email_verification_method"]) == (0, "OTP")
    # ...its gates stay shut...
    assert client.post("/api/community/setup", headers=headers).status_code == 403
    # ...and the code endpoints say plainly that they are off.
    email_service.clear()
    for path in ("/api/auth/resend-verification", "/api/auth/verify-email"):
        resp = client.post(path, headers=headers,
                           json={"email": "stranded.one@student.babcock.edu.ng", "code": "123456"})
        assert resp.status_code == 409, path
        assert "not enabled on this deployment" in resp.get_json()["message"]
    assert email_service.sent_messages() == []


def test_the_migration_makes_a_stranded_account_usable_and_touches_nothing_else(client, app):
    from academicai.db.connection import execute, transaction

    headers = _stranded(client, app, "stranded.two@student.babcock.edu.ng", "BU/SEN/9021")
    # A genuinely verified account beside it, which the migration must not touch.
    app.config["EMAIL_VERIFICATION_REQUIRED"] = True
    code = register(client, "otp.done@student.babcock.edu.ng", "BU/SEN/9022").get_json()[
        "verification_code"]
    assert client.post("/api/auth/verify-email", json={
        "email": "otp.done@student.babcock.edu.ng", "code": code}).status_code == 200
    app.config["EMAIL_VERIFICATION_REQUIRED"] = False

    with app.app_context():
        with transaction() as conn:
            changed = execute(STRANDED_ACCOUNTS_MIGRATION, conn=conn).rowcount
    assert changed == 1

    me = client.get("/api/auth/me", headers=headers).get_json()
    assert me["next_step"] == "community_setup"
    assert me["user"]["email_verification"] == "not_required"
    assert client.post("/api/community/setup", headers=headers).status_code in (200, 201)
    assert client.post("/api/community/join", headers=headers).status_code == 201
    with app.app_context():
        done = query_one("SELECT email_verification_method FROM users WHERE email = ?",
                         ("otp.done@student.babcock.edu.ng",))
    assert done["email_verification_method"] == "OTP"


# ── With the switch on: the OTP flow is untouched ──────────────────────────

def test_the_otp_flow_still_works_when_enabled(client, register_fixture=None):
    """The whole point of a switch rather than a deletion."""
    from academicai.services import email_service as es
    es.clear()
    resp = register(client, "real.student@student.babcock.edu.ng", "BU/SEN/9100")
    assert resp.status_code == 201
    payload = resp.get_json()

    assert payload["user"]["email_verified"] is False
    assert payload["next_step"] == "verify_email"
    assert payload["email_verification_required"] is True

    code = payload["verification_code"]
    assert code.isdigit() and len(code) == 6
    assert any(code in m["body"] for m in es.sent_messages())

    verify = client.post("/api/auth/verify-email",
                         json={"email": "real.student@student.babcock.edu.ng", "code": code})
    assert verify.status_code == 200
    assert verify.get_json()["user"]["email_verified"] is True


def test_an_otp_verified_account_is_recorded_as_such(client, app):
    resp = register(client, "real.method@student.babcock.edu.ng", "BU/SEN/9101")
    client.post("/api/auth/verify-email",
                json={"email": "real.method@student.babcock.edu.ng",
                      "code": resp.get_json()["verification_code"]})
    with app.app_context():
        row = query_one("SELECT email_verification_method FROM users WHERE email = ?",
                        ("real.method@student.babcock.edu.ng",))
    assert row["email_verification_method"] == "OTP"


def test_the_account_says_pending_then_verified(client):
    resp = register(client, "real.status@student.babcock.edu.ng", "BU/SEN/9102")
    assert resp.get_json()["user"]["email_verification"] == "pending"
    token = client.post("/api/auth/login", json={
        "email": "real.status@student.babcock.edu.ng",
        "password": "Password123"}).get_json()["token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).get_json()
    assert me["email_verification_required"] is True
    verify = client.post("/api/auth/verify-email", json={
        "email": "real.status@student.babcock.edu.ng",
        "code": resp.get_json()["verification_code"]})
    assert verify.get_json()["user"]["email_verification"] == "verified"


def test_an_account_let_through_earlier_reads_verified_once_it_enters_a_code(client, app):
    """Verification off, then back on: an email change asks for a code, and
    entering it makes the account genuinely verified - and recorded as such."""
    app.config["EMAIL_VERIFICATION_REQUIRED"] = False
    register(client, "was.skipped@student.babcock.edu.ng", "BU/SEN/9103")
    token = client.post("/api/auth/login", json={
        "email": "was.skipped@student.babcock.edu.ng",
        "password": "Password123"}).get_json()["token"]
    app.config["EMAIL_VERIFICATION_REQUIRED"] = True
    changed = client.post("/api/auth/change-email",
                          headers={"Authorization": f"Bearer {token}"},
                          json={"email": "now.verified@student.babcock.edu.ng"}).get_json()
    assert changed["user"]["email_verification"] == "pending"
    verify = client.post("/api/auth/verify-email", json={
        "email": "now.verified@student.babcock.edu.ng", "code": changed["verification_code"]})
    assert verify.status_code == 200
    assert verify.get_json()["user"]["email_verification"] == "verified"
    with app.app_context():
        row = query_one("SELECT email_verification_method FROM users WHERE email = ?",
                        ("now.verified@student.babcock.edu.ng",))
    assert row["email_verification_method"] == "OTP"


def test_the_switch_defaults_to_requiring_verification(app):
    """A deployment that configures nothing gets the safe behaviour."""
    from academicai.config import Config
    assert Config.EMAIL_VERIFICATION_REQUIRED is True


# ── Production safety ──────────────────────────────────────────────────────

def _prod(**extra):
    import tempfile

    from academicai.config import Config

    class ProdConfig(Config):
        ENV = "production"
        TESTING = False
        SECRET_KEY = "a-real-production-secret"
        DATABASE_PATH = tempfile.mkdtemp() + "/academicai.db"
        # Production runs on PostgreSQL. These tests are about the start-up
        # checks, which run before any connection is made (_passes_checks).
        DATABASE_BACKEND = "postgresql"
        DATABASE_URL = "postgresql://academicai@db.internal:5432/academicai"
        EMAIL_BACKEND = "resend"
        RESEND_API_KEY = "re_test_key"
        ALLOW_ANY_EMAIL_DOMAIN = False
    for key, value in extra.items():
        setattr(ProdConfig, key, value)
    return ProdConfig


def _passes_checks(config):
    """The production start-up checks alone, without connecting to a database."""
    from flask import Flask

    from academicai.app import _validate_production_config
    app = Flask("check")
    app.config.from_object(config)
    _validate_production_config(app)
    return app


def test_production_refuses_unverified_signups_while_nothing_is_declared():
    """Verification off, DEPLOYMENT_MODE still the default: refused. One flag
    can be cleared and forgotten - an empty value reads as false."""
    from academicai.app import create_app
    with pytest.raises(RuntimeError) as excinfo:
        create_app(_prod(EMAIL_VERIFICATION_REQUIRED=False))
    assert "ACADEMICAI_DEPLOYMENT_MODE=production" in str(excinfo.value)


def test_production_runs_with_verification_off_when_declared_production(caplog):
    """The live deployment: production, verification temporarily off. No demo."""
    with caplog.at_level("WARNING", logger="academicai.app"):
        app = _passes_checks(_prod(EMAIL_VERIFICATION_REQUIRED=False,
                                   DEPLOYMENT_MODE="production"))
    assert app.config["EMAIL_VERIFICATION_REQUIRED"] is False
    # Permitted, never silent - and not described as a demo.
    assert "PRODUCTION DEPLOYMENT: email verification is DISABLED" in caplog.text
    assert "DEMO" not in caplog.text


def test_production_runs_with_verification_on_in_every_declared_mode():
    for mode in ("standard", "production", "demo"):
        assert _passes_checks(_prod(DEPLOYMENT_MODE=mode)).config[
            "EMAIL_VERIFICATION_REQUIRED"] is True


def test_a_demo_may_still_run_without_verification(caplog):
    with caplog.at_level("WARNING", logger="academicai.app"):
        app = _passes_checks(_prod(EMAIL_VERIFICATION_REQUIRED=False, DEPLOYMENT_MODE="demo"))
    assert app.config["EMAIL_VERIFICATION_REQUIRED"] is False
    assert "DEMO DEPLOYMENT: email verification is DISABLED" in caplog.text


def test_a_near_miss_deployment_mode_does_not_count():
    from academicai.app import create_app
    for mode in ("staging", "test", "DEMO_", "", "standard", "prod", "live"):
        with pytest.raises(RuntimeError):
            create_app(_prod(EMAIL_VERIFICATION_REQUIRED=False, DEPLOYMENT_MODE=mode))


def test_an_unknown_deployment_mode_is_refused_even_with_verification_on():
    """A typo would otherwise change what the verification check allows."""
    with pytest.raises(RuntimeError) as excinfo:
        _passes_checks(_prod(DEPLOYMENT_MODE="prodution"))
    assert "ACADEMICAI_DEPLOYMENT_MODE is 'prodution'" in str(excinfo.value)


@pytest.mark.parametrize("override, refusal", [
    ({"SECRET_KEY": "dev-insecure-secret-change-me"}, "ACADEMICAI_SECRET_KEY"),
    ({"DATABASE_BACKEND": "sqlite"}, "requires 'postgresql'"),
    ({"DATABASE_URL": None}, "ACADEMICAI_DATABASE_URL must be set"),
    ({"EMAIL_BACKEND": "console"}, "does not send mail"),
    ({"RESEND_API_KEY": None}, "ACADEMICAI_RESEND_API_KEY must be set"),
    ({"ALLOW_ANY_EMAIL_DOMAIN": True}, "ACADEMICAI_ALLOW_ANY_EMAIL_DOMAIN must not be set"),
])
def test_turning_verification_off_relaxes_no_other_production_check(override, refusal):
    with pytest.raises(RuntimeError) as excinfo:
        _passes_checks(_prod(EMAIL_VERIFICATION_REQUIRED=False,
                             DEPLOYMENT_MODE="production", **override))
    assert refusal in str(excinfo.value)


@pytest.mark.postgres
def test_a_production_start_on_postgresql_with_verification_off(pg_schema):
    """The real thing: starts, registers without a code, attempts no email."""
    from academicai.app import create_app
    app = create_app(_prod(EMAIL_VERIFICATION_REQUIRED=False, DEPLOYMENT_MODE="production",
                           DATABASE_URL=pg_schema))
    attempts = []
    email_service.set_failure_hook(lambda to, subject, body: attempts.append(to))
    resp = register(app.test_client(), "prod.user@student.babcock.edu.ng", "BU/SEN/9200")
    assert resp.status_code == 201, resp.get_json()
    payload = resp.get_json()
    assert payload["next_step"] == "community_setup"
    assert payload["user"]["email_verification"] == "not_required"
    assert "verification_code" not in payload
    assert attempts == [], "no email may be attempted"


def test_demo_mode_alone_changes_nothing_when_verification_is_on():
    """The acknowledgement is not itself a switch."""
    app = _passes_checks(_prod(DEPLOYMENT_MODE="demo"))
    assert app.config["EMAIL_VERIFICATION_REQUIRED"] is True
