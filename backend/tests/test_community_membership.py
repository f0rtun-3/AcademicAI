"""Community determination, PENDING bootstrap and ACTIVE approval (spec 7, 8, 9)."""
import pytest


def test_setup_creates_pending_community(client, verified_user):
    actor = verified_user(client)
    resp = actor.post("/api/community/setup")
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["created"] is True
    assert data["community"]["status"] == "PENDING"
    assert "hasn't been set up yet" in data["message"]


def test_setup_finds_existing_community(client, verified_user):
    first = verified_user(client)
    first.post("/api/community/setup")
    second = verified_user(client)
    resp = second.post("/api/community/setup")
    assert resp.status_code == 200
    assert resp.get_json()["existed"] is True
    assert resp.get_json()["message"] == "Your academic community is ready."


def test_community_identity_is_four_part_unique(client, verified_user):
    a = verified_user(client)
    a.post("/api/community/setup")
    b = verified_user(client, level="300")
    b.post("/api/community/setup")
    c = verified_user(client, department="Computer Science", level="300")
    c.post("/api/community/setup")
    ids = set()
    for actor in (a, b, c):
        ids.add(actor.post("/api/community/setup").get_json()["community"]["id"])
    assert len(ids) == 3


def test_eligible_student_auto_joins_pending_community(client, joined_user):
    """Bootstrap path: auto-join exists only to make a first election possible (spec 8)."""
    actor = joined_user(client)
    assert actor.awaiting_approval is False
    resp = actor.get("/api/community")
    assert resp.status_code == 200
    assert resp.get_json()["membership"]["status"] == "ACTIVE"
    assert resp.get_json()["membership"]["role"] == "STUDENT"


def test_a_student_without_a_verified_email_cannot_join(client, register):
    """The account gate is enforced at join time (spec 8).

    A confirmed institutional email is the whole gate, and it is checked here.
    """
    actor = register(client)
    resp = client.post("/api/auth/login",
                       json={"email": actor.email, "password": "Password123"})
    actor.token = resp.get_json()["token"]

    resp = actor.post("/api/community/join")
    assert resp.status_code == 403
    assert "Email verification" in resp.get_json()["message"]


def test_an_email_verified_student_joins_their_own_pending_community(client, register):
    """The first eligible student into a brand-new community becomes a member.

    A PENDING community has nobody to approve anyone, so an eligible student
    joins it directly (spec 8). Note what this does NOT grant: the role is
    STUDENT, and becoming a rep still requires the full election.
    """
    actor = register(client)
    client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
    actor.relogin()

    assert actor.post("/api/community/setup").status_code in (200, 201)
    resp = actor.post("/api/community/join")
    assert resp.status_code == 201
    assert resp.get_json()["membership"]["status"] == "ACTIVE"
    assert resp.get_json()["membership"]["role"] == "STUDENT"


def test_duplicate_join_is_rejected(client, joined_user):
    actor = joined_user(client)
    assert actor.post("/api/community/join").status_code == 409


def test_member_can_list_members(client, joined_user):
    a = joined_user(client)
    joined_user(client)
    resp = a.get("/api/community/members")
    assert resp.status_code == 200
    assert len(resp.get_json()["members"]) == 2


def test_non_member_cannot_read_community(client, verified_user):
    actor = verified_user(client)
    assert actor.get("/api/community").status_code == 403
    assert actor.get("/api/community/members").status_code == 403


def test_leave_community_ends_membership(client, joined_user):
    actor = joined_user(client)
    assert actor.post("/api/community/leave").status_code == 200
    assert actor.get("/api/community").status_code == 403


def test_join_of_archived_community_is_rejected(client, joined_user, verified_user, app):
    actor = joined_user(client)
    with app.app_context():
        from academicai.db.connection import execute, transaction
        with transaction() as conn:
            execute("UPDATE academic_communities SET status = 'ARCHIVED' WHERE id = ?",
                    (actor.community_id,), conn=conn)
    other = verified_user(client)
    resp = other.post("/api/community/join", json={"community_id": actor.community_id})
    assert resp.status_code == 409
