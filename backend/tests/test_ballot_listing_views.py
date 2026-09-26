"""Ballot listings carry the caller's own vote state (spec 11, 12).

The listings tell a client what it may do so the UI need not guess, but the
hint is not a permission: cast_vote re-checks eligibility itself. These tests
hold both halves - the hint is accurate, and acting against it still fails.
"""
from datetime import timedelta

import pytest

from academicai import clock

pytestmark = pytest.mark.security


def _open_ballot(setup, candidate):
    resp = setup.rep.post("/api/rep/nominate", json={"candidate_id": candidate.user_id})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["nomination"]["id"]


def _candidate_view(actor, nomination_id):
    rows = actor.get("/api/rep/candidates").get_json()["candidates"]
    return next(r for r in rows if r["id"] == nomination_id)


def _removal_view(actor, removal_id):
    rows = actor.get("/api/rep/removals").get_json()["removals"]
    return next(r for r in rows if r["id"] == removal_id)


# --- Candidacy listing ----------------------------------------------------

def test_listing_reports_tally_and_requirement(client, academic_community):
    setup = academic_community(size=6, seed_events=False)
    nomination_id = _open_ballot(setup, setup.members[1])

    view = _candidate_view(setup.members[2], nomination_id)
    assert view["status"] == "OPEN"
    assert view["yes_votes"] == 0 and view["no_votes"] == 0
    assert view["min_votes_required"] == 3
    assert view["can_vote"] is True
    assert view["my_vote"] is None
    assert view["is_me"] is False


def test_listing_marks_the_candidate_and_forbids_self_voting(client, academic_community):
    setup = academic_community(size=6, seed_events=False)
    candidate = setup.members[1]
    nomination_id = _open_ballot(setup, candidate)

    view = _candidate_view(candidate, nomination_id)
    assert view["is_me"] is True
    assert view["can_vote"] is False
    # And the hint matches what the backend actually enforces.
    assert candidate.post(f"/api/rep/candidates/{nomination_id}/vote",
                          json={"vote": "YES"}).status_code == 403


def test_listing_records_how_the_caller_voted(client, academic_community):
    setup = academic_community(size=6, seed_events=False)
    nomination_id = _open_ballot(setup, setup.members[1])
    voter = setup.members[2]

    assert voter.post(f"/api/rep/candidates/{nomination_id}/vote",
                      json={"vote": "NO"}).status_code == 201

    view = _candidate_view(voter, nomination_id)
    assert view["my_vote"] == "NO"
    assert view["can_vote"] is False
    assert view["no_votes"] == 1
    # A second vote is still refused by the backend.
    assert voter.post(f"/api/rep/candidates/{nomination_id}/vote",
                      json={"vote": "YES"}).status_code == 409


def test_each_member_sees_only_their_own_vote_state(client, academic_community):
    setup = academic_community(size=6, seed_events=False)
    nomination_id = _open_ballot(setup, setup.members[1])
    voted, not_voted = setup.members[2], setup.members[3]
    voted.post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": "YES"})

    assert _candidate_view(voted, nomination_id)["my_vote"] == "YES"
    assert _candidate_view(not_voted, nomination_id)["my_vote"] is None
    assert _candidate_view(not_voted, nomination_id)["can_vote"] is True


def test_an_expired_ballot_offers_no_vote(client, academic_community):
    setup = academic_community(size=6, seed_events=False)
    nomination_id = _open_ballot(setup, setup.members[1])
    clock.advance(timedelta(hours=25))
    voter = setup.members[2].relogin()

    assert _candidate_view(voter, nomination_id)["can_vote"] is False
    assert voter.post(f"/api/rep/candidates/{nomination_id}/vote",
                      json={"vote": "YES"}).status_code == 409


def test_a_resolved_ballot_reports_its_final_counts(client, academic_community, run_worker):
    setup = academic_community(size=6, seed_events=False)
    nomination_id = _open_ballot(setup, setup.members[1])
    for voter in setup.members[2:5]:
        voter.post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": "YES"})
    clock.advance(timedelta(hours=25))
    run_worker()

    view = _candidate_view(setup.members[2].relogin(), nomination_id)
    assert view["status"] == "PASSED"
    assert view["yes_votes"] == 3 and view["no_votes"] == 0
    assert view["can_vote"] is False
    assert view["resolved_at"] is not None


# --- Removal listing ------------------------------------------------------

def _open_removal(setup, run_worker):
    """Seat a second rep so one rep can open a removal against the other."""
    second = setup.members[1]
    nomination_id = _open_ballot(setup, second)
    for voter in setup.members[2:5]:
        voter.post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": "YES"})
    clock.advance(timedelta(hours=25))
    run_worker()
    second.relogin()
    resp = second.post("/api/rep/removals", json={"target_user_id": setup.rep.user_id})
    assert resp.status_code == 201, resp.get_json()
    return second, resp.get_json()["removal"]["id"]


def test_removal_listing_reports_tally_and_self_state(client, academic_community, run_worker):
    setup = academic_community(size=7, seed_events=False)
    initiator, removal_id = _open_removal(setup, run_worker)

    voter = setup.members[2].relogin()
    view = _removal_view(voter, removal_id)
    assert view["status"] == "OPEN"
    assert view["min_votes_required"] == 3
    assert view["can_vote"] is True
    assert view["is_me"] is False


def test_the_removal_target_cannot_vote_and_the_listing_says_so(
        client, academic_community, run_worker):
    setup = academic_community(size=7, seed_events=False)
    initiator, removal_id = _open_removal(setup, run_worker)
    target = setup.rep.relogin()

    view = _removal_view(target, removal_id)
    assert view["is_me"] is True
    assert view["can_vote"] is False
    assert target.post(f"/api/rep/removals/{removal_id}/vote",
                       json={"vote": "NO"}).status_code == 403


def test_removal_listing_records_the_callers_vote(client, academic_community, run_worker):
    setup = academic_community(size=7, seed_events=False)
    initiator, removal_id = _open_removal(setup, run_worker)
    voter = setup.members[2].relogin()
    assert voter.post(f"/api/rep/removals/{removal_id}/vote",
                      json={"vote": "YES"}).status_code == 201

    view = _removal_view(voter, removal_id)
    assert view["my_vote"] == "YES"
    assert view["can_vote"] is False
    assert view["yes_votes"] == 1


def test_a_non_member_cannot_read_ballot_listings(client, academic_community, verified_user):
    """The listings are member-scoped, like everything else in a community."""
    setup = academic_community(size=6, seed_events=False)
    _open_ballot(setup, setup.members[1])
    outsider = verified_user(client)
    assert outsider.get("/api/rep/candidates").status_code == 403
    assert outsider.get("/api/rep/removals").status_code == 403


def test_ballot_listings_do_not_leak_other_communities(client, academic_community):
    setup_a = academic_community(size=6, seed_events=False)
    nomination_id = _open_ballot(setup_a, setup_a.members[1])
    setup_b = academic_community(size=4, department="Computer Science", seed_events=False)

    ids = [c["id"] for c in setup_b.rep.get("/api/rep/candidates").get_json()["candidates"]]
    assert nomination_id not in ids


# --- The bootstrap sequence the UI performs -------------------------------

def test_join_then_self_nominate_is_the_first_rep_path(client, verified_user, joined_user):
    """What "Yes, I'm a Course Rep" does: join, then stand.

    Nominating requires an ACTIVE membership, so the order matters.
    """
    others = [joined_user(client) for _ in range(3)]
    candidate = verified_user(client)

    # Standing before joining is refused.
    assert candidate.post("/api/rep/nominate", json={}).status_code == 403

    candidate.post("/api/community/setup")
    assert candidate.post("/api/community/join").status_code == 201
    resp = candidate.post("/api/rep/nominate", json={})
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["nomination"]["status"] == "OPEN"
    assert resp.get_json()["nomination"]["candidate_id"] == candidate.user_id


def test_standing_is_refused_but_membership_survives_when_too_small(client, joined_user,
                                                                    verified_user):
    """The UI reports the refusal and keeps the student as a member."""
    joined_user(client)
    candidate = verified_user(client)
    candidate.post("/api/community/setup")
    assert candidate.post("/api/community/join").status_code == 201

    resp = candidate.post("/api/rep/nominate", json={})
    assert resp.status_code == 409
    assert resp.get_json()["details"]["required_members"] == 4
    # Still an active member.
    assert candidate.get("/api/community").get_json()["membership"]["status"] == "ACTIVE"
