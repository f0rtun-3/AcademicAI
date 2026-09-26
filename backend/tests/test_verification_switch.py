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
                       json={**PROFILE, "email": email,
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
        EMAIL_BACKEND = "resend"
        RESEND_API_KEY = "re_test_key"
        ALLOW_ANY_EMAIL_DOMAIN = False
    for key, value in extra.items():
        setattr(ProdConfig, key, value)
    return ProdConfig


def test_production_refuses_unverified_signups_by_default():
    from academicai.app import create_app
    with pytest.raises(RuntimeError) as excinfo:
        create_app(_prod(EMAIL_VERIFICATION_REQUIRED=False))
    assert "ACADEMICAI_DEPLOYMENT_MODE=demo" in str(excinfo.value)


def test_production_allows_it_only_when_declared_a_demo():
    """Two variables, not one: a single flag can be set and forgotten."""
    from academicai.app import create_app
    app = create_app(_prod(EMAIL_VERIFICATION_REQUIRED=False, DEPLOYMENT_MODE="demo"))
    assert app.config["EMAIL_VERIFICATION_REQUIRED"] is False


def test_a_near_miss_deployment_mode_does_not_count():
    from academicai.app import create_app
    for mode in ("staging", "test", "DEMO_", "", "standard"):
        with pytest.raises(RuntimeError):
            create_app(_prod(EMAIL_VERIFICATION_REQUIRED=False, DEPLOYMENT_MODE=mode))


def test_demo_mode_alone_changes_nothing_when_verification_is_on():
    """The acknowledgement is not itself a switch."""
    from academicai.app import create_app
    app = create_app(_prod(DEPLOYMENT_MODE="demo"))
    assert app.config["EMAIL_VERIFICATION_REQUIRED"] is True
