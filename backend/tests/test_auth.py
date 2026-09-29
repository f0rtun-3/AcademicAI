"""Authentication and account lifecycle tests (spec 7, 25)."""
from datetime import timedelta

from academicai import clock
from academicai.services.auth_service import TERMS_VERSION  # noqa: E402
# What the sign-up form sends when its Terms box is ticked.
TERMS_ACCEPTED = {"accept_terms": True, "terms_version": TERMS_VERSION}


def test_health(client):
    assert client.get("/api/health").status_code == 200


def test_register_creates_unverified_account(client, register):
    actor = register(client)
    resp = client.post("/api/auth/login",
                       json={"email": actor.email, "password": "Password123"})
    assert resp.status_code == 200
    me = client.get("/api/auth/me",
                    headers={"Authorization": f"Bearer {resp.get_json()['token']}"})
    data = me.get_json()
    assert data["user"]["email_verified"] is False
    # No identity status is projected: the MVP has no ID-card check, so
    # reporting one would be a claim the product cannot make.
    assert "identity_status" not in data["user"]
    assert data["next_step"] == "verify_email"


def test_register_rejects_duplicate_email(client, register):
    actor = register(client)
    resp = client.post("/api/auth/register", json={**actor.profile})
    assert resp.status_code == 409


def test_register_rejects_password_mismatch(client):
    resp = client.post("/api/auth/register", json={**TERMS_ACCEPTED, 
        "full_name": "A B", "email": "ab@student.babcock.edu.ng",
        "password": "Password123", "confirm_password": "Password124",
        "university": "Babcock University", "department": "Software Engineering",
        "level": "200", "academic_session": "2026/2027",
    })
    assert resp.status_code == 400


def test_register_rejects_weak_password(client):
    resp = client.post("/api/auth/register", json={**TERMS_ACCEPTED, 
        "full_name": "A B", "email": "weak@student.babcock.edu.ng",
        "password": "short", "confirm_password": "short",
        "university": "Babcock University", "department": "Software Engineering",
        "level": "200", "academic_session": "2026/2027",
    })
    assert resp.status_code == 400


def test_password_is_never_stored_in_plaintext(client, register, app):
    register(client)
    with app.app_context():
        from academicai.db.connection import query_one
        row = query_one("SELECT password_hash FROM users LIMIT 1")
        assert "Password123" not in row["password_hash"]
        assert row["password_hash"].startswith("pbkdf2:")


def test_email_verification_flow(client, register):
    actor = register(client)
    resp = client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
    assert resp.status_code == 200
    assert resp.get_json()["user"]["email_verified"] is True
    # Email verification leads straight to community setup; the
    # verify_identity step was removed with the ID-card feature.
    assert resp.get_json()["next_step"] == "community_setup"


def test_email_verification_token_is_single_use(client, register):
    actor = register(client)
    client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
    resp = client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
    assert resp.status_code == 400


def test_email_verification_token_expires(client, register):
    actor = register(client)
    clock.advance(timedelta(hours=25))
    resp = client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
    assert resp.status_code == 400


def test_login_rejects_wrong_password(client, register):
    actor = register(client)
    resp = client.post("/api/auth/login", json={"email": actor.email, "password": "Wrong123456"})
    assert resp.status_code == 401


def test_login_error_does_not_reveal_account_existence(client, register):
    actor = register(client)
    known = client.post("/api/auth/login",
                        json={"email": actor.email, "password": "Wrong123456"}).get_json()
    unknown = client.post("/api/auth/login",
                          json={"email": "nobody@student.babcock.edu.ng",
                                "password": "Wrong123456"}).get_json()
    assert known == unknown


def test_logout_revokes_session(client, register):
    actor = register(client)
    resp = client.post("/api/auth/login", json={"email": actor.email, "password": "Password123"})
    actor.token = resp.get_json()["token"]
    assert actor.post("/api/auth/logout").status_code == 200
    assert actor.get("/api/auth/me").status_code == 401


def test_session_expires(client, register):
    actor = register(client)
    resp = client.post("/api/auth/login", json={"email": actor.email, "password": "Password123"})
    actor.token = resp.get_json()["token"]
    assert actor.get("/api/auth/me").status_code == 200
    clock.advance(timedelta(hours=25))
    assert actor.get("/api/auth/me").status_code == 401


def test_unauthenticated_request_is_rejected(client):
    assert client.get("/api/auth/me").status_code == 401


def test_garbage_token_is_rejected(client):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_password_reset_flow(client, register):
    actor = register(client)
    resp = client.post("/api/auth/forgot-password", json={"email": actor.email})
    assert resp.status_code == 200
    token = resp.get_json()["reset_token"]
    resp = client.post("/api/auth/reset-password", json={
        "token": token, "password": "NewPassword123", "confirm_password": "NewPassword123"})
    assert resp.status_code == 200
    assert client.post("/api/auth/login",
                       json={"email": actor.email, "password": "Password123"}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"email": actor.email,
                             "password": "NewPassword123"}).status_code == 200


def test_password_reset_invalidates_existing_sessions(client, register):
    actor = register(client)
    login = client.post("/api/auth/login", json={"email": actor.email, "password": "Password123"})
    actor.token = login.get_json()["token"]
    assert actor.get("/api/auth/me").status_code == 200
    token = client.post("/api/auth/forgot-password",
                        json={"email": actor.email}).get_json()["reset_token"]
    client.post("/api/auth/reset-password", json={
        "token": token, "password": "NewPassword123", "confirm_password": "NewPassword123"})
    assert actor.get("/api/auth/me").status_code == 401


def test_forgot_password_does_not_reveal_unknown_account(client):
    resp = client.post("/api/auth/forgot-password", json={"email": "ghost@student.babcock.edu.ng"})
    assert resp.status_code == 200
    assert "reset_token" not in resp.get_json()


def test_reset_token_is_single_use(client, register):
    actor = register(client)
    token = client.post("/api/auth/forgot-password",
                        json={"email": actor.email}).get_json()["reset_token"]
    payload = {"token": token, "password": "NewPassword123",
               "confirm_password": "NewPassword123"}
    assert client.post("/api/auth/reset-password", json=payload).status_code == 200
    assert client.post("/api/auth/reset-password", json=payload).status_code == 400
