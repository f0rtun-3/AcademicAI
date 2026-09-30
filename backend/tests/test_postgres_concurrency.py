"""The read-then-write guarantees, re-proved on PostgreSQL.

On SQLite they rest on BEGIN IMMEDIATE's single write lock. On PostgreSQL
they rest on the app-wide advisory lock that stands in for it (db/postgres.py).
The races below are the existing concurrency suite's own scenarios - real
threads, real requests, the same assertions - run unchanged against a
PostgreSQL app, plus the two that talked to SQLite directly, rewritten for
PostgreSQL.

Needs ACADEMICAI_TEST_POSTGRES_URL; skipped (and reported skipped) without it.
"""
import threading

import pytest

pytest.importorskip("psycopg")

from academicai.db import postgres  # noqa: E402
from tests import pg_support  # noqa: E402
from tests import test_concurrency as basic  # noqa: E402
from tests import test_lifecycle_concurrency as lifecycle  # noqa: E402
from tests.conftest import seed_rep_community_over_http  # noqa: E402

pytestmark = [pytest.mark.postgres, pytest.mark.concurrency]


@pytest.fixture
def pg_app(pg_schema):
    return pg_support.make_pg_app(pg_schema)


@pytest.fixture
def lifecycle_on_postgres(pg_schema, monkeypatch):
    """The lifecycle matrix builds its app through make_file_app; give it a
    PostgreSQL one. Its final-state reads (concurrency_harness.db) follow the
    app's backend."""
    monkeypatch.setattr(lifecycle, "make_file_app",
                        lambda tmp_path, name="conc": (pg_support.make_pg_app(pg_schema), None))
    monkeypatch.setattr(lifecycle, "cleanup", lambda path: None)


@pytest.mark.parametrize("scenario", [
    basic.test_concurrent_updates_to_one_event_yield_one_winner,
    basic.test_concurrent_ballot_closing_promotes_once,
    basic.test_concurrent_votes_are_all_recorded_exactly_once,
    basic.test_double_vote_is_rejected_under_concurrency,
    basic.test_transaction_rolls_back_on_failure,
], ids=lambda f: f.__name__)
def test_concurrency_suite_on_postgresql(scenario, pg_app):
    scenario(pg_app)


@pytest.mark.parametrize("scenario", [
    lifecycle.test_race_election_overflow,
    lifecycle.test_race_removal_vs_publish,
    lifecycle.test_race_transfers,
    lifecycle.test_race_course_removal,
    lifecycle.test_race_cancel_vs_reminder,
    lifecycle.test_race_archive_vs_everything,
], ids=lambda f: f.__name__)
def test_lifecycle_races_on_postgresql(scenario, lifecycle_on_postgres, tmp_path):
    scenario(tmp_path)


def test_lock_contention_is_503_not_a_stale_proposal(pg_schema):
    """test_concurrency's version holds a SQLite lock; this holds PostgreSQL's."""
    app = pg_support.make_pg_app(pg_schema)
    actors, event, _ = basic._seed(app)
    blocked = pg_support.make_pg_app(pg_schema, SQLITE_BUSY_TIMEOUT_MS=50)

    holder = postgres.connect(pg_schema)
    try:
        with holder.transaction(immediate=True):
            holder.execute("UPDATE academic_events SET title = 'locked' WHERE id = ?",
                           (event["id"],))
            resp = blocked.test_client().put(
                f"/api/events/{event['id']}",
                json={"event_date": "2026-11-01", "expected_version": event["version"]},
                headers=actors[0]["headers"])
    finally:
        holder.close()

    assert resp.status_code == 503
    assert resp.get_json()["error"] == "database_busy"


def test_concurrent_removal_and_publish_leaves_consistent_state(pg_schema):
    """test_authority_revocation_races' version revokes through SQLite; this
    revokes through PostgreSQL, taking the same write lock the app takes."""
    app = pg_support.make_pg_app(pg_schema)
    rep_headers, rep_id, community_id = seed_rep_community_over_http(app)
    client = app.test_client()
    results = {}

    def publish():
        results["publish"] = client.post(
            "/api/events", json={"title": "Concurrent", "event_type": "QUIZ"},
            headers=rep_headers).status_code

    def revoke():
        conn = postgres.connect(pg_schema)
        try:
            with conn.transaction(immediate=True):
                conn.execute("""UPDATE community_members SET role = 'STUDENT'
                                WHERE user_id = ? AND community_id = ?""",
                             (rep_id, community_id))
        finally:
            conn.close()

    threads = [threading.Thread(target=publish), threading.Thread(target=revoke)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    verify = postgres.connect(pg_schema)
    try:
        published = verify.execute(
            "SELECT COUNT(*) AS n FROM academic_events WHERE title = 'Concurrent'"
        ).fetchone()["n"]
        still_rep = verify.execute(
            """SELECT COUNT(*) AS n FROM community_members
               WHERE user_id = ? AND community_id = ? AND role = 'VERIFIED_REP'""",
            (rep_id, community_id)).fetchone()["n"]
    finally:
        verify.close()
    assert results["publish"] in (201, 403)
    assert (results["publish"] == 201) == (published == 1)
    assert still_rep == 0
