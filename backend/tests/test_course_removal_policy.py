"""Course removal is refused while official records still depend on it.

Product decision (recorded 2026-09-15): block removal rather than auto-cancel
or silently detach.

Why: course-scoped notifications are targeted through ACTIVE enrolments, and
removing a course drops them all. Anything still attached would keep existing
while reaching nobody - a rep would get HTTP 200 on a deadline change that no
student ever received. Blocking makes the rep's intent explicit and destroys
nothing.
"""
import pytest

pytestmark = pytest.mark.security


def _course_with_event(setup, code="COS500", **event):
    course = setup.rep.post("/api/community/courses",
                            json={"code": code}).get_json()["course"]
    payload = {"title": "Attached work", "event_type": "ASSIGNMENT",
               "course_id": course["id"], "event_date": "2026-10-20"}
    payload.update(event)
    created = setup.rep.post("/api/events", json=payload)
    assert created.status_code == 201, created.get_json()
    return course, created.get_json()["event"]


def test_removal_is_refused_while_a_scheduled_event_references_the_course(
        client, academic_community, app):
    setup = academic_community(size=5, seed_events=False)
    course, event = _course_with_event(setup)

    resp = setup.rep.delete(f"/api/community/courses/{course['id']}")
    assert resp.status_code == 409
    body = resp.get_json()
    assert "Cancel or reschedule them" in body["message"]
    assert [e["id"] for e in body["details"]["blocking_events"]] == [event["id"]]
    assert body["details"]["blocking_events"][0]["title"] == "Attached work"

    # Nothing changed: the course is still usable and enrolments intact.
    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT status FROM courses WHERE id = ?",
                         (course["id"],))["status"] == "ACTIVE"
    listed = [c["code"] for c in
              setup.rep.get("/api/community/courses").get_json()["courses"]]
    assert "COS500" in listed


def test_removal_succeeds_once_the_event_is_cancelled(client, academic_community, app):
    """The documented way out: deal with the events, then remove the course."""
    setup = academic_community(size=5, seed_events=False)
    course, event = _course_with_event(setup)

    current = setup.rep.get(f"/api/events/{event['id']}").get_json()["event"]
    assert setup.rep.post(f"/api/events/{event['id']}/cancel",
                          json={"expected_version": current["version"]}).status_code == 200

    assert setup.rep.delete(f"/api/community/courses/{course['id']}").status_code == 200
    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT status FROM courses WHERE id = ?",
                         (course["id"],))["status"] == "REMOVED"


def test_a_cancelled_event_does_not_block_removal(client, academic_community):
    setup = academic_community(size=5, seed_events=False)
    course, event = _course_with_event(setup)
    current = setup.rep.get(f"/api/events/{event['id']}").get_json()["event"]
    setup.rep.post(f"/api/events/{event['id']}/cancel",
                   json={"expected_version": current["version"]})
    assert setup.rep.delete(f"/api/community/courses/{course['id']}").status_code == 200


def test_an_active_timetable_entry_also_blocks_removal(client, academic_community):
    """Timetable entries are course-scoped in the same way."""
    setup = academic_community(size=5, seed_events=False)
    course = setup.rep.post("/api/community/courses",
                            json={"code": "COS501"}).get_json()["course"]
    entry = setup.rep.post("/api/community/timetable", json={
        "course_id": course["id"], "day_of_week": "MONDAY",
        "start_time": "09:00", "venue": "B007"})
    assert entry.status_code == 201, entry.get_json()

    resp = setup.rep.delete(f"/api/community/courses/{course['id']}")
    assert resp.status_code == 409
    assert resp.get_json()["details"]["blocking_timetable_entries"]
    assert resp.get_json()["details"]["blocking_events"] == []


def test_removal_succeeds_once_the_timetable_entry_is_cancelled(client, academic_community):
    setup = academic_community(size=5, seed_events=False)
    course = setup.rep.post("/api/community/courses",
                            json={"code": "COS502"}).get_json()["course"]
    entry = setup.rep.post("/api/community/timetable", json={
        "course_id": course["id"], "day_of_week": "MONDAY",
        "start_time": "09:00"}).get_json()["timetable_entry"]
    setup.rep.delete(f"/api/community/timetable/{entry['id']}")
    assert setup.rep.delete(f"/api/community/courses/{course['id']}").status_code == 200


def test_a_course_with_no_dependants_removes_cleanly(client, academic_community, app):
    setup = academic_community(size=5, seed_events=False)
    course = setup.rep.post("/api/community/courses",
                            json={"code": "COS503"}).get_json()["course"]
    student = setup.members[1]
    student.post(f"/api/community/courses/{course['id']}/enroll")

    assert setup.rep.delete(f"/api/community/courses/{course['id']}").status_code == 200
    with app.app_context():
        from academicai.db.connection import query_all
        statuses = [r["status"] for r in query_all(
            "SELECT status FROM course_enrollments WHERE course_id = ?", (course["id"],))]
        assert statuses == ["DROPPED"]


def test_the_block_reports_every_blocking_record(client, academic_community):
    setup = academic_community(size=5, seed_events=False)
    course = setup.rep.post("/api/community/courses",
                            json={"code": "COS504"}).get_json()["course"]
    for i in range(3):
        setup.rep.post("/api/events", json={
            "title": f"Work {i}", "event_type": "ASSIGNMENT",
            "course_id": course["id"], "event_date": f"2026-10-2{i}"})

    resp = setup.rep.delete(f"/api/community/courses/{course['id']}")
    assert resp.status_code == 409
    assert len(resp.get_json()["details"]["blocking_events"]) == 3
    assert "3 scheduled events" in resp.get_json()["message"]


def test_no_notification_or_history_is_written_by_a_refused_removal(
        client, academic_community, app):
    setup = academic_community(size=5, seed_events=False)
    course, _event = _course_with_event(setup)
    with app.app_context():
        from academicai.db.connection import query_one
        before_n = query_one("SELECT COUNT(*) AS n FROM notifications")["n"]
        before_h = query_one("SELECT COUNT(*) AS n FROM change_history")["n"]

    assert setup.rep.delete(f"/api/community/courses/{course['id']}").status_code == 409

    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT COUNT(*) AS n FROM notifications")["n"] == before_n
        assert query_one("SELECT COUNT(*) AS n FROM change_history")["n"] == before_h


def test_a_deadline_change_still_reaches_enrolled_students(client, academic_community, app):
    """The condition the policy protects: the course cannot vanish underneath
    an event, so course-scoped targeting keeps working."""
    setup = academic_community(size=5, seed_events=False)
    course, event = _course_with_event(setup, title="Reaches students")
    student = setup.members[1]
    assert student.post(f"/api/community/courses/{course['id']}/enroll").status_code == 201

    # Removal is blocked, so the enrolment survives...
    assert setup.rep.delete(f"/api/community/courses/{course['id']}").status_code == 409
    current = setup.rep.get(f"/api/events/{event['id']}").get_json()["event"]
    assert setup.rep.put(f"/api/events/{event['id']}",
                         json={"event_date": "2026-11-01",
                               "expected_version": current["version"]}).status_code == 200

    with app.app_context():
        from academicai.db.connection import query_all
        recipients = {r["user_id"] for r in query_all(
            "SELECT user_id FROM notifications WHERE subject LIKE ?",
            ("%Reaches students%",))}
    assert student.user_id in recipients
