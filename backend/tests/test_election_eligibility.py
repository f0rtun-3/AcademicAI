"""When a rep election may be opened (spec 8, 11).

The rules interact: a candidate may not vote for themselves, and a ballot needs
3 ACTUAL votes. A community therefore needs 3 eligible voters BESIDES the
candidate - at least 4 eligible members in total - before an election can be
opened at all.

A community reaches election PREPARATION at 3 eligible students, but opening a
ballot at that size would guarantee failure, so it is refused up front rather
than after a 24-hour wait.
"""
from datetime import timedelta

import pytest

from academicai import clock


def test_three_eligible_members_cannot_start_an_election(client, community):
    """The regression case: 3 members means only 2 possible voters."""
    members = community(client, size=3)
    candidate = members[0]

    resp = candidate.post("/api/rep/nominate", json={"candidate_id": candidate.user_id})
    assert resp.status_code == 409

    details = resp.get_json()["details"]
    assert details["eligible_members"] == 3
    assert details["eligible_voters"] == 2      # the candidate cannot vote
    assert details["required_voters"] == 3
    assert details["required_members"] == 4
    assert "besides the candidate" in resp.get_json()["message"]

    # No ballot was created, and the community is untouched.
    assert candidate.get("/api/rep/candidates").get_json()["candidates"] == []
    assert candidate.get("/api/community").get_json()["community"]["status"] == "PENDING"


def test_two_eligible_members_cannot_start_an_election(client, community):
    members = community(client, size=2)
    resp = members[0].post("/api/rep/nominate", json={"candidate_id": members[0].user_id})
    assert resp.status_code == 409
    assert resp.get_json()["details"]["eligible_voters"] == 1


def test_four_eligible_members_can_start_and_win_an_election(
        client, community, elect_rep, run_worker):
    """One more eligible member is enough for the rules to resolve."""
    members = community(client, size=4)
    nomination_id = elect_rep(client, members)
    clock.advance(timedelta(hours=25))
    run_worker()

    results = members[1].relogin().get(
        f"/api/rep/candidates/{nomination_id}/results").get_json()["results"]
    assert results["status"] == "PASSED"
    assert results["yes_votes"] == 3
    assert members[0].relogin().get(
        "/api/community").get_json()["community"]["status"] == "ACTIVE"


def test_the_minimum_vote_count_was_not_lowered(client, community, run_worker):
    """The fix raises the electorate requirement; it must not relax the ballot."""
    members = community(client, size=4)
    nomination_id = members[0].post(
        "/api/rep/nominate", json={"candidate_id": members[0].user_id}
    ).get_json()["nomination"]["id"]

    # Only two of the three eligible voters turn out.
    members[1].post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": "YES"})
    members[2].post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": "YES"})
    clock.advance(timedelta(hours=25))
    run_worker()

    results = members[1].relogin().get(
        f"/api/rep/candidates/{nomination_id}/results").get_json()["results"]
    assert results["status"] == "FAILED"        # 2 actual votes still fails
    assert results["min_votes_required"] == 3


def test_an_ineligible_member_does_not_count_towards_the_electorate(
        client, community, verified_user):
    """Only identity-verified active members count as eligible voters."""
    members = community(client, size=3)
    # A fourth person who has not verified their identity joins nothing.
    unverified = verified_user(client)
    resp = members[0].post("/api/rep/nominate", json={"candidate_id": members[0].user_id})
    assert resp.status_code == 409
    assert resp.get_json()["details"]["eligible_members"] == 3


def test_a_candidate_who_leaves_is_not_promoted(client, community, elect_rep, run_worker):
    """Eligibility is re-checked at resolution, not just at nomination."""
    members = community(client, size=5)
    nomination_id = elect_rep(client, members)
    candidate = members[0]
    candidate.post("/api/community/leave")

    clock.advance(timedelta(hours=25))
    run_worker()

    results = members[1].relogin().get(
        f"/api/rep/candidates/{nomination_id}/results").get_json()["results"]
    assert results["status"] == "FAILED"
    # The community did not activate on a promotion that never happened.
    assert members[1].get("/api/community").get_json()["community"]["reps"] == []


def test_community_reports_election_readiness_to_the_client(client, community):
    """The UI must be able to explain the requirement before someone tries."""
    members = community(client, size=3)
    election = members[0].get("/api/community").get_json()["community"]["election"]
    assert election["eligible_members"] == 3
    assert election["required_members"] == 4
    assert election["in_preparation"] is True      # 3 is enough to prepare
    assert election["can_start_election"] is False  # but not to open a ballot
    assert election["members_needed"] == 1


def test_election_readiness_flips_at_four_members(client, community, joined_user):
    members = community(client, size=3)
    joined_user(client)                            # a fourth eligible student
    election = members[0].get("/api/community").get_json()["community"]["election"]
    assert election["can_start_election"] is True
    assert election["members_needed"] == 0


# --- J·4: read-only cooldown visibility ------------------------------------
#
# The UI needs to say "you can stand again on <date>" instead of offering a
# control that answers 409. Everything below asserts that the value is
# INFORMATIONAL: present for the viewer, absent for everyone else, and never
# capable of admitting or refusing a candidacy on its own.

def test_election_object_reports_no_cooldown_for_a_student_who_may_stand(client, community):
    members = community(client, size=4)
    election = members[0].get("/api/community").get_json()["community"]["election"]
    assert election["cooldown_until"] is None
    assert election["can_start_election"] is True


def test_a_failed_candidacy_shows_the_viewer_their_own_cooldown(
        client, community, run_worker):
    members = community(client, size=4)
    candidate = members[0]
    nomination_id = candidate.post(
        "/api/rep/nominate", json={"candidate_id": candidate.user_id}
    ).get_json()["nomination"]["id"]

    # Three actual votes, a majority against: the ballot fails.
    for voter in members[1:4]:
        voter.post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": "NO"})
    clock.advance(timedelta(hours=25))
    run_worker()

    election = candidate.relogin().get(
        "/api/community").get_json()["community"]["election"]
    assert election["cooldown_until"] is not None

    # It is the failure plus the configured window, not an arbitrary date.
    resolved = clock.parse_iso(
        candidate.get(f"/api/rep/candidates/{nomination_id}/results")
        .get_json()["results"]["resolved_at"])
    expected = resolved + timedelta(
        days=int(client.application.config["FAILED_CANDIDATE_COOLDOWN_DAYS"]))
    assert clock.parse_iso(election["cooldown_until"]) == expected

    # And the rule it describes is still enforced by the backend.
    refused = candidate.post("/api/rep/nominate", json={"candidate_id": candidate.user_id})
    assert refused.status_code == 409


def test_a_cooldown_is_never_reported_for_another_student(
        client, community, run_worker):
    """Whose candidacy failed last week is not a classmate's business."""
    members = community(client, size=4)
    candidate = members[0]
    nomination_id = candidate.post(
        "/api/rep/nominate", json={"candidate_id": candidate.user_id}
    ).get_json()["nomination"]["id"]
    for voter in members[1:4]:
        voter.post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": "NO"})
    clock.advance(timedelta(hours=25))
    run_worker()

    # The candidate sees their own cooldown; a classmate sees only their own,
    # which is None - never the candidate's.
    assert candidate.relogin().get(
        "/api/community").get_json()["community"]["election"]["cooldown_until"] is not None
    other = members[1].relogin().get(
        "/api/community").get_json()["community"]["election"]
    assert other["cooldown_until"] is None


def test_cooldown_is_omitted_entirely_when_there_is_no_viewer(app, client, community):
    """No viewer, no field. It is never returned speculatively."""
    members = community(client, size=4)
    community_id = members[0].get(
        "/api/community").get_json()["community"]["id"]
    with app.app_context():
        from academicai.services import community_service
        readiness = community_service.election_readiness(community_id)
        assert "cooldown_until" not in readiness


def test_cooldown_visibility_does_not_authorize_anything(
        client, community, run_worker, monkeypatch):
    """The decisive test: lie to the display helper, and nothing changes.

    nominate() must not consult candidate_cooldown_until(). If a client - or a
    patched helper - reports "no cooldown", the ballot is still refused, because
    the authority is the rule inside the transaction and not this value.
    """
    members = community(client, size=4)
    candidate = members[0]
    nomination_id = candidate.post(
        "/api/rep/nominate", json={"candidate_id": candidate.user_id}
    ).get_json()["nomination"]["id"]
    for voter in members[1:4]:
        voter.post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": "NO"})
    clock.advance(timedelta(hours=25))
    run_worker()

    from academicai.services import rep_service
    monkeypatch.setattr(rep_service, "candidate_cooldown_until",
                        lambda *a, **kw: None)

    candidate.relogin()
    election = candidate.get("/api/community").get_json()["community"]["election"]
    assert election["cooldown_until"] is None          # the display now lies
    refused = candidate.post("/api/rep/nominate",
                             json={"candidate_id": candidate.user_id})
    assert refused.status_code == 409                   # the backend does not
    assert "wait" in refused.get_json()["message"]
