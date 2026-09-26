"""Rep removal ballots (spec 12)."""
from datetime import timedelta

from academicai import clock


def _two_reps(client, rep_community, elect_rep, run_worker):
    rep_a, members = rep_community(size=6)
    elect_rep(client, members, candidate=members[1])
    clock.advance(timedelta(hours=25))
    run_worker()
    for m in members:
        m.relogin()
    return members[0], members[1], members


def test_only_a_rep_can_open_a_removal(client, rep_community):
    rep, members = rep_community(size=5)
    resp = members[1].post("/api/rep/removals", json={"target_user_id": rep.user_id})
    assert resp.status_code == 403


def test_rep_cannot_remove_themselves(client, rep_community):
    rep, _members = rep_community(size=5)
    resp = rep.post("/api/rep/removals", json={"target_user_id": rep.user_id})
    assert resp.status_code == 400


def test_target_must_be_a_rep(client, rep_community):
    rep, members = rep_community(size=5)
    resp = rep.post("/api/rep/removals", json={"target_user_id": members[1].user_id})
    assert resp.status_code == 400


def test_rep_can_open_removal_against_another_rep(client, rep_community, elect_rep, run_worker):
    rep_a, rep_b, _ = _two_reps(client, rep_community, elect_rep, run_worker)
    resp = rep_a.post("/api/rep/removals", json={"target_user_id": rep_b.user_id})
    assert resp.status_code == 201
    assert resp.get_json()["removal"]["status"] == "OPEN"


def test_target_cannot_vote_on_own_removal(client, rep_community, elect_rep, run_worker):
    rep_a, rep_b, _ = _two_reps(client, rep_community, elect_rep, run_worker)
    removal_id = rep_a.post("/api/rep/removals",
                            json={"target_user_id": rep_b.user_id}).get_json()["removal"]["id"]
    assert rep_b.post(f"/api/rep/removals/{removal_id}/vote",
                      json={"vote": "NO"}).status_code == 403


def test_electorate_is_all_members_not_just_reps(client, rep_community, elect_rep, run_worker):
    """Eligible voters are all verified active members except the target (spec 12)."""
    rep_a, rep_b, members = _two_reps(client, rep_community, elect_rep, run_worker)
    ordinary = [m for m in members if m.user_id not in (rep_a.user_id, rep_b.user_id)]
    removal_id = rep_a.post("/api/rep/removals",
                            json={"target_user_id": rep_b.user_id}).get_json()["removal"]["id"]
    for student in ordinary[:3]:
        resp = student.post(f"/api/rep/removals/{removal_id}/vote", json={"vote": "YES"})
        assert resp.status_code == 201, resp.get_json()


def test_successful_removal_revokes_authority_but_keeps_membership(
        client, rep_community, elect_rep, run_worker):
    rep_a, rep_b, members = _two_reps(client, rep_community, elect_rep, run_worker)
    removal_id = rep_a.post("/api/rep/removals",
                            json={"target_user_id": rep_b.user_id}).get_json()["removal"]["id"]
    voters = [m for m in members if m.user_id != rep_b.user_id][:3]
    for v in voters:
        v.post(f"/api/rep/removals/{removal_id}/vote", json={"vote": "YES"})
    clock.advance(timedelta(hours=25))
    run_worker()

    removed = rep_b.relogin()
    community = removed.get("/api/community").get_json()
    assert community["membership"]["status"] == "ACTIVE"   # still a member
    assert community["membership"]["role"] == "STUDENT"    # authority revoked
    assert removed.get("/api/community/requests").status_code == 403


def test_removal_fails_on_tie(client, rep_community, elect_rep, run_worker):
    rep_a, rep_b, members = _two_reps(client, rep_community, elect_rep, run_worker)
    removal_id = rep_a.post("/api/rep/removals",
                            json={"target_user_id": rep_b.user_id}).get_json()["removal"]["id"]
    voters = [m for m in members if m.user_id != rep_b.user_id][:4]
    for v, vote in zip(voters, ["YES", "YES", "NO", "NO"]):
        v.post(f"/api/rep/removals/{removal_id}/vote", json={"vote": vote})
    clock.advance(timedelta(hours=25))
    run_worker()
    results = rep_a.relogin().get(f"/api/rep/removals/{removal_id}/results").get_json()["results"]
    assert results["status"] == "FAILED"
    assert rep_b.relogin().get("/api/community").get_json()["membership"]["role"] == "VERIFIED_REP"


def test_removal_fails_with_too_few_votes(client, rep_community, elect_rep, run_worker):
    rep_a, rep_b, members = _two_reps(client, rep_community, elect_rep, run_worker)
    removal_id = rep_a.post("/api/rep/removals",
                            json={"target_user_id": rep_b.user_id}).get_json()["removal"]["id"]
    voters = [m for m in members if m.user_id != rep_b.user_id][:2]
    for v in voters:
        v.post(f"/api/rep/removals/{removal_id}/vote", json={"vote": "YES"})
    clock.advance(timedelta(hours=25))
    run_worker()
    results = rep_a.relogin().get(f"/api/rep/removals/{removal_id}/results").get_json()["results"]
    assert results["status"] == "FAILED"


def test_failed_removal_blocks_retry_for_seven_days(client, rep_community, elect_rep, run_worker):
    rep_a, rep_b, members = _two_reps(client, rep_community, elect_rep, run_worker)
    removal_id = rep_a.post("/api/rep/removals",
                            json={"target_user_id": rep_b.user_id}).get_json()["removal"]["id"]
    voters = [m for m in members if m.user_id != rep_b.user_id][:3]
    for v in voters:
        v.post(f"/api/rep/removals/{removal_id}/vote", json={"vote": "NO"})
    clock.advance(timedelta(hours=25))
    run_worker()
    rep_a.relogin()
    assert rep_a.post("/api/rep/removals",
                      json={"target_user_id": rep_b.user_id}).status_code == 409
    clock.advance(timedelta(days=8))
    rep_a.relogin()
    assert rep_a.post("/api/rep/removals",
                      json={"target_user_id": rep_b.user_id}).status_code == 201


def test_removed_rep_cannot_immediately_re_run(client, rep_community, elect_rep, run_worker):
    rep_a, rep_b, members = _two_reps(client, rep_community, elect_rep, run_worker)
    removal_id = rep_a.post("/api/rep/removals",
                            json={"target_user_id": rep_b.user_id}).get_json()["removal"]["id"]
    for v in [m for m in members if m.user_id != rep_b.user_id][:3]:
        v.post(f"/api/rep/removals/{removal_id}/vote", json={"vote": "YES"})
    clock.advance(timedelta(hours=25))
    run_worker()
    removed = rep_b.relogin()
    assert removed.post("/api/rep/nominate",
                        json={"candidate_id": removed.user_id}).status_code == 409
    clock.advance(timedelta(days=8))
    removed.relogin()
    assert removed.post("/api/rep/nominate",
                        json={"candidate_id": removed.user_id}).status_code == 201


def test_duplicate_open_removal_is_rejected(client, rep_community, elect_rep, run_worker):
    rep_a, rep_b, _ = _two_reps(client, rep_community, elect_rep, run_worker)
    assert rep_a.post("/api/rep/removals",
                      json={"target_user_id": rep_b.user_id}).status_code == 201
    assert rep_a.post("/api/rep/removals",
                      json={"target_user_id": rep_b.user_id}).status_code == 409


def test_removal_closing_is_idempotent(client, rep_community, elect_rep, run_worker, app):
    rep_a, rep_b, members = _two_reps(client, rep_community, elect_rep, run_worker)
    removal_id = rep_a.post("/api/rep/removals",
                            json={"target_user_id": rep_b.user_id}).get_json()["removal"]["id"]
    for v in [m for m in members if m.user_id != rep_b.user_id][:3]:
        v.post(f"/api/rep/removals/{removal_id}/vote", json={"vote": "YES"})
    clock.advance(timedelta(hours=25))
    run_worker()
    with app.app_context():
        from academicai.db.connection import query_all
        first = len(query_all(
            "SELECT * FROM change_history WHERE entity_type = 'rep_removal' AND entity_id = ?",
            (removal_id,)))
    run_worker()
    run_worker()
    with app.app_context():
        from academicai.db.connection import query_all
        after = len(query_all(
            "SELECT * FROM change_history WHERE entity_type = 'rep_removal' AND entity_id = ?",
            (removal_id,)))
    assert after == first


def test_removal_is_community_specific(client, rep_community, elect_rep, run_worker):
    """A rep in one community has no standing in another (spec 12)."""
    rep_a, _members_a = rep_community(size=5)
    rep_b, _members_b = rep_community(size=5, department="Computer Science")
    rep_a.relogin()
    resp = rep_a.post("/api/rep/removals", json={"target_user_id": rep_b.user_id})
    assert resp.status_code == 400
