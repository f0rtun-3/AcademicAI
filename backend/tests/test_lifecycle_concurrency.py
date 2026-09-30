"""Lifecycle concurrency matrix: real threads against a real SQLite file.

Every race below was executed, not reasoned about. The harness asserts each
setup step, because a race whose fixture quietly failed proves nothing - an
earlier version of this file "passed" only because expired sessions made every
vote a silent 401.
"""
from datetime import timedelta

from academicai import clock
from tests.concurrency_harness import (advance_and_relogin, cleanup, db, elect_rep,
                                       make_file_app, make_member, race, relogin,
                                       relogin_all, run_worker)


def _seed(tmp_path, name, size):
    app, path = make_file_app(tmp_path, name)
    members = [make_member(app) for _ in range(size)]
    elect_rep(app, members[0], members[1:4], run_worker)
    # elect_rep advances the clock past the 24h session TTL, so every member
    # needs a fresh session before the test does anything else.
    relogin_all(app, members)
    return app, path, members


def test_race_election_overflow(tmp_path):
    """Four passing ballots close concurrently with only 2 rep slots left."""
    app, path, m = _seed(tmp_path, "elect", 12)
    try:
        rep = m[0]
        ids = []
        for cand in m[4:8]:
            r = rep["client"].post("/api/rep/nominate", headers=rep["headers"],
                                   json={"candidate_id": cand["id"]})
            assert r.status_code == 201, r.get_json()
            ids.append(r.get_json()["nomination"]["id"])
        for nid in ids:
            for voter in m[8:12]:
                v = voter["client"].post(f"/api/rep/candidates/{nid}/vote",
                                         headers=voter["headers"], json={"vote": "YES"})
                assert v.status_code == 201, f"vote: {v.get_json()}"
        advance_and_relogin(app, m, timedelta(hours=25))

        race(lambda: run_worker(app), threads_per_fn=4)

        conn = db(app)
        reps = conn.execute(
            "SELECT COUNT(*) AS n FROM community_members WHERE role='VERIFIED_REP'"
        ).fetchone()["n"]
        passed = conn.execute(
            "SELECT COUNT(*) AS n FROM rep_nominations WHERE status='PASSED'").fetchone()["n"]
        promos = conn.execute(
            """SELECT COUNT(*) AS n FROM change_history
               WHERE change_type='NOMINATION_PASSED'""").fetchone()["n"]
        notifs = conn.execute(
            """SELECT dedupe_key, COUNT(*) AS n FROM notifications
               WHERE dedupe_key LIKE 'nomination:%' GROUP BY dedupe_key
               HAVING COUNT(*) > 1""").fetchall()
        conn.close()
        print(f"\n[1] election x4 close  reps={reps} passed_ballots={passed} "
              f"promo_audit={promos} dup_notifs={len(notifs)}")
        assert reps <= 3, f"maximum rep cap breached: {reps}"
        assert promos == passed, "a promotion was recorded more than once"
        assert not notifs, "duplicate ballot notifications"
    finally:
        cleanup(path)


def test_race_removal_vs_publish(tmp_path):
    """Removal ballot closes while the same rep creates and updates events."""
    app, path, m = _seed(tmp_path, "removal", 8)
    try:
        target, second = m[0], m[1]
        elect_rep(app, second, m[2:5], run_worker)
        relogin_all(app, m)
        ev = target["client"].post("/api/events", headers=target["headers"],
                                   json={"title": "Pre", "event_type": "QUIZ",
                                         "event_date": "2026-10-20"})
        assert ev.status_code == 201, ev.get_json()
        event = ev.get_json()["event"]

        rid = second["client"].post("/api/rep/removals", headers=second["headers"],
                                    json={"target_user_id": target["id"]})
        assert rid.status_code == 201, rid.get_json()
        removal_id = rid.get_json()["removal"]["id"]
        for voter in m[2:5]:
            relogin(app, voter)
            v = voter["client"].post(f"/api/rep/removals/{removal_id}/vote",
                                     headers=voter["headers"], json={"vote": "YES"})
            assert v.status_code == 201, f"removal vote: {v.get_json()}"
        advance_and_relogin(app, m, timedelta(hours=25))

        out = race(
            lambda: run_worker(app),
            lambda: target["client"].post("/api/events", headers=target["headers"],
                                          json={"title": "Raced create",
                                                "event_type": "QUIZ"}).status_code,
            lambda: target["client"].put(f"/api/events/{event['id']}",
                                         headers=target["headers"],
                                         json={"venue": "Raced venue",
                                               "expected_version": event["version"]}
                                         ).status_code,
        )
        conn = db(app)
        role = conn.execute(
            "SELECT role FROM community_members WHERE user_id=?", (target["id"],)
        ).fetchone()["role"]
        created = conn.execute(
            "SELECT COUNT(*) AS n FROM academic_events WHERE title='Raced create'"
        ).fetchone()["n"]
        venue = conn.execute("SELECT venue FROM academic_events WHERE id=?",
                             (event["id"],)).fetchone()["venue"]
        conn.close()
        print(f"[2] removal vs publish  results={out[1:]} final_role={role} "
              f"created={created} venue={venue}")
        assert role == "STUDENT", "removal did not revoke authority"
        # A write that committed before the removal was authorised at the time;
        # what must never happen is a write landing after authority is gone.
        assert out[2] in (403, 401, 409, 200), out[2]
        if out[2] == 200:
            assert venue == "Raced venue"
        else:
            assert venue is None, "an unauthorised update landed"
    finally:
        cleanup(path)


def test_race_transfers(tmp_path):
    """Concurrent transfers to different and identical destinations."""
    app, path, m = _seed(tmp_path, "transfer", 6)
    try:
        mover = m[4]
        base = {"university": "Babcock University",
                "department": "Software Engineering", "academic_session": "2026/2027"}
        out = race(
            lambda: mover["client"].post("/api/community/transfer",
                                         headers=mover["headers"],
                                         json={**base, "level": "300"}).status_code,
            lambda: mover["client"].post("/api/community/transfer",
                                         headers=mover["headers"],
                                         json={**base, "level": "400"}).status_code,
            lambda: mover["client"].post("/api/community/transfer",
                                         headers=mover["headers"],
                                         json={**base, "level": "300"}).status_code,
        )
        conn = db(app)
        rows = conn.execute(
            "SELECT community_id, status FROM community_members WHERE user_id=?",
            (mover["id"],)).fetchall()
        conn.close()
        active = [r for r in rows if r["status"] == "ACTIVE"]
        print(f"[3] transfer B vs C vs B  results={sorted(out, key=str)} "
              f"ACTIVE={len(active)} rows={[(r['community_id'], r['status']) for r in rows]}")
        assert len(active) == 1, f"single-active-membership violated: {len(active)}"
    finally:
        cleanup(path)


def test_race_course_removal(tmp_path):
    """Course removal racing event creation and enrolment on that course."""
    app, path, m = _seed(tmp_path, "course", 6)
    try:
        rep, student = m[0], m[4]
        course = rep["client"].post("/api/community/courses", headers=rep["headers"],
                                    json={"code": "COS950"}).get_json()["course"]
        out = race(
            lambda: rep["client"].delete(f"/api/community/courses/{course['id']}",
                                         headers=rep["headers"]).status_code,
            lambda: rep["client"].post("/api/events", headers=rep["headers"],
                                       json={"title": "Raced course event",
                                             "event_type": "ASSIGNMENT",
                                             "course_id": course["id"],
                                             "event_date": "2026-10-20"}).status_code,
            lambda: student["client"].post(
                f"/api/community/courses/{course['id']}/enroll",
                headers=student["headers"]).status_code,
        )
        conn = db(app)
        status = conn.execute("SELECT status FROM courses WHERE id=?",
                              (course["id"],)).fetchone()["status"]
        ev = conn.execute(
            "SELECT COUNT(*) AS n FROM academic_events WHERE title='Raced course event'"
        ).fetchone()["n"]
        enr = conn.execute(
            "SELECT status FROM course_enrollments WHERE course_id=?",
            (course["id"],)).fetchall()
        conn.close()
        print(f"[4] course removal race  results={out} course={status} "
              f"events={ev} enrollments={[e['status'] for e in enr]}")

        # THE REMOVAL IS NOT GUARANTEED TO WIN, and must not be asserted to.
        # Removal is refused while a SCHEDULED event references the course, so
        # whether the DELETE commits or answers 409 depends on which thread
        # reaches its transaction first. An earlier version of this test
        # asserted status == "REMOVED" and so failed intermittently on the
        # outcome where the policy worked correctly. What must hold is the
        # INVARIANT, in both outcomes.
        assert status in ("REMOVED", "ACTIVE"), status
        assert 409 in out or status == "REMOVED", out

        # Whatever the order, no enrolment survives as ACTIVE on a removed
        # course - neither dropped late nor created after the removal.
        if status == "REMOVED":
            assert all(e["status"] == "DROPPED" for e in enr), [e["status"] for e in enr]
            # And nothing that would have blocked the removal slipped in after it.
            conn = db(app)
            blocking = conn.execute(
                """SELECT COUNT(*) AS n FROM academic_events
                   WHERE course_id = ? AND status = 'SCHEDULED'""",
                (course["id"],)).fetchone()["n"]
            live_entries = conn.execute(
                """SELECT COUNT(*) AS n FROM timetable_entries
                   WHERE course_id = ? AND status = 'ACTIVE'""",
                (course["id"],)).fetchone()["n"]
            conn.close()
            assert blocking == 0, f"scheduled event survives on a removed course: {blocking}"
            assert live_entries == 0, live_entries
        else:
            # The removal was refused. It must have been refused for the stated
            # reason - a blocking record actually exists - and not left the
            # course half-removed.
            assert ev == 1, ev
            assert 409 in out, out
    finally:
        cleanup(path)


def test_race_cancel_vs_reminder(tmp_path):
    """Event cancellation racing the reminder worker."""
    app, path, m = _seed(tmp_path, "cancel", 6)
    try:
        rep = m[0]
        ev = rep["client"].post("/api/events", headers=rep["headers"],
                                json={"title": "Cancel race", "event_type": "ASSIGNMENT",
                                      "event_date": "2026-09-20"}).get_json()["event"]
        clock.freeze(clock.parse_iso("2026-09-19T08:00:00+00:00"))
        relogin_all(app, m)          # the freeze moved past the session TTL
        out = race(
            lambda: rep["client"].post(f"/api/events/{ev['id']}/cancel",
                                       headers=rep["headers"],
                                       json={"expected_version": ev["version"]}).status_code,
            lambda: run_worker(app),
        )
        conn = db(app)
        status = conn.execute("SELECT status FROM academic_events WHERE id=?",
                              (ev["id"],)).fetchone()["status"]
        rem = conn.execute("SELECT status FROM event_reminders WHERE event_id=?",
                           (ev["id"],)).fetchall()
        notif = conn.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE subject LIKE 'Reminder:%'"
        ).fetchone()["n"]
        conn.close()
        print(f"[5] cancel vs reminder  cancel={out[0]} event={status} "
              f"reminders={[r['status'] for r in rem]} reminder_notifs={notif}")
        assert out[0] == 200, f"cancel failed, race is inconclusive: {out[0]}"
        assert status == "CANCELLED"
    finally:
        cleanup(path)


def test_race_archive_vs_everything(tmp_path):
    """Archival racing publish, election close and notification dispatch."""
    app, path, m = _seed(tmp_path, "archive", 10)
    try:
        rep = m[0]
        cand = m[5]
        nid = rep["client"].post("/api/rep/nominate", headers=rep["headers"],
                                 json={"candidate_id": cand["id"]}).get_json()["nomination"]["id"]
        for voter in m[6:9]:
            v = voter["client"].post(f"/api/rep/candidates/{nid}/vote",
                                     headers=voter["headers"], json={"vote": "YES"})
            assert v.status_code == 201, f"vote: {v.get_json()}"
        advance_and_relogin(app, m, timedelta(hours=25))

        def archive():
            with app.app_context():
                from academicai.services import calendar_service
                try:
                    calendar_service.archive_session(rep["id"], rep["community_id"])
                    return "archived"
                except Exception as exc:
                    return f"EXC {type(exc).__name__}"

        out = race(
            archive,
            lambda: run_worker(app),
            lambda: rep["client"].post("/api/events", headers=rep["headers"],
                                       json={"title": "Raced archive publish",
                                             "event_type": "QUIZ"}).status_code,
        )
        conn = db(app)
        cstatus = conn.execute("SELECT status FROM academic_communities WHERE id=?",
                               (rep["community_id"],)).fetchone()["status"]
        reps = conn.execute(
            "SELECT COUNT(*) AS n FROM community_members WHERE role='VERIFIED_REP'"
        ).fetchone()["n"]
        published = conn.execute(
            "SELECT COUNT(*) AS n FROM academic_events WHERE title='Raced archive publish'"
        ).fetchone()["n"]
        conn.close()
        print(f"[6] archive vs all  results={out} community={cstatus} "
              f"reps_after={reps} published={published}")
        assert cstatus == "ARCHIVED"
        assert reps == 0, "rep authority survived archival"
    finally:
        cleanup(path)
