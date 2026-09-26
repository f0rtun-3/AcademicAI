"""Publishing, authorization and optimistic concurrency (spec 2, 17)."""
from tests.conftest import analyze


def _publish(actor, proposal, **overrides):
    payload = {
        "action": proposal["action"],
        "scope": proposal["scope"],
        "target_id": proposal.get("possible_match_id"),
        "expected_version": proposal.get("expected_version"),
        "title": proposal.get("title"),
        "event_type": proposal.get("event_type"),
        "event_date": proposal.get("event_date"),
        "event_time": proposal.get("event_time"),
        "venue": proposal.get("venue"),
        "day_of_week": proposal.get("day_of_week"),
        "course_code": proposal.get("course_code"),
        "original_message": proposal.get("original_message"),
    }
    payload.update(overrides)
    return actor.post("/api/ai/publish", json=payload)


def test_rep_can_publish_a_create_proposal(client, academic_community):
    setup = academic_community(seed_events=False)
    proposal = analyze(setup.rep, "WE have cos 202 assignmentto be submittted on friday")
    resp = _publish(setup.rep, proposal)
    assert resp.status_code == 201, resp.get_json()
    event = resp.get_json()["published"]["event"]
    assert event["event_date"] == "2026-09-18"
    assert event["event_type"] == "ASSIGNMENT"


def test_published_event_is_visible_to_students(client, academic_community):
    setup = academic_community(seed_events=False)
    proposal = analyze(setup.rep, "WE have cos 202 assignmentto be submittted on friday")
    _publish(setup.rep, proposal)
    events = setup.members[1].get("/api/events").get_json()["events"]
    assert any(e["event_type"] == "ASSIGNMENT" for e in events)


def test_student_cannot_publish(client, academic_community):
    """Only verified reps publish official information (spec 13)."""
    setup = academic_community(seed_events=False)
    student = setup.members[1]
    proposal = analyze(student, "WE have cos 202 assignmentto be submittted on friday")
    assert proposal["personal_only"] is True
    assert proposal["publishable"] is False
    assert _publish(student, proposal).status_code == 403


def test_publishing_a_clarification_is_refused(client, academic_community):
    setup = academic_community()
    proposal = analyze(setup.rep, "We have 212 presentation, to beb presented next two weeks")
    assert proposal["action"] == "CLARIFICATION"
    resp = _publish(setup.rep, proposal)
    assert resp.status_code == 400


def test_publishing_a_duplicate_is_refused(client, academic_community):
    setup = academic_community()
    proposal = analyze(setup.rep, "WE have cos 202 assignment to be submittted on friday")
    assert proposal["action"] == "DUPLICATE"
    assert _publish(setup.rep, proposal).status_code == 400


def test_update_applies_the_change_and_records_history(client, academic_community):
    setup = academic_community()
    proposal = analyze(
        setup.rep,
        "The deadline for the cos202 assignment has been extended to next week monday.")
    resp = _publish(setup.rep, proposal)
    assert resp.status_code == 201, resp.get_json()

    detail = setup.rep.get(f"/api/events/{setup.cos202_assignment['id']}").get_json()
    assert detail["event"]["event_date"] == "2026-09-21"
    changes = [h for h in detail["history"] if h["change_type"] == "DEADLINE_CHANGED"]
    assert len(changes) == 1
    assert changes[0]["old_value"]["event_date"] == "2026-09-18"
    assert changes[0]["new_value"]["event_date"] == "2026-09-21"


def test_stale_proposal_is_rejected_with_409(client, academic_community):
    """Proposal built against version N, database now at N+1 -> 409 (spec 17)."""
    setup = academic_community()
    proposal = analyze(
        setup.rep,
        "The deadline for the cos202 assignment has been extended to next week monday.")
    assert proposal["expected_version"] == 1

    # Someone else changes the same event first.
    other = setup.rep.put(f"/api/events/{setup.cos202_assignment['id']}",
                          json={"venue": "LT2"})
    assert other.status_code == 200

    resp = _publish(setup.rep, proposal)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "stale_proposal"
    assert resp.get_json()["details"]["current_version"] == 2


def test_reanalysis_after_a_conflict_succeeds(client, academic_community):
    setup = academic_community()
    setup.rep.put(f"/api/events/{setup.cos202_assignment['id']}", json={"venue": "LT2"})
    proposal = analyze(
        setup.rep,
        "The deadline for the cos202 assignment has been extended to next week monday.")
    assert proposal["expected_version"] == 2
    assert _publish(setup.rep, proposal).status_code == 201


def test_venue_change_publishes_as_update_not_a_new_record(client, academic_community, app):
    setup = academic_community()
    proposal = analyze(
        setup.rep,
        "Guys the venue fo adventist heritage has ben changed from b007 to b107")
    assert _publish(setup.rep, proposal).status_code == 201
    with app.app_context():
        from academicai.db.connection import query_all
        rows = query_all("SELECT * FROM academic_events WHERE title LIKE 'Adventist%'")
        assert len(rows) == 1              # updated, not duplicated
        assert rows[0]["venue"] == "B107"


def test_timetable_day_change_publishes(client, academic_community):
    setup = academic_community()
    proposal = analyze(
        setup.rep, "we now have philosophy every wednesddays insted ofevery thursdays.")
    resp = _publish(setup.rep, proposal)
    assert resp.status_code == 201, resp.get_json()
    entries = setup.rep.get("/api/community/timetable").get_json()["timetable"]
    philosophy = next(e for e in entries if e["id"] == setup.philosophy_entry)
    assert philosophy["day_of_week"] == "WEDNESDAY"


def test_cancellation_publishes_and_preserves_history(client, academic_community):
    setup = academic_community()
    proposal = analyze(setup.rep, "the cos202 assignment has been cancelled")
    assert _publish(setup.rep, proposal).status_code == 201
    detail = setup.rep.get(f"/api/events/{setup.cos202_assignment['id']}").get_json()
    assert detail["event"]["status"] == "CANCELLED"
    # History is preserved, not deleted (spec 16).
    assert any(h["change_type"] == "EVENT_CREATED" for h in detail["history"])
    assert any(h["change_type"] == "EVENT_CANCELLED" for h in detail["history"])


def test_revoked_rep_cannot_publish(client, academic_community, elect_rep, run_worker, app):
    """A rep who loses authority loses it immediately (spec 25)."""
    setup = academic_community(size=6)
    with app.app_context():
        from academicai.db.connection import execute, transaction
        with transaction() as conn:
            execute("""UPDATE community_members SET role = 'STUDENT'
                       WHERE user_id = ? AND community_id = ?""",
                    (setup.rep.user_id, setup.community_id), conn=conn)
    resp = setup.rep.post("/api/ai/publish", json={
        "action": "CREATE", "scope": "EVENT", "title": "Sneaky", "event_type": "QUIZ"})
    assert resp.status_code == 403


def test_publish_requires_a_known_course(client, academic_community):
    setup = academic_community(seed_events=False)
    resp = setup.rep.post("/api/ai/publish", json={
        "action": "CREATE", "scope": "EVENT", "title": "Ghost quiz",
        "event_type": "QUIZ", "course_code": "ZZZ999"})
    assert resp.status_code == 400


def test_update_without_target_is_refused(client, academic_community):
    setup = academic_community()
    resp = setup.rep.post("/api/ai/publish", json={
        "action": "UPDATE", "scope": "EVENT", "event_date": "2026-10-01"})
    assert resp.status_code == 400
