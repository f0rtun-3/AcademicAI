"""Institutional student-email domain validation (identity Gate 1).

Gate 1 establishes control of an email account on a domain approved for the
SELECTED university. It is not proof of enrolment, and it does not stand in for
the ID-card check (Gate 2), community membership (Gate 3), or rep authority
(Gate 4). These tests hold all four apart.
"""
import pytest

from academicai import clock
from academicai.errors import ValidationError
from academicai.services import auth_service, email_domain_service
from tests.conftest import APPROVED_DOMAINS
from academicai.services.auth_service import TERMS_VERSION  # noqa: E402
# What the sign-up form sends when its Terms box is ticked.
TERMS_ACCEPTED = {"accept_terms": True, "terms_version": TERMS_VERSION}

pytestmark = pytest.mark.security


def _profile(university, email, **overrides):
    payload = {
        **TERMS_ACCEPTED,
        "full_name": "Fortune Okala",
        "email": email,
        "password": "Password123",
        "confirm_password": "Password123",
        "university": university,
        "department": "Software Engineering",
        "level": "200",
        "academic_session": "2026/2027",
        "student_id_number": "BU/SEN/0001",
    }
    payload.update(overrides)
    return payload


def _register(client, university, email, **overrides):
    return client.post("/api/auth/register",
                       json=_profile(university, email, **overrides))


# --- The four supported universities --------------------------------------

@pytest.mark.parametrize("university,email", [
    ("Babcock University", "fortune@student.babcock.edu.ng"),
    ("University of Ibadan", "fortune@stu.ui.edu.ng"),
    ("University of Lagos", "fortune@unilag.edu.ng"),
    ("Covenant University", "fortune@stu.cu.edu.ng"),
])
def test_approved_domain_is_accepted(client, university, email):
    resp = _register(client, university, email)
    assert resp.status_code == 201, resp.get_json()
    # A valid domain starts email verification; it does not complete it.
    assert resp.get_json()["next_step"] == "verify_email"


def test_the_registry_matches_the_documented_four(client):
    resp = client.get("/api/universities")
    assert resp.status_code == 200
    listed = {u["name"]: [d["domain"] for d in u["domains"]]
              for u in resp.get_json()["universities"]}
    assert listed == {
        "Babcock University": ["student.babcock.edu.ng"],
        "Covenant University": ["stu.cu.edu.ng"],
        "University of Ibadan": ["stu.ui.edu.ng"],
        "University of Lagos": ["unilag.edu.ng"],
    }


def test_oau_is_not_supported(client):
    """Only universities with a confirmed domain are in the registry."""
    resp = _register(client, "Obafemi Awolowo University", "fortune@oauife.edu.ng")
    assert resp.status_code == 400
    names = resp.get_json()["details"]["supported_universities"]
    assert "Obafemi Awolowo University" not in names


# --- Wrong domain for the selected university -----------------------------

@pytest.mark.parametrize("university,email", [
    ("Babcock University", "fortune@gmail.com"),
    ("Babcock University", "fortune@yahoo.com"),
    ("Babcock University", "fortune@outlook.com"),
])
def test_personal_email_is_rejected(client, university, email):
    resp = _register(client, university, email)
    assert resp.status_code == 400
    assert "approved student email domain" in resp.get_json()["message"]


@pytest.mark.parametrize("university,email", [
    ("Babcock University", "fortune@stu.cu.edu.ng"),
    ("Covenant University", "fortune@student.babcock.edu.ng"),
    ("University of Ibadan", "fortune@unilag.edu.ng"),
    ("University of Lagos", "fortune@stu.ui.edu.ng"),
    ("Covenant University", "fortune@stu.ui.edu.ng"),
])
def test_another_universitys_domain_is_rejected(client, university, email):
    """A real institutional domain is still wrong for the wrong university."""
    resp = _register(client, university, email)
    assert resp.status_code == 400
    details = resp.get_json()["details"]
    assert details["domain_belongs_to_another_university"] is True
    # The caller is told what IS acceptable for their selection.
    assert details["approved_domains"] == [APPROVED_DOMAINS[university]]


def test_a_bare_edu_ng_domain_is_not_accepted(client):
    """There is no generic '.edu.ng' rule."""
    for email in ("fortune@babcock.edu.ng", "fortune@ui.edu.ng",
                  "fortune@cu.edu.ng", "fortune@some-college.edu.ng"):
        resp = _register(client, "Babcock University", email)
        assert resp.status_code == 400, email


# --- Domain parsing must not be fooled ------------------------------------

@pytest.mark.parametrize("email", [
    "fortune@student.babcock.edu.ng.attacker.com",
    "fortune@attacker-student.babcock.edu.ng",
    "fortune@notstudent.babcock.edu.ng",
    "fortune@student.babcock.edu.ng.co",
    "fortune@evil.com?student.babcock.edu.ng",
    "fortune@student-babcock.edu.ng",
])
def test_lookalike_domains_are_rejected(client, email):
    """Comparison is exact equality, never a suffix or substring test."""
    resp = _register(client, "Babcock University", email)
    assert resp.status_code == 400, email


def test_a_subdomain_of_an_approved_domain_is_rejected(client):
    resp = _register(client, "Babcock University",
                     "fortune@mail.student.babcock.edu.ng")
    assert resp.status_code == 400


@pytest.mark.parametrize("email", [
    "FORTUNE@STUDENT.BABCOCK.EDU.NG",
    "Fortune@Student.Babcock.Edu.Ng",
    "fortune@STUDENT.babcock.edu.NG",
])
def test_domain_comparison_is_case_insensitive(client, email):
    resp = _register(client, "Babcock University", email)
    assert resp.status_code == 201, resp.get_json()


def test_surrounding_whitespace_is_tolerated(client):
    resp = _register(client, "  Babcock University  ",
                     "  fortune@student.babcock.edu.ng  ")
    assert resp.status_code == 201, resp.get_json()


@pytest.mark.parametrize("email", [
    "", "   ", "not-an-email", "fortune@", "@student.babcock.edu.ng",
    "fortune@@student.babcock.edu.ng", "fortune@localhost",
    "fortune at student.babcock.edu.ng", None,
])
def test_malformed_email_is_rejected(client, email):
    resp = _register(client, "Babcock University", email)
    assert resp.status_code == 400, email


@pytest.mark.parametrize("university", ["", "   ", None])
def test_missing_university_is_rejected(client, university):
    resp = _register(client, university, "fortune@student.babcock.edu.ng")
    assert resp.status_code == 400


def test_unknown_university_is_rejected_even_with_a_real_domain(client):
    resp = _register(client, "Hogwarts", "fortune@student.babcock.edu.ng")
    assert resp.status_code == 400
    assert "does not yet support that university" in resp.get_json()["message"]


def test_an_unknown_university_is_not_created_by_a_failed_attempt(client, app):
    """A rejected registration must leave no trace."""
    _register(client, "Ghost University", "fortune@gmail.com")
    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT id FROM universities WHERE name = ?",
                         ("Ghost University",)) is None
        assert query_one("SELECT id FROM users WHERE email = ?",
                         ("fortune@gmail.com",)) is None


def test_a_university_with_no_active_domain_is_rejected(client, app):
    """Deactivating a domain closes registration for that university."""
    with app.app_context():
        from academicai.db.connection import execute, transaction
        with transaction() as conn:
            execute("""UPDATE university_email_domains SET active = 0, deactivated_at = ?
                       WHERE domain = ?""",
                    (clock.now_iso(), "student.babcock.edu.ng"), conn=conn)

    resp = _register(client, "Babcock University", "fortune@student.babcock.edu.ng")
    assert resp.status_code == 400
    assert "does not yet support that university" in resp.get_json()["message"]
    # The row survives for audit; it is merely inactive.
    with app.app_context():
        from academicai.db.connection import query_one
        row = query_one("SELECT * FROM university_email_domains WHERE domain = ?",
                        ("student.babcock.edu.ng",))
        assert row["active"] == 0
        assert row["deactivated_at"] is not None


def test_a_deactivated_university_disappears_from_the_public_registry(client, app):
    with app.app_context():
        from academicai.db.connection import execute, transaction
        with transaction() as conn:
            execute("UPDATE university_email_domains SET active = 0 WHERE domain = ?",
                    ("stu.cu.edu.ng",), conn=conn)
    names = [u["name"] for u in client.get("/api/universities").get_json()["universities"]]
    assert "Covenant University" not in names
    assert "Babcock University" in names


# --- The backend, not the client, decides ---------------------------------

def test_the_client_cannot_supply_its_own_approved_domain(client):
    """Extra fields in the payload must not influence the registry."""
    payload = _profile("Babcock University", "attacker@stu.cu.edu.ng")
    payload.update({
        "approved_domains": ["stu.cu.edu.ng"],
        "university_email_domains": ["stu.cu.edu.ng"],
        "domain": "stu.cu.edu.ng",
        "skip_domain_check": True,
        "email_verified": True,
    })
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 400


def test_the_registry_endpoint_is_read_only(client):
    for method in ("post", "put", "delete", "patch"):
        resp = getattr(client, method)("/api/universities")
        assert resp.status_code in (405, 404), method


def test_validation_happens_before_any_email_is_sent(client):
    """No verification message may go out for a rejected domain."""
    from academicai.services import email_service

    email_service.clear()
    resp = _register(client, "Babcock University", "fortune@gmail.com")
    assert resp.status_code == 400
    assert email_service.sent_messages() == []


def test_a_valid_domain_does_send_a_verification_email(client):
    from academicai.services import email_service

    email_service.clear()
    assert _register(client, "Babcock University",
                     "fortune@student.babcock.edu.ng").status_code == 201
    assert len(email_service.sent_messages()) == 1


# --- Account enumeration --------------------------------------------------

def test_a_domain_error_does_not_reveal_an_existing_account(client):
    """A wrong domain reports the domain problem, never account existence."""
    assert _register(client, "Babcock University",
                     "taken@student.babcock.edu.ng").status_code == 201

    # Same address, wrong university: the domain rule fires first, so the
    # response says nothing about the account that already exists.
    resp = _register(client, "Covenant University", "taken@student.babcock.edu.ng")
    assert resp.status_code == 400
    body = resp.get_data(as_text=True).lower()
    assert "already exists" not in body
    assert "taken@student.babcock.edu.ng" not in body


def test_a_duplicate_registration_on_a_valid_domain_still_conflicts(client):
    """The existing duplicate-account behaviour is unchanged."""
    email = "dupe@student.babcock.edu.ng"
    assert _register(client, "Babcock University", email).status_code == 201
    assert _register(client, "Babcock University", email).status_code == 409


# --- Gate 1 is not Gate 2, 3 or 4 -----------------------------------------

def test_a_valid_domain_does_not_set_email_verified(client):
    resp = _register(client, "Babcock University", "fortune@student.babcock.edu.ng")
    token = resp.get_json()["verification_code"]
    login = client.post("/api/auth/login",
                        json={"email": "fortune@student.babcock.edu.ng",
                              "password": "Password123"})
    me = client.get("/api/auth/me",
                    headers={"Authorization": f"Bearer {login.get_json()['token']}"})
    assert me.get_json()["user"]["email_verified"] is False
    assert me.get_json()["next_step"] == "verify_email"
    assert token  # only the token can verify the address


def test_an_institutional_domain_cannot_skip_email_verification(client, register):
    """Gate 1 passed, email not yet verified: nothing is unlocked."""
    actor = register(client)
    actor.relogin()
    assert actor.post("/api/community/setup").status_code == 403
    assert actor.post("/api/community/join").status_code == 403
    assert actor.get("/api/dashboard").status_code == 403


def test_an_institutional_domain_plus_a_verified_email_is_not_membership(client, register):
    """Gate 1 + verified email opens onboarding, and nothing past it.

    This replaces a test that required identity verification as a second
    account gate. That gate is out of MVP scope, so setup is now reachable -
    but community DATA still is not, because membership is a separate gate.
    """
    actor = register(client)
    client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
    actor.relogin()

    me = actor.get("/api/auth/me").get_json()
    assert me["user"]["email_verified"] is True
    assert "identity_status" not in me["user"]
    assert me["next_step"] == "community_setup"

    assert actor.post("/api/community/setup").status_code in (200, 201)
    # Determining the community is not joining it, and joining is not reading.
    assert actor.get("/api/community").status_code == 403
    assert actor.get("/api/events").status_code == 403


def test_an_institutional_domain_does_not_grant_membership(client, verified_user):
    """Gate 1 + Gate 2 is still not Gate 3."""
    actor = verified_user(client)
    me = actor.get("/api/auth/me").get_json()
    assert me["user"]["email_verified"] is True
    assert me["membership"] is None
    assert actor.get("/api/community").status_code == 403


def test_an_institutional_domain_does_not_grant_rep_authority(client, joined_user):
    """Gate 1 + Gate 2 + Gate 3 is still not Gate 4."""
    actor = joined_user(client)
    assert actor.get("/api/community").get_json()["membership"]["role"] == "STUDENT"
    assert actor.post("/api/events", json={"title": "x",
                                           "event_type": "QUIZ"}).status_code == 403
    assert actor.post("/api/ai/publish", json={
        "action": "CREATE", "scope": "EVENT", "title": "x",
        "event_type": "QUIZ"}).status_code == 403


# --- Verification lifecycle is unchanged ----------------------------------

def test_email_verification_still_works_on_an_institutional_domain(client, register):
    actor = register(client)
    resp = client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
    assert resp.status_code == 200
    assert resp.get_json()["user"]["email_verified"] is True


def test_verification_code_still_expires(client, register):
    from datetime import timedelta

    actor = register(client)
    # Ten minutes now, not twenty-four hours: a six-digit code is only safe
    # while its life is short.
    clock.advance(timedelta(minutes=11))
    assert client.post("/api/auth/verify-email",
                       json={"email": actor.email, "code": actor.otp}).status_code == 400


def test_verification_token_is_still_single_use(client, register):
    actor = register(client)
    assert client.post("/api/auth/verify-email",
                       json={"email": actor.email, "code": actor.otp}).status_code == 200
    assert client.post("/api/auth/verify-email",
                       json={"email": actor.email, "code": actor.otp}).status_code == 400


def test_resend_replaces_the_previous_code_and_is_rate_limited(client, register, app):
    """The rule REVERSED when verification became a six-digit code.

    A 256-bit link token could be left live after a resend: guessing one was
    impossible, so an extra valid token widened nothing. Six digits is a space
    of a million, and every additional live code multiplies the chance a blind
    guess lands. So issuing a code now destroys the previous one, and this test
    is the inversion of the one it replaces.
    """
    from datetime import timedelta

    actor = register(client)
    actor.relogin()
    clock.advance(timedelta(seconds=61))  # past the resend cooldown
    resp = actor.post("/api/auth/resend-verification")
    assert resp.status_code == 200
    fresh = resp.get_json()["verification_code"]
    assert fresh != actor.otp

    # The OLD code is dead the moment a new one is issued.
    assert client.post("/api/auth/verify-email",
                       json={"email": actor.email, "code": actor.otp}).status_code == 400
    # The new one works, once.
    assert client.post("/api/auth/verify-email",
                       json={"email": actor.email, "code": fresh}).status_code == 200
    assert client.post("/api/auth/verify-email",
                       json={"email": actor.email, "code": fresh}).status_code == 400

    app.config["RATE_LIMIT_ENABLED"] = True
    try:
        other = register(client)
        other.relogin()
        statuses = []
        for _ in range(7):
            clock.advance(timedelta(seconds=61))  # cooldown is not the limit under test
            statuses.append(other.post("/api/auth/resend-verification").status_code)
        assert 429 in statuses
    finally:
        app.config["RATE_LIMIT_ENABLED"] = False


def test_verified_email_stays_required_after_verification(client, register):
    """Verifying email does not retroactively unlock later gates."""
    actor = register(client)
    client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
    actor.relogin()
    assert actor.get("/api/dashboard").status_code == 403


# --- Changing the email address -------------------------------------------

def test_the_only_email_changing_route_is_the_authenticated_one(app):
    """J·3 added exactly one route that can change an email address.

    This test replaces an earlier one asserting that NO such route existed. The
    invariant it was really protecting - that no endpoint can change an email
    while preserving verification - is now asserted directly by the tests
    below, against the route rather than against its absence.
    """
    routes = [str(r) for r in app.url_map.iter_rules()]
    email_routes = [r for r in routes
                    if "email" in r and r != "/api/auth/verify-email"
                    and "verification" not in r]
    assert email_routes == ["/api/auth/change-email"]


def test_change_email_route_requires_authentication(client):
    response = client.post("/api/auth/change-email",
                           json={"email": "moved@student.babcock.edu.ng"})
    assert response.status_code == 401


def test_change_email_route_enforces_the_institutional_domain(client, register):
    """Gate 1 is re-run by the service, so the route cannot bypass it."""
    actor = register(client)
    client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
    actor.relogin()

    response = actor.post("/api/auth/change-email", json={"email": "fortune@gmail.com"})
    assert response.status_code == 400
    # Unchanged and still verified.
    assert actor.get("/api/auth/me").get_json()["user"]["email"] == actor.email
    assert actor.get("/api/auth/me").get_json()["user"]["email_verified"] is True


def test_change_email_route_clears_verification_and_revokes_the_caller(client, register):
    """The caller logs itself out. That is the rule working, not a defect."""
    actor = register(client)
    client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
    actor.relogin()

    response = actor.post("/api/auth/change-email",
                          json={"email": "moved@student.babcock.edu.ng"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["user"]["email"] == "moved@student.babcock.edu.ng"
    assert payload["user"]["email_verified"] is False
    assert payload["next_step"] == "verify_email"

    # The session that made the request is gone.
    assert actor.get("/api/auth/me").status_code == 401
    # And the newly issued code verifies the NEW address.
    assert client.post("/api/auth/verify-email",
                       json={"email": "moved@student.babcock.edu.ng",
                             "code": payload["verification_code"]}).status_code == 200


def test_change_email_route_refuses_an_address_another_account_holds(client, register):
    first = register(client)
    second = register(client)
    client.post("/api/auth/verify-email", json={"email": second.email, "code": second.otp})
    second.relogin()

    response = second.post("/api/auth/change-email", json={"email": first.email})
    assert response.status_code == 409
    assert second.get("/api/auth/me").get_json()["user"]["email"] == second.email


def test_changing_email_clears_verification_and_revokes_sessions(client, register, app):
    actor = register(client)
    client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
    actor.relogin()
    assert actor.get("/api/auth/me").get_json()["user"]["email_verified"] is True

    with app.app_context():
        user, token = auth_service.change_email(
            actor.user_id, "moved@student.babcock.edu.ng")
    assert user["email"] == "moved@student.babcock.edu.ng"
    assert user["email_verified"] == 0
    # The old session no longer works.
    assert actor.get("/api/auth/me").status_code == 401

    # The new address can be verified with the newly issued code.
    assert client.post("/api/auth/verify-email",
                       json={"email": "moved@student.babcock.edu.ng",
                             "code": token}).status_code == 200


def test_changing_to_a_personal_email_is_rejected(client, register, app):
    actor = register(client)
    client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
    with app.app_context():
        with pytest.raises(ValidationError):
            auth_service.change_email(actor.user_id, "fortune@gmail.com")
        # Still the original, still verified.
        from academicai.db.connection import query_one
        row = query_one("SELECT * FROM users WHERE id = ?", (actor.user_id,))
        assert row["email"] == actor.email
        assert row["email_verified"] == 1


def test_changing_to_another_universitys_domain_is_rejected(client, register, app):
    actor = register(client)
    with app.app_context():
        with pytest.raises(ValidationError):
            auth_service.change_email(actor.user_id, "fortune@stu.cu.edu.ng")


def test_an_old_verification_link_cannot_verify_a_changed_address(client, register, app):
    actor = register(client)
    with app.app_context():
        auth_service.change_email(actor.user_id, "moved2@student.babcock.edu.ng")
    # The link issued for the previous address is spent.
    assert client.post("/api/auth/verify-email",
                       json={"email": actor.email, "code": actor.otp}).status_code == 400


# --- Transfers cannot sidestep the rule -----------------------------------

def test_a_transfer_to_another_university_is_rejected(client, joined_user):
    """A Babcock address cannot transfer into a Covenant community."""
    actor = joined_user(client)
    resp = actor.post("/api/community/transfer", json={
        "university": "Covenant University", "department": "Software Engineering",
        "level": "300", "academic_session": "2026/2027"})
    assert resp.status_code == 400
    assert "approved student email domain" in resp.get_json()["message"]


def test_a_transfer_to_an_unsupported_university_is_rejected(client, joined_user):
    actor = joined_user(client)
    resp = actor.post("/api/community/transfer", json={
        "university": "Hogwarts", "department": "Potions",
        "level": "300", "academic_session": "2026/2027"})
    assert resp.status_code == 400


def test_a_transfer_within_the_same_university_still_works(client, joined_user):
    """The existing transfer workflow is unchanged for same-university moves."""
    actor = joined_user(client)
    resp = actor.post("/api/community/transfer", json={
        "university": "Babcock University", "department": "Software Engineering",
        "level": "300", "academic_session": "2026/2027"})
    assert resp.status_code == 201, resp.get_json()


def test_a_failed_transfer_creates_no_community(client, joined_user, app):
    actor = joined_user(client)
    actor.post("/api/community/transfer", json={
        "university": "Covenant University", "department": "Software Engineering",
        "level": "300", "academic_session": "2026/2027"})
    with app.app_context():
        from academicai.db.connection import query_one
        covenant = query_one("SELECT id FROM universities WHERE name = ?",
                             ("Covenant University",))
        assert query_one(
            "SELECT id FROM academic_communities WHERE university_id = ?",
            (covenant["id"],)) is None


# --- Service-level unit checks --------------------------------------------

def test_extract_domain_rejects_ambiguous_addresses(app):
    with app.app_context():
        for value in ("a@b@c.com", "no-at-sign", "", None, "a@", "a@b"):
            with pytest.raises(ValidationError):
                email_domain_service.extract_domain(value)


def test_extract_domain_normalizes(app):
    with app.app_context():
        assert email_domain_service.extract_domain(
            "A@STUDENT.BABCOCK.EDU.NG") == "student.babcock.edu.ng"
        assert email_domain_service.extract_domain(
            "a@student.babcock.edu.ng.") == "student.babcock.edu.ng"


def test_domains_are_unique_across_universities(app):
    """One domain can never be claimed by two institutions."""
    import sqlite3

    with app.app_context():
        from academicai.db.connection import execute, transaction
        with pytest.raises(sqlite3.IntegrityError):
            with transaction() as conn:
                covenant = conn.execute(
                    "SELECT id FROM universities WHERE name = 'Covenant University'"
                ).fetchone()["id"]
                execute("""INSERT INTO university_email_domains
                           (university_id, domain, domain_type, active, created_at)
                           VALUES (?, 'student.babcock.edu.ng', 'STUDENT', 1, ?)""",
                        (covenant, clock.now_iso()), conn=conn)


def test_a_second_domain_can_be_added_without_touching_auth_logic(client, app):
    """The registry is extensible: adding a row is the whole change."""
    with app.app_context():
        from academicai.db.connection import execute, query_one, transaction
        with transaction() as conn:
            babcock = query_one("SELECT id FROM universities WHERE name = ?",
                                ("Babcock University",), conn=conn)["id"]
            execute("""INSERT INTO university_email_domains
                       (university_id, domain, domain_type, active, created_at)
                       VALUES (?, 'pg.babcock.edu.ng', 'STUDENT', 1, ?)""",
                    (babcock, clock.now_iso()), conn=conn)

    resp = _register(client, "Babcock University", "fortune@pg.babcock.edu.ng")
    assert resp.status_code == 201, resp.get_json()


def test_seeding_is_idempotent_and_non_destructive(app):
    from academicai.db import reference_data

    with app.app_context():
        from academicai.db.connection import get_db, query_one
        conn = get_db()
        before = query_one("SELECT COUNT(*) AS n FROM university_email_domains")["n"]
        # Already seeded: a second run writes nothing.
        assert reference_data.is_seeded(conn) is True
        assert reference_data.seed(conn, clock.now_iso()) is False
        after = query_one("SELECT COUNT(*) AS n FROM university_email_domains")["n"]
        assert after == before == 4


def test_registration_is_rate_limited(client, app):
    """Domain probing must not be free (spec 12).

    Exercised here because the HTTP smoke test disables rate limiting to run
    its full domain matrix; this keeps the limiter covered.
    """
    app.config["RATE_LIMIT_ENABLED"] = True
    try:
        statuses = []
        for i in range(8):
            statuses.append(_register(
                client, "Babcock University",
                f"probe{i}@student.babcock.edu.ng").status_code)
        assert 429 in statuses
        # The limiter fires before the domain rule is even reached, so it
        # equally throttles someone guessing at domains.
        assert _register(client, "Babcock University",
                         "probe-late@gmail.com").status_code == 429
    finally:
        app.config["RATE_LIMIT_ENABLED"] = False


def test_login_is_rate_limited(client, app, register):
    actor = register(client)
    app.config["RATE_LIMIT_ENABLED"] = True
    try:
        statuses = [client.post("/api/auth/login",
                                json={"email": actor.email,
                                      "password": "Wrong123456"}).status_code
                    for _ in range(14)]
        assert 429 in statuses
    finally:
        app.config["RATE_LIMIT_ENABLED"] = False


def test_the_universities_endpoint_is_rate_limited(client, app):
    app.config["RATE_LIMIT_ENABLED"] = True
    try:
        statuses = [client.get("/api/universities").status_code for _ in range(70)]
        assert 429 in statuses
    finally:
        app.config["RATE_LIMIT_ENABLED"] = False
