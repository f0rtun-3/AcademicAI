"""Academic calendar and session lifecycle (spec 23)."""
CALENDAR_TEXT = """
2026/2027 ACADEMIC SESSION CALENDAR

Session begins: 2026-09-07
Registration closes: 2026-09-21
First semester examinations: 2026-12-07
Semester ends: 2026-12-18
Second semester resumption: 2027-01-11
Session ends: 2027-07-16
Notes - nothing parseable here
"""


def test_rep_uploads_calendar_and_dates_are_extracted(client, academic_community):
    setup = academic_community(seed_events=False)
    resp = setup.rep.post("/api/community/calendar", json={"raw_text": CALENDAR_TEXT})
    assert resp.status_code == 201, resp.get_json()
    calendar = resp.get_json()["calendar"]
    assert calendar["session_start"] == "2026-09-07"
    assert calendar["session_end"] == "2027-07-16"
    labels = {p["label"] for p in calendar["periods"]}
    assert "Registration closes" in labels
    assert "First semester examinations" in labels


def test_unparseable_lines_are_skipped_not_guessed(client, academic_community):
    setup = academic_community(seed_events=False)
    calendar = setup.rep.post("/api/community/calendar",
                              json={"raw_text": CALENDAR_TEXT}).get_json()["calendar"]
    assert all(p["date"] for p in calendar["periods"])
    assert "Notes" not in {p["label"] for p in calendar["periods"]}


def test_student_cannot_upload_calendar(client, academic_community):
    setup = academic_community(seed_events=False)
    resp = setup.members[1].post("/api/community/calendar", json={"raw_text": CALENDAR_TEXT})
    assert resp.status_code == 403


def test_students_can_read_the_calendar(client, academic_community):
    setup = academic_community(seed_events=False)
    setup.rep.post("/api/community/calendar", json={"raw_text": CALENDAR_TEXT})
    calendar = setup.members[1].get("/api/community/calendar").get_json()["calendar"]
    assert calendar["session_start"] == "2026-09-07"


def test_empty_calendar_is_rejected(client, academic_community):
    setup = academic_community(seed_events=False)
    assert setup.rep.post("/api/community/calendar", json={"raw_text": "  "}).status_code == 400


def test_archiving_a_session_revokes_rep_authority(client, academic_community):
    """Rep authority does not carry into a new session (spec 23)."""
    setup = academic_community(seed_events=False)
    assert setup.rep.post("/api/community/archive").status_code == 200
    setup.rep.relogin()
    membership = setup.rep.get("/api/community").get_json()["membership"]
    assert membership["role"] == "STUDENT"
    assert setup.rep.post("/api/events",
                          json={"title": "x", "event_type": "QUIZ"}).status_code == 403


def test_archiving_cancels_outstanding_reminders(client, academic_community, app):
    setup = academic_community(seed_events=False)
    setup.rep.post("/api/events", json={
        "title": "COS202 Quiz", "event_type": "QUIZ",
        "course_id": setup.courses["COS202"], "event_date": "2026-10-20"})
    setup.rep.post("/api/community/archive")
    with app.app_context():
        from academicai.db.connection import query_all
        rows = query_all("SELECT * FROM event_reminders")
        assert all(r["status"] == "CANCELLED" for r in rows)


def test_archived_session_stops_generating_notifications(
        client, academic_community, run_worker, app):
    from academicai.services import email_service
    setup = academic_community(seed_events=False)
    setup.rep.post("/api/events", json={
        "title": "COS202 Quiz", "event_type": "QUIZ",
        "course_id": setup.courses["COS202"], "event_date": "2026-10-20"})
    setup.rep.post("/api/community/archive")
    email_service.clear()
    run_worker()
    assert email_service.sent_messages() == []


def test_students_keep_their_history_after_archiving(client, academic_community):
    setup = academic_community()
    setup.rep.post("/api/community/archive")
    student = setup.members[1].relogin()
    events = student.get("/api/events").get_json()["events"]
    assert any(e["title"] == "COS202 Assignment" for e in events)


def test_new_session_requires_a_fresh_community_and_new_reps(client, academic_community):
    """Nothing is carried over: new session, new community, new election (spec 23)."""
    setup = academic_community(seed_events=False)
    setup.rep.post("/api/community/archive")
    student = setup.members[1].relogin()

    resp = student.post("/api/community/transfer", json={
        "university": "Babcock University", "department": "Software Engineering",
        "level": "200", "academic_session": "2027/2028"})
    assert resp.status_code == 201
    destination = resp.get_json()["destination"]
    assert destination["status"] == "PENDING"     # starts fresh, no reps
    assert destination["reps"] == []
    assert destination["member_count"] == 1

    # Courses are not copied into the new session.
    assert student.get("/api/community/courses").get_json()["courses"] == []


def test_level_is_never_incremented_automatically(client, academic_community):
    setup = academic_community(seed_events=False)
    setup.rep.post("/api/community/archive")
    student = setup.members[1].relogin()
    profile = student.get("/api/auth/me").get_json()["user"]
    assert profile["level"] == "200"


def test_double_archive_is_rejected(client, academic_community):
    setup = academic_community(seed_events=False)
    setup.rep.post("/api/community/archive")
    setup.rep.relogin()
    assert setup.rep.post("/api/community/archive").status_code == 403
