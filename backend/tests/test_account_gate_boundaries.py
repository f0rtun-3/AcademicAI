"""An account that is not email-verified must not grant anything (spec 6, 23).

This file replaces test_identity_boundaries.py. Student ID-card verification
is out of MVP scope, so NEEDS_REVIEW and REJECTED no longer gate anything -
but every BOUNDARY that file protected still matters, and each one now hangs
off the account gate that remains: a confirmed email address on the selected
university's approved institutional domain.

The boundaries checked here are the same ones the product names: joining an
active community, reading protected community data, publishing official
information, and being promoted to verified rep.

What this file deliberately does NOT test: that anybody's identity was
verified. Nothing in the MVP establishes that.
"""
import pytest

pytestmark = pytest.mark.security


def _email_verified_only(client, register):
    actor = register(client)
    client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
    return actor.relogin()


def _unverified(client, register):
    """Registered, logged in, email NOT confirmed."""
    actor = register(client)
    resp = client.post("/api/auth/login",
                       json={"email": actor.email, "password": "Password123"})
    assert resp.status_code == 200, resp.get_json()
    actor.token = resp.get_json()["token"]
    return actor


# --- an unverified email cannot join --------------------------------------

def test_an_unverified_email_cannot_reach_community_setup(client, register, rep_community):
    rep_community(size=4)
    actor = _unverified(client, register)
    for path in ("/api/community/setup", "/api/community/join", "/api/community/transfer"):
        resp = actor.post(path)
        assert resp.status_code == 403, path
        assert "Email verification" in resp.get_json()["message"]


def test_an_unverified_email_cannot_read_the_dashboard(client, register, rep_community):
    rep_community(size=4)
    actor = _unverified(client, register)
    assert actor.get("/api/dashboard").status_code == 403


def test_email_verification_grants_the_gate_and_nothing_further(
        client, register, rep_community):
    """The replacement gate opens onboarding - it does not confer membership.

    This is the test that would catch the mistake of "removing ID verification"
    by quietly handing everyone community access. A verified email lets the
    student ASK to join; an existing community still has to approve them, and
    until it does they are not a member and read nothing.
    """
    rep_community(size=4)
    actor = _email_verified_only(client, register)

    assert actor.post("/api/community/setup").status_code in (200, 201)
    joined = actor.post("/api/community/join")
    assert joined.status_code == 201
    # An ACTIVE community admits nobody automatically.
    assert joined.get_json()["awaiting_approval"] is True
    assert joined.get_json()["membership"]["status"] == "PENDING_APPROVAL"

    # Still not a member, so protected data stays closed.
    assert actor.get("/api/dashboard").status_code == 403
    assert actor.get("/api/community/members").status_code == 403
    assert actor.get("/api/events").status_code == 403


def test_a_verified_email_is_never_reported_as_a_verified_identity(client, register):
    """No payload may imply AcademicAI established who the student is."""
    actor = _email_verified_only(client, register)
    payload = actor.get("/api/auth/me").get_json()
    assert payload["user"]["email_verified"] is True
    assert "identity_status" not in payload["user"]
    assert "identity_check" not in payload
    body = actor.get("/api/auth/me").get_data(as_text=True).lower()
    for claim in ("identity_verified", "identity_status", "id_card", "authoritative"):
        assert claim not in body


# --- losing the gate closes protected data --------------------------------

def test_a_member_losing_email_verification_loses_protected_community_data(
        client, academic_community, unverified_email_member):
    setup = academic_community()
    member = unverified_email_member(setup.members[1])

    for path in ("/api/community", "/api/community/members", "/api/community/courses",
                 "/api/community/timetable", "/api/community/announcements",
                 "/api/community/changes", "/api/events", "/api/dashboard",
                 "/api/calendar"):
        resp = member.get(path)
        assert resp.status_code == 403, path


def test_a_member_losing_email_verification_cannot_use_ai_or_chat(
        client, academic_community, unverified_email_member):
    setup = academic_community()
    member = unverified_email_member(setup.members[1])
    assert member.post("/api/ai/analyze-message",
                       json={"message": "quiz on friday"}).status_code == 403
    assert member.post("/api/chat", json={"question": "what is due?"}).status_code == 403


def test_a_member_losing_email_verification_cannot_read_a_specific_event(
        client, academic_community, unverified_email_member):
    setup = academic_community()
    event_id = setup.cos202_assignment["id"]
    member = unverified_email_member(setup.members[1])
    assert member.get(f"/api/events/{event_id}").status_code == 403


# --- losing the gate removes authority ------------------------------------

def test_a_rep_losing_email_verification_cannot_publish(
        client, academic_community, unverified_email_member):
    """Rep authority is re-read live, so it lapses on the very next request."""
    setup = academic_community(seed_events=False)
    rep = unverified_email_member(setup.rep)

    assert rep.post("/api/events", json={"title": "x", "event_type": "QUIZ"}).status_code == 403
    assert rep.post("/api/ai/publish", json={
        "action": "CREATE", "scope": "EVENT", "title": "Sneaky",
        "event_type": "QUIZ"}).status_code == 403
    assert rep.post("/api/community/announcements",
                    json={"title": "x", "body": "y"}).status_code == 403


def test_a_rep_losing_email_verification_cannot_approve_membership(
        client, academic_community, unverified_email_member, verified_user):
    setup = academic_community(seed_events=False)
    newcomer = verified_user(client)
    newcomer.post("/api/community/setup")
    newcomer.post("/api/community/join")

    rep = unverified_email_member(setup.rep)
    assert rep.post(f"/api/community/requests/{newcomer.user_id}/approve").status_code == 403


def test_a_member_losing_email_verification_cannot_be_nominated(
        client, academic_community, unverified_email_member):
    setup = academic_community(size=6, seed_events=False)
    candidate = unverified_email_member(setup.members[1])
    resp = setup.rep.post("/api/rep/nominate", json={"candidate_id": candidate.user_id})
    assert resp.status_code == 400


def test_a_member_losing_email_verification_cannot_vote(
        client, academic_community, unverified_email_member):
    setup = academic_community(size=6, seed_events=False)
    nomination_id = setup.rep.post(
        "/api/rep/nominate", json={"candidate_id": setup.members[1].user_id}
    ).get_json()["nomination"]["id"]
    voter = unverified_email_member(setup.members[2])
    assert voter.post(f"/api/rep/candidates/{nomination_id}/vote",
                      json={"vote": "YES"}).status_code == 403


def test_a_candidate_losing_the_account_gate_is_not_promoted(
        client, academic_community, unverified_email_member, run_worker):
    """Eligibility is re-checked when the ballot closes, not only when it opens.

    Carried over from the identity version of this test. The votes were real
    and are still counted as cast; what fails is the candidate's eligibility at
    the moment of promotion, which is exactly the property worth keeping.
    """
    from datetime import timedelta

    from academicai import clock

    setup = academic_community(size=6, seed_events=False)
    candidate = setup.members[1]
    nomination_id = setup.rep.post(
        "/api/rep/nominate", json={"candidate_id": candidate.user_id}
    ).get_json()["nomination"]["id"]
    for voter in setup.members[2:5]:
        assert voter.post(f"/api/rep/candidates/{nomination_id}/vote",
                          json={"vote": "YES"}).status_code == 201

    unverified_email_member(candidate)
    clock.advance(timedelta(hours=25))
    run_worker()

    results = setup.rep.relogin().get(
        f"/api/rep/candidates/{nomination_id}/results").get_json()["results"]
    assert results["status"] == "FAILED"
    assert results["yes_votes"] == 3            # the votes were real; eligibility was not


def test_removing_id_verification_did_not_make_anyone_a_rep(
        client, academic_community, verified_user):
    """The headline risk of this scope change, asserted directly.

    A brand-new email-verified student must be a STUDENT with no authority.
    Becoming a rep still requires the whole election: nomination, a 24h ballot,
    three actual votes and a YES majority.
    """
    setup = academic_community(size=4, seed_events=False)
    newcomer = verified_user(client)
    newcomer.post("/api/community/setup")
    newcomer.post("/api/community/join")

    assert newcomer.get("/api/auth/me").get_json()["membership"] is None
    # No publishing, no course management, no approvals.
    assert newcomer.post("/api/events",
                         json={"title": "x", "event_type": "QUIZ"}).status_code == 403
    assert newcomer.post("/api/community/courses",
                         json={"code": "COS999", "title": "x"}).status_code == 403
    assert newcomer.post(
        f"/api/community/requests/{setup.members[1].user_id}/approve").status_code == 403


def test_an_approved_member_is_a_student_not_a_rep(client, academic_community):
    """Approval grants membership only - never a role."""
    setup = academic_community(size=4, seed_events=False)
    member = setup.members[1]
    payload = member.get("/api/auth/me").get_json()
    assert payload["membership"]["status"] == "ACTIVE"
    assert payload["membership"]["role"] == "STUDENT"
    assert member.post("/api/community/announcements",
                       json={"title": "x", "body": "y"}).status_code == 403
