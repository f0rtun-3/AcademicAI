"""Membership approval in an ACTIVE community (spec 9)."""


def test_new_student_in_active_community_awaits_approval(client, rep_community, verified_user):
    rep, _members = rep_community(size=4)
    newcomer = verified_user(client)
    newcomer.post("/api/community/setup")
    resp = newcomer.post("/api/community/join")
    assert resp.status_code == 201
    assert resp.get_json()["awaiting_approval"] is True
    assert resp.get_json()["membership"]["status"] == "PENDING_APPROVAL"


def test_awaiting_student_is_not_treated_as_a_member(client, rep_community, verified_user):
    """A student awaiting approval must not be treated as an active member (spec 9)."""
    rep, _members = rep_community(size=4)
    newcomer = verified_user(client)
    newcomer.post("/api/community/setup")
    newcomer.post("/api/community/join")
    assert newcomer.get("/api/community").status_code == 403
    assert newcomer.get("/api/community/members").status_code == 403


def test_awaiting_state_is_signalled_to_the_client(client, rep_community, verified_user):
    """The UI needs an explicit awaiting state rather than a bare 403 (spec 9)."""
    rep, _members = rep_community(size=4)
    newcomer = verified_user(client)
    newcomer.post("/api/community/setup")
    newcomer.post("/api/community/join")
    me = newcomer.get("/api/auth/me").get_json()
    assert me["next_step"] == "awaiting_approval"
    assert me["membership"] is None
    assert me["pending_membership"]["status"] == "PENDING_APPROVAL"


def test_rep_sees_and_approves_request(client, rep_community, verified_user):
    rep, _members = rep_community(size=4)
    newcomer = verified_user(client)
    newcomer.post("/api/community/setup")
    newcomer.post("/api/community/join")

    requests = rep.get("/api/community/requests").get_json()["requests"]
    assert [r["user_id"] for r in requests] == [newcomer.user_id]

    resp = rep.post(f"/api/community/requests/{newcomer.user_id}/approve")
    assert resp.status_code == 200
    assert resp.get_json()["membership"]["status"] == "ACTIVE"
    assert newcomer.get("/api/community").status_code == 200


def test_approval_does_not_make_the_student_a_rep(client, rep_community, verified_user):
    """Approval gives membership_status ACTIVE; the role stays STUDENT (spec 9)."""
    rep, _members = rep_community(size=4)
    newcomer = verified_user(client)
    newcomer.post("/api/community/setup")
    newcomer.post("/api/community/join")
    rep.post(f"/api/community/requests/{newcomer.user_id}/approve")
    assert newcomer.get("/api/community").get_json()["membership"]["role"] == "STUDENT"
    assert newcomer.get("/api/community/requests").status_code == 403


def test_student_cannot_approve_membership(client, rep_community, verified_user):
    rep, members = rep_community(size=4)
    newcomer = verified_user(client)
    newcomer.post("/api/community/setup")
    newcomer.post("/api/community/join")
    resp = members[1].post(f"/api/community/requests/{newcomer.user_id}/approve")
    assert resp.status_code == 403


def test_rejected_request_does_not_grant_membership(client, rep_community, verified_user):
    rep, _members = rep_community(size=4)
    newcomer = verified_user(client)
    newcomer.post("/api/community/setup")
    newcomer.post("/api/community/join")
    resp = rep.post(f"/api/community/requests/{newcomer.user_id}/reject",
                    json={"reason": "not in this class"})
    assert resp.status_code == 200
    assert newcomer.get("/api/community").status_code == 403
    assert newcomer.get("/api/auth/me").get_json()["next_step"] == "community_setup"


def test_rep_of_another_community_cannot_approve(client, rep_community, verified_user):
    """Rep authority is scoped to one community (spec 5)."""
    rep_a, _ = rep_community(size=4)
    rep_b, _ = rep_community(size=4, department="Computer Science")
    rep_a.relogin()
    newcomer = verified_user(client, department="Computer Science")
    newcomer.post("/api/community/setup")
    newcomer.post("/api/community/join")
    resp = rep_a.post(f"/api/community/requests/{newcomer.user_id}/approve")
    assert resp.status_code == 404
