"""No endpoint may expose another user's private account or identity data.

Identity evidence, verification outcomes, email addresses and student ID
numbers belong to their owner and must not travel through community-facing
responses.
"""
import pytest

pytestmark = pytest.mark.security


def _all_member_facing_bodies(actor):
    paths = ("/api/auth/me", "/api/community", "/api/community/members",
             "/api/community/courses", "/api/community/timetable",
             "/api/community/announcements", "/api/community/changes",
             "/api/dashboard", "/api/calendar", "/api/events", "/api/reminders",
             "/api/rep/candidates", "/api/rep/removals", "/api/chat/prompts")
    return {p: actor.get(p).get_data(as_text=True) for p in paths}


def test_no_endpoint_exposes_another_users_email(client, academic_community):
    setup = academic_community(size=4)
    viewer, other = setup.members[1], setup.members[2]
    other_email = other.email
    assert other_email

    for path, body in _all_member_facing_bodies(viewer).items():
        assert other_email not in body, path


def test_no_endpoint_exposes_another_users_student_id_number(client, academic_community):
    setup = academic_community(size=4)
    viewer, other = setup.members[1], setup.members[2]
    other_sid = other.get("/api/auth/me").get_json()["user"]["student_id_number"]
    assert other_sid

    for path, body in _all_member_facing_bodies(viewer).items():
        assert other_sid not in body, path


def test_no_endpoint_exposes_another_users_identity_status(client, academic_community):
    """Whether someone's ID passed is their business, not the community's."""
    setup = academic_community(size=4)
    viewer = setup.members[1]
    members = viewer.get("/api/community/members").get_json()["members"]
    assert members
    for member in members:
        assert set(member) == {"user_id", "full_name", "role", "status"}
        assert "identity_status" not in member
        assert "email" not in member


def test_the_membership_request_queue_does_not_leak_private_fields(
        client, academic_community, verified_user):
    """Rep-only, and still minimal."""
    setup = academic_community(size=4, seed_events=False)
    newcomer = verified_user(client)
    newcomer.post("/api/community/setup")
    newcomer.post("/api/community/join")

    requests = setup.rep.get("/api/community/requests").get_json()["requests"]
    assert requests
    for entry in requests:
        assert set(entry) == {"user_id", "full_name", "requested_at"}
    body = setup.rep.get("/api/community/requests").get_data(as_text=True)
    assert newcomer.email not in body


def test_no_route_serves_identity_records_at_all(app):
    """Student ID-card verification is out of MVP scope: no route touches it.

    The legacy identity_verifications table and users.identity_status still
    exist in the schema, so this also guards against either being exposed by
    some future read endpoint.
    """
    paths = [str(r) for r in app.url_map.iter_rules()]
    for path in paths:
        assert "identity" not in path.lower(), path
        assert "evidence" not in path.lower(), path
        assert "ocr" not in path.lower(), path


def test_onboarding_returns_nothing_about_other_users(client, register):
    """Replaces the identity-submission isolation test.

    Onboarding responses must describe only the caller, no matter how many
    other accounts exist on the same community.
    """
    first = register(client)
    client.post("/api/auth/verify-email", json={"email": first.email, "code": first.otp})
    first.relogin()
    first.post("/api/community/setup")
    first.post("/api/community/join")

    second = register(client)
    client.post("/api/auth/verify-email", json={"email": second.email, "code": second.otp})
    second.relogin()

    for resp in (second.post("/api/community/setup"),
                 second.post("/api/community/join"),
                 second.get("/api/auth/me")):
        body = resp.get_data(as_text=True)
        assert first.email not in body
        assert first.full_name not in body


def test_me_reports_only_the_caller(client, academic_community):
    """No parameter can redirect /api/auth/me at another account."""
    setup = academic_community(size=4)
    viewer, other = setup.members[1], setup.members[2]

    for query in (f"?user_id={other.user_id}", f"?id={other.user_id}",
                  f"?email={other.email}"):
        body = viewer.get(f"/api/auth/me{query}").get_json()
        assert body["user"]["id"] == viewer.user_id
        assert body["user"]["email"] == viewer.email


def test_reminders_are_private_to_their_owner(client, academic_community):
    setup = academic_community(size=4)
    owner, snooper = setup.members[1], setup.members[2]
    owner.post("/api/reminders", json={"title": "my private note",
                                       "remind_at": "2026-09-25T08:00:00+00:00"})
    body = snooper.get("/api/reminders").get_data(as_text=True)
    assert "my private note" not in body
    assert snooper.get("/api/reminders").get_json()["reminders"] == []


def test_chat_history_is_private_to_its_owner(client, academic_community):
    setup = academic_community(size=4)
    owner, snooper = setup.members[1], setup.members[2]
    owner.post("/api/chat", json={"question": "what is my secret deadline?"})
    body = snooper.get("/api/chat/history").get_data(as_text=True)
    assert "secret deadline" not in body


# --- Forged client-side authorization fields -------------------------------

FORGED = {
    "role": "VERIFIED_REP",
    "is_rep": True,
    "verified": True,
    "email_verified": True,
    "identity_status": "VERIFIED",
    "authoritative": True,
    "membership_status": "ACTIVE",
    "user_id": 1,
    "actor_id": 1,
    "community_id": 1,
    "skip_domain_check": True,
    "bypass": True,
}


@pytest.mark.parametrize("path,base", [
    ("/api/events", {"title": "Forged", "event_type": "QUIZ"}),
    ("/api/community/announcements", {"title": "Forged", "body": "x"}),
    ("/api/community/courses", {"code": "FORGE1"}),
    ("/api/community/timetable", {"day_of_week": "MONDAY", "start_time": "09:00"}),
    ("/api/ai/publish", {"action": "CREATE", "scope": "EVENT", "title": "Forged",
                         "event_type": "QUIZ"}),
])
def test_forged_authorization_fields_do_not_grant_rep_powers(
        client, academic_community, path, base):
    setup = academic_community(size=5, seed_events=False)
    student = setup.members[1]
    payload = {**base, **FORGED}
    assert student.post(path, json=payload).status_code == 403


def test_forged_fields_do_not_promote_a_member_during_approval(
        client, academic_community, verified_user):
    """Approval must yield STUDENT regardless of what the request asks for."""
    setup = academic_community(size=4, seed_events=False)
    newcomer = verified_user(client)
    newcomer.post("/api/community/setup")
    newcomer.post("/api/community/join")

    resp = setup.rep.post(f"/api/community/requests/{newcomer.user_id}/approve",
                          json={"role": "VERIFIED_REP", "is_rep": True})
    assert resp.status_code == 200
    assert resp.get_json()["membership"]["role"] == "STUDENT"


def test_forged_vote_fields_cannot_decide_a_ballot(client, academic_community):
    setup = academic_community(size=6, seed_events=False)
    nomination_id = setup.rep.post(
        "/api/rep/nominate", json={"candidate_id": setup.members[1].user_id}
    ).get_json()["nomination"]["id"]

    # A single voter claiming a landslide.
    resp = setup.members[2].post(
        f"/api/rep/candidates/{nomination_id}/vote",
        json={"vote": "YES", "yes_votes": 99, "no_votes": 0, "status": "PASSED"})
    assert resp.status_code == 201
    results = setup.rep.get(
        f"/api/rep/candidates/{nomination_id}/results").get_json()["results"]
    assert results["yes_votes"] == 1
    assert results["status"] == "OPEN"


def test_a_student_cannot_self_promote_by_voting_for_themselves(client, academic_community):
    setup = academic_community(size=6, seed_events=False)
    candidate = setup.members[1]
    nomination_id = candidate.post(
        "/api/rep/nominate", json={"candidate_id": candidate.user_id}
    ).get_json()["nomination"]["id"]
    assert candidate.post(f"/api/rep/candidates/{nomination_id}/vote",
                          json={"vote": "YES"}).status_code == 403
