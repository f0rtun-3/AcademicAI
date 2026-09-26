"""Rep verification ballots (spec 8, 11)."""
from datetime import timedelta

import pytest

from academicai import clock


def test_nomination_grants_no_authority(client, community):
    """Nomination never grants authority (spec 11)."""
    members = community(client, size=4)
    candidate = members[0]
    resp = candidate.post("/api/rep/nominate", json={"candidate_id": candidate.user_id})
    assert resp.status_code == 201
    assert resp.get_json()["nomination"]["status"] == "OPEN"
    # Still only a student: a rep-only endpoint must refuse.
    assert candidate.get("/api/community/requests").status_code == 403


def test_first_election_requires_enough_eligible_voters(client, community):
    """A ballot needs 3 voters besides the candidate, so 4 eligible members
    in total (spec 8, 11). Fully covered in test_election_eligibility.py."""
    members = community(client, size=2)
    resp = members[0].post("/api/rep/nominate", json={"candidate_id": members[0].user_id})
    assert resp.status_code == 409
    assert resp.get_json()["details"]["required_members"] == 4


def test_successful_ballot_promotes_and_activates_community(
        client, community, elect_rep, run_worker):
    members = community(client, size=4)
    nomination_id = elect_rep(client, members)
    clock.advance(timedelta(hours=25))
    run_worker()

    rep = members[0].relogin()
    results = rep.get(f"/api/rep/candidates/{nomination_id}/results").get_json()["results"]
    assert results["status"] == "PASSED"
    assert results["yes_votes"] == 3
    # First verified rep activates the PENDING community (spec 8, 11).
    assert rep.get("/api/community").get_json()["community"]["status"] == "ACTIVE"
    assert rep.get("/api/community").get_json()["membership"]["role"] == "VERIFIED_REP"
    assert rep.get("/api/community/requests").status_code == 200


def test_candidate_cannot_vote_for_themselves(client, community):
    members = community(client, size=4)
    candidate = members[0]
    nomination_id = candidate.post(
        "/api/rep/nominate", json={"candidate_id": candidate.user_id}
    ).get_json()["nomination"]["id"]
    resp = candidate.post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": "YES"})
    assert resp.status_code == 403


def test_one_vote_per_voter(client, community):
    members = community(client, size=4)
    nomination_id = members[0].post(
        "/api/rep/nominate", json={"candidate_id": members[0].user_id}
    ).get_json()["nomination"]["id"]
    assert members[1].post(f"/api/rep/candidates/{nomination_id}/vote",
                           json={"vote": "YES"}).status_code == 201
    assert members[1].post(f"/api/rep/candidates/{nomination_id}/vote",
                           json={"vote": "NO"}).status_code == 409


def test_ballot_fails_with_too_few_votes(client, community, run_worker):
    members = community(client, size=4)
    nomination_id = members[0].post(
        "/api/rep/nominate", json={"candidate_id": members[0].user_id}
    ).get_json()["nomination"]["id"]
    members[1].post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": "YES"})
    members[2].post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": "YES"})
    clock.advance(timedelta(hours=25))
    run_worker()
    results = members[1].relogin().get(
        f"/api/rep/candidates/{nomination_id}/results").get_json()["results"]
    assert results["status"] == "FAILED"


def test_tie_fails(client, community, elect_rep, run_worker):
    members = community(client, size=5)
    nomination_id = elect_rep(client, members, votes=["YES", "NO", "YES", "NO"])
    clock.advance(timedelta(hours=25))
    run_worker()
    results = members[1].relogin().get(
        f"/api/rep/candidates/{nomination_id}/results").get_json()["results"]
    assert results["status"] == "FAILED"
    assert results["yes_votes"] == results["no_votes"] == 2


def test_majority_no_fails(client, community, elect_rep, run_worker):
    members = community(client, size=5)
    nomination_id = elect_rep(client, members, votes=["NO", "NO", "YES"])
    clock.advance(timedelta(hours=25))
    run_worker()
    results = members[1].relogin().get(
        f"/api/rep/candidates/{nomination_id}/results").get_json()["results"]
    assert results["status"] == "FAILED"


def test_voting_closes_after_24_hours(client, community):
    members = community(client, size=4)
    nomination_id = members[0].post(
        "/api/rep/nominate", json={"candidate_id": members[0].user_id}
    ).get_json()["nomination"]["id"]
    clock.advance(timedelta(hours=25))
    voter = members[1].relogin()
    resp = voter.post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": "YES"})
    assert resp.status_code == 409


def test_failed_candidate_has_seven_day_cooldown(client, community, elect_rep, run_worker):
    members = community(client, size=5)
    elect_rep(client, members, votes=["NO", "NO", "YES"])
    clock.advance(timedelta(hours=25))
    run_worker()
    candidate = members[0].relogin()
    resp = candidate.post("/api/rep/nominate", json={"candidate_id": candidate.user_id})
    assert resp.status_code == 409
    clock.advance(timedelta(days=8))
    candidate.relogin()
    assert candidate.post("/api/rep/nominate",
                          json={"candidate_id": candidate.user_id}).status_code == 201


def test_maximum_three_reps_per_community(client, community, elect_rep, run_worker):
    members = community(client, size=8)
    for i in range(3):
        elect_rep(client, members, candidate=members[i])
        clock.advance(timedelta(hours=25))
        run_worker()
        for m in members:
            m.relogin()
    resp = members[3].post("/api/rep/nominate", json={"candidate_id": members[3].user_id})
    assert resp.status_code == 409
    assert "3 verified reps" in resp.get_json()["message"]


def test_student_cannot_nominate_another_student(client, community):
    members = community(client, size=4)
    resp = members[0].post("/api/rep/nominate", json={"candidate_id": members[1].user_id})
    assert resp.status_code == 403


def test_rep_can_nominate_another_student(client, rep_community):
    rep, members = rep_community(size=5)
    resp = rep.post("/api/rep/nominate", json={"candidate_id": members[1].user_id})
    assert resp.status_code == 201


def test_non_member_cannot_vote(client, rep_community, joined_user):
    rep, members = rep_community(size=5)
    nomination_id = rep.post(
        "/api/rep/nominate", json={"candidate_id": members[1].user_id}
    ).get_json()["nomination"]["id"]
    outsider = joined_user(client, department="Computer Science")
    resp = outsider.post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": "YES"})
    assert resp.status_code == 403


def test_ballot_closing_is_idempotent(client, community, elect_rep, run_worker, app):
    """Running the worker twice must not promote twice or duplicate notices (spec 21)."""
    members = community(client, size=4)
    nomination_id = elect_rep(client, members)
    clock.advance(timedelta(hours=25))
    run_worker()
    with app.app_context():
        from academicai.db.connection import query_all, query_one
        history_first = query_all(
            "SELECT * FROM change_history WHERE entity_type = 'rep_nomination' AND entity_id = ?",
            (nomination_id,))
        notices_first = query_all("SELECT * FROM notifications")
    run_worker()
    run_worker()
    with app.app_context():
        from academicai.db.connection import query_all, query_one
        history_after = query_all(
            "SELECT * FROM change_history WHERE entity_type = 'rep_nomination' AND entity_id = ?",
            (nomination_id,))
        notices_after = query_all("SELECT * FROM notifications")
        reps = query_one(
            """SELECT COUNT(*) AS n FROM community_members
               WHERE community_id = ? AND role = 'VERIFIED_REP' AND status = 'ACTIVE'""",
            (members[0].community_id,))
    assert len(history_after) == len(history_first)
    assert len(notices_after) == len(notices_first)
    assert reps["n"] == 1
