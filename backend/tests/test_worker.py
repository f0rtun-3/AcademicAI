"""Background worker behaviour (spec 21)."""
from datetime import timedelta

import pytest

from academicai import clock
from academicai.services import email_service

pytestmark = pytest.mark.worker


def test_run_once_executes_every_job(app):
    from academicai.worker.jobs import JOBS, run_once
    with app.app_context():
        results = run_once()
    assert set(results) == {name for name, _ in JOBS}
    assert not any(isinstance(v, dict) and "error" in v for v in results.values())


def test_a_failing_job_does_not_stop_the_others(app):
    """Separate transactions: one failure must not roll back other work (spec 21)."""
    from academicai.worker.jobs import run_once

    def boom():
        raise RuntimeError("job exploded")

    calls = []

    def fine():
        calls.append(1)
        return "ok"

    with app.app_context():
        results = run_once(jobs=(("boom", boom), ("fine", fine)))
    assert "error" in results["boom"]
    assert results["fine"] == "ok"
    assert calls == [1]


def test_worker_closes_expired_ballots_only(client, community, elect_rep, run_worker, app):
    members = community(client, size=4)
    nomination_id = elect_rep(client, members)
    results = run_worker()
    assert results["close_expired_nominations"] == []       # not yet expired

    clock.advance(timedelta(hours=25))
    results = run_worker()
    assert len(results["close_expired_nominations"]) == 1
    assert results["close_expired_nominations"][0][1]["status"] == "PASSED"


def test_repeated_worker_runs_are_idempotent_end_to_end(
        client, academic_community, run_worker, app):
    setup = academic_community(seed_events=False)
    setup.rep.post("/api/events", json={
        "title": "COS202 Quiz", "event_type": "QUIZ",
        "course_id": setup.courses["COS202"], "event_date": "2026-09-25"})
    clock.freeze(clock.parse_iso("2026-09-24T08:30:00+00:00"))
    run_worker()
    baseline = len(email_service.sent_messages())
    for _ in range(3):
        run_worker()
    assert len(email_service.sent_messages()) == baseline


def test_worker_promotes_a_candidate_exactly_once_under_repeat_runs(
        client, community, elect_rep, run_worker, app):
    members = community(client, size=4)
    elect_rep(client, members)
    clock.advance(timedelta(hours=25))
    for _ in range(4):
        run_worker()
    with app.app_context():
        from academicai.db.connection import query_one
        row = query_one(
            """SELECT COUNT(*) AS n FROM community_members
               WHERE community_id = ? AND role = 'VERIFIED_REP' AND status = 'ACTIVE'""",
            (members[0].community_id,))
        assert row["n"] == 1


def test_ballot_closing_is_safe_when_run_concurrently(client, community, elect_rep, app):
    """Two workers resolving the same ballot must produce one outcome (spec 21)."""
    from academicai.db.connection import transaction
    from academicai.services import rep_service

    members = community(client, size=4)
    nomination_id = elect_rep(client, members)
    clock.advance(timedelta(hours=25))

    with app.app_context():
        with transaction() as conn:
            first = rep_service.close_ballot(nomination_id, conn=conn)
        with transaction() as conn:
            second = rep_service.close_ballot(nomination_id, conn=conn)
    assert first["status"] == "PASSED"
    assert second is None          # the second caller finds nothing to do


def test_expired_removal_ballots_are_closed_by_the_worker(
        client, rep_community, elect_rep, run_worker):
    rep_a, members = rep_community(size=6)
    elect_rep(client, members, candidate=members[1])
    clock.advance(timedelta(hours=25))
    run_worker()
    for m in members:
        m.relogin()
    rep_b = members[1]

    removal_id = rep_a.post("/api/rep/removals",
                            json={"target_user_id": rep_b.user_id}).get_json()["removal"]["id"]
    for voter in [m for m in members if m.user_id != rep_b.user_id][:3]:
        voter.post(f"/api/rep/removals/{removal_id}/vote", json={"vote": "YES"})

    clock.advance(timedelta(hours=25))
    results = run_worker()
    assert len(results["close_expired_removals"]) == 1
    assert results["close_expired_removals"][0][1]["status"] == "PASSED"


def test_the_worker_has_no_identity_evidence_job(app):
    """The purge job existed only to clean up ID-card uploads.

    With student ID-card verification out of MVP scope there is no evidence to
    purge, so the job is gone rather than left running as a no-op - and the
    remaining jobs must still all be registered.
    """
    from academicai.worker.jobs import JOBS, run_once

    names = [name for name, _fn in JOBS]
    assert "purge_identity_evidence" not in names
    assert names == ["close_expired_nominations", "close_expired_removals",
                     "process_event_reminders", "process_personal_reminders",
                     "dispatch_notifications"]
    with app.app_context():
        assert set(run_once()) == set(names)

