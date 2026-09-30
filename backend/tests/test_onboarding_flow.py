"""The MVP onboarding sequence, with no student ID-card step (spec 7, 9).

This file replaces test_identity_verification.py. The flow it pins is:

    register -> verify email -> community setup -> join -> (approval) -> dashboard

Student ID-card verification was removed from the product, so these tests are
also the guard against it creeping back: there is no identity endpoint, no
identity step in the state machine, and no payload that claims an identity was
verified.
"""
import pytest

pytestmark = pytest.mark.security


def _register_and_login(client, register, **kwargs):
    actor = register(client, **kwargs)
    resp = client.post("/api/auth/login",
                       json={"email": actor.email, "password": "Password123"})
    actor.token = resp.get_json()["token"]
    return actor


# --- the sequence ----------------------------------------------------------

def test_registration_asks_for_email_verification_next(client, register):
    actor = register(client)
    resp = client.post("/api/auth/login",
                       json={"email": actor.email, "password": "Password123"})
    actor.token = resp.get_json()["token"]
    assert actor.get("/api/auth/me").get_json()["next_step"] == "verify_email"


def test_verifying_the_email_leads_straight_to_community_setup(client, register):
    """There is no identity-verification step, under any name."""
    actor = register(client)
    resp = client.post("/api/auth/verify-email",
                       json={"email": actor.email, "code": actor.otp})
    assert resp.status_code == 200
    assert resp.get_json()["next_step"] == "community_setup"

    actor.relogin()
    assert actor.get("/api/auth/me").get_json()["next_step"] == "community_setup"


def test_the_whole_flow_reaches_the_dashboard_without_an_id_card(
        client, register, verified_user):
    """End to end, the sequence a real student now walks."""
    actor = _register_and_login(client, register)
    assert actor.get("/api/auth/me").get_json()["next_step"] == "verify_email"

    client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
    actor.relogin()
    assert actor.get("/api/auth/me").get_json()["next_step"] == "community_setup"

    assert actor.post("/api/community/setup").status_code in (200, 201)
    joined = actor.post("/api/community/join")
    assert joined.status_code == 201
    # First student into a brand-new PENDING community becomes a member.
    assert actor.get("/api/auth/me").get_json()["next_step"] in (
        "dashboard", "awaiting_approval")


def test_no_onboarding_step_is_ever_verify_identity(client, register, verified_user,
                                                    rep_community):
    """Whatever state a user is in, the client is never sent to an ID screen."""
    rep_community(size=4)
    seen = set()

    unverified = _register_and_login(client, register)
    seen.add(unverified.get("/api/auth/me").get_json()["next_step"])

    fresh = verified_user(client)
    seen.add(fresh.get("/api/auth/me").get_json()["next_step"])

    fresh.post("/api/community/setup")
    fresh.post("/api/community/join")
    seen.add(fresh.get("/api/auth/me").get_json()["next_step"])

    assert "verify_identity" not in seen
    assert seen <= {"verify_email", "community_setup", "awaiting_approval", "dashboard"}


# --- the removed feature must stay removed --------------------------------

def test_there_is_no_identity_endpoint(client, verified_user):
    actor = verified_user(client)
    for method in ("post", "get", "put", "delete"):
        resp = getattr(actor, method)("/api/auth/identity")
        assert resp.status_code in (404, 405), f"{method} {resp.status_code}"


def test_no_route_accepts_a_student_id_card_upload(client, verified_user):
    """Nothing anywhere takes an id_card_image part any more."""
    actor = verified_user(client)
    routes = [r for r in client.application.url_map.iter_rules()]
    assert not [r.rule for r in routes if "identity" in r.rule]


def test_the_identity_vision_modules_are_gone():
    """A dead subsystem left importable is a switch waiting to be flipped."""
    import importlib

    for name in ("academicai.ai.identity_vision", "academicai.ai.local_ocr",
                 "academicai.ai.ocr_text", "academicai.services.identity_service",
                 "academicai.services.identity_matching",
                 "academicai.services.temp_storage",
                 "academicai.security.image_validation"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(name)


def test_no_configuration_can_re_enable_identity_scanning(app):
    """There is no provider switch to set, so none can be set by accident."""
    from academicai.config import Config

    for key in ("IDENTITY_PROVIDER", "IDENTITY_VISION_PROVIDER",
                "IDENTITY_VISION_FIXTURE", "IDENTITY_MIN_CONFIDENCE",
                "IDENTITY_IMAGE_MAX_BYTES", "IDENTITY_TEMP_DIR",
                "TESSERACT_CMD", "IDENTITY_OCR_TIMEOUT"):
        assert not hasattr(Config, key), key
        assert key not in app.config, key


def test_the_authorization_gate_no_longer_reads_identity_status():
    """The gate must be rebuilt on the email check, not merely bypassed."""
    import inspect

    from academicai.security import authz

    assert not hasattr(authz, "require_identity_verified")
    assert not hasattr(authz, "assert_identity_verified")
    assert hasattr(authz, "assert_email_verified")

    for fn in (authz.is_rep, authz.is_eligible_member):
        assert "identity_status" not in inspect.getsource(fn), fn.__name__
        assert "email_verified" in inspect.getsource(fn), fn.__name__


def test_nobody_is_auto_marked_verified_by_the_removal(client, register, app):
    """The lazy fix for this scope change would be to stamp every account
    VERIFIED. That would be a false claim, so the legacy column must stay
    untouched at its default and simply go unread."""
    actor = register(client)
    client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})

    with app.app_context():
        from academicai.db.connection import query_one
        row = query_one("SELECT identity_status, email_verified FROM users WHERE id = ?",
                        (actor.user_id,))
    assert row["email_verified"] == 1
    assert row["identity_status"] == "UNVERIFIED"   # never rewritten to VERIFIED


def test_a_legacy_rejected_account_is_no_longer_blocked(client, register, app):
    """Existing rows carry old statuses. Those must not gate anything now.

    An account left REJECTED by the removed ID check would otherwise be
    permanently stuck, because nothing can clear that status any more.
    """
    actor = register(client)
    client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
    with app.app_context():
        from academicai.db.connection import execute, transaction
        with transaction() as conn:
            execute("UPDATE users SET identity_status = 'REJECTED' WHERE id = ?",
                    (actor.user_id,), conn=conn)
    actor.relogin()

    assert actor.get("/api/auth/me").get_json()["next_step"] == "community_setup"
    assert actor.post("/api/community/setup").status_code in (200, 201)
    assert actor.post("/api/community/join").status_code == 201


# --- membership is still separate -----------------------------------------

def test_passing_the_account_gate_is_not_membership(client, verified_user):
    """Preserved from the identity-era suite: the gate is not a membership."""
    actor = verified_user(client)
    payload = actor.get("/api/auth/me").get_json()
    assert payload["membership"] is None
    assert actor.get("/api/dashboard").status_code == 403


def test_email_verification_is_still_required_to_join(client, register):
    """The remaining gate is genuinely enforced, not just documented."""
    actor = _register_and_login(client, register)
    resp = actor.post("/api/community/setup")
    assert resp.status_code == 403
    assert "Email verification" in resp.get_json()["message"]
