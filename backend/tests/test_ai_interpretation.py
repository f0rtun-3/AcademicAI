"""AI message interpretation (spec 15, 16, 31).

Every message in spec section 31 is covered here verbatim, typos included.
"""
from tests.conftest import analyze


# --- The six worked examples from spec 31 ---------------------------------

def test_case_1_assignment_with_typos(client, academic_community):
    """'WE have cos 202 assignmentto be submittted on friday' -> COS202 assignment Friday."""
    setup = academic_community(seed_events=False)
    proposal = analyze(setup.rep, "WE have cos 202 assignmentto be submittted on friday")
    assert proposal["action"] == "CREATE"
    assert proposal["course_code"] == "COS202"
    assert proposal["event_type"] == "ASSIGNMENT"
    assert proposal["event_date"] == "2026-09-18"   # the Friday after 2026-09-14


def test_case_2_ambiguous_timeframe_asks_for_clarification(client, academic_community):
    """'next two weeks' is not a date -> CLARIFICATION, not an invented date."""
    setup = academic_community()
    proposal = analyze(setup.rep, "We have 212 presentation, to beb presented next two weeks")
    assert proposal["action"] == "CLARIFICATION"
    assert proposal["needs_clarification"] is True
    assert proposal["clarification_question"]
    assert proposal["event_date"] is None


def test_case_3_next_class_without_resolvable_course(client, academic_community):
    """'next class' cannot be resolved without a course -> CLARIFICATION (spec 15)."""
    setup = academic_community()
    proposal = analyze(setup.rep, "We're having a quiz nexgt class on th202")
    assert proposal["action"] == "CLARIFICATION"
    assert proposal["event_type"] == "QUIZ"


def test_case_3_next_class_resolves_from_timetable(client, academic_community):
    """With the course known, 'next class' resolves from the timetable (spec 15)."""
    setup = academic_community()
    proposal = analyze(setup.rep, "We're having a quiz nexgt class",
                       course_id=setup.courses["COS202"])
    assert proposal["action"] == "CREATE"
    assert proposal["event_type"] == "QUIZ"
    assert proposal["event_date"] == "2026-09-16"   # next Wednesday COS202 class


def test_case_4_venue_change_updates_existing_record(client, academic_community):
    """Venue B007 -> B107 must UPDATE the existing record, not duplicate it."""
    setup = academic_community()
    proposal = analyze(
        setup.rep,
        "Guys the venue fo adventist heritage has ben changed from b007 to b107")
    assert proposal["action"] == "UPDATE"
    assert proposal["possible_match_id"] == setup.heritage_event["id"]
    assert proposal["old_value"] == {"venue": "B007"}
    assert proposal["new_value"] == {"venue": "B107"}


def test_case_5_timetable_day_change(client, academic_community):
    """'philosophy every wednesddays insted ofevery thursdays' -> Thursday to Wednesday."""
    setup = academic_community()
    proposal = analyze(
        setup.rep, "we now have philosophy every wednesddays insted ofevery thursdays.")
    assert proposal["scope"] == "TIMETABLE"
    assert proposal["action"] == "UPDATE"
    assert proposal["possible_match_id"] == setup.philosophy_entry
    assert proposal["old_value"] == {"day_of_week": "THURSDAY"}
    assert proposal["new_value"] == {"day_of_week": "WEDNESDAY"}


def test_case_6_deadline_extension(client, academic_community):
    """Existing Friday assignment moves to next Monday."""
    setup = academic_community()
    proposal = analyze(
        setup.rep,
        "The deadline for the cos202 assignment has been extended to next week monday.")
    assert proposal["action"] == "UPDATE"
    assert proposal["possible_match_id"] == setup.cos202_assignment["id"]
    assert proposal["old_value"] == {"event_date": "2026-09-18"}
    assert proposal["new_value"] == {"event_date": "2026-09-21"}


# --- Regression: change with unreadable new value --------------------------

def test_change_with_unparseable_new_date_is_clarification_not_duplicate(
        client, academic_community):
    """Spec 33: this was once misclassified as DUPLICATE. It must be CLARIFICATION."""
    setup = academic_community()
    proposal = analyze(setup.rep, "The deadline for the cos202 assignment has been changed")
    assert proposal["action"] == "CLARIFICATION"
    assert proposal["action"] != "DUPLICATE"
    assert proposal["needs_clarification"] is True


def test_change_with_unparseable_new_venue_is_clarification_not_duplicate(
        client, academic_community):
    setup = academic_community()
    proposal = analyze(setup.rep, "the venue for adventist heritage has been changed")
    assert proposal["action"] == "CLARIFICATION"
    assert "venue" in proposal["clarification_question"].lower()


def test_vague_change_target_is_clarification(client, academic_community):
    setup = academic_community()
    proposal = analyze(
        setup.rep, "the cos202 assignment deadline has been moved to sometime next month")
    assert proposal["action"] == "CLARIFICATION"


# --- Other required cases (spec 31) ---------------------------------------

def test_duplicate_detection(client, academic_community):
    """An identical existing record yields DUPLICATE (spec 16)."""
    setup = academic_community()
    proposal = analyze(setup.rep, "WE have cos 202 assignment to be submittted on friday")
    assert proposal["action"] == "DUPLICATE"
    assert proposal["possible_match_id"] == setup.cos202_assignment["id"]


def test_cancellation(client, academic_community):
    setup = academic_community()
    proposal = analyze(setup.rep, "the cos202 assignment has been cancelled")
    assert proposal["action"] == "CANCEL"
    assert proposal["possible_match_id"] == setup.cos202_assignment["id"]


def test_explicit_unspecified_values_stay_null(client, academic_community):
    """Explicit 'no specified' means null and is not an AI failure (spec 14)."""
    setup = academic_community()
    proposal = analyze(setup.rep, "We have a cos202 test", course_id=setup.courses["COS202"],
                       no_date=True, no_time=True, no_venue=True)
    assert proposal["action"] == "CREATE"
    assert proposal["event_date"] is None
    assert proposal["event_time"] is None
    assert proposal["venue"] is None
    assert proposal["needs_clarification"] is False


def test_discrepancy_between_rep_fields_and_message_is_flagged(client, academic_community):
    """A conflict is surfaced, never silently resolved (spec 15)."""
    setup = academic_community()
    proposal = analyze(setup.rep, "We have a sen212 quiz on friday",
                       course_id=setup.courses["COS202"])
    assert proposal["discrepancies"]
    assert proposal["needs_clarification"] is True


def test_multiple_events_in_one_message_ask_for_clarification(client, academic_community):
    setup = academic_community()
    proposal = analyze(setup.rep, "we have a cos202 quiz on friday and an exam on monday")
    assert proposal["action"] == "CLARIFICATION"


def test_malformed_input_is_rejected(client, academic_community):
    setup = academic_community()
    assert setup.rep.post("/api/ai/analyze-message", json={}).status_code == 400
    assert setup.rep.post("/api/ai/analyze-message", json={"message": "   "}).status_code == 400


def test_overlong_message_is_rejected(client, academic_community):
    setup = academic_community()
    resp = setup.rep.post("/api/ai/analyze-message", json={"message": "x" * 5000})
    assert resp.status_code == 400


def test_analysis_never_writes_to_the_database(client, academic_community, app):
    """The AI proposes; it never mutates (spec 3)."""
    setup = academic_community()
    with app.app_context():
        from academicai.db.connection import query_one
        before = query_one("SELECT COUNT(*) AS n FROM academic_events")["n"]
    analyze(setup.rep, "WE have cos 202 assignmentto be submittted on friday")
    analyze(setup.rep, "the cos202 assignment has been cancelled")
    with app.app_context():
        from academicai.db.connection import query_one
        after = query_one("SELECT COUNT(*) AS n FROM academic_events")["n"]
    assert after == before
