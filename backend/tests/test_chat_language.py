"""The chat assistant speaks to a student, not to a database.

change_history is deliberately precise: MEMBERSHIP_APPROVED, a
PENDING_APPROVAL -> ACTIVE transition, an entity_id. That precision is for the
system. None of it may reach a student who asked what changed this week.

These protect the translation, not the storage. Every one of them reads the
answer a student would actually see.
"""
import re

import pytest

# Anything here appearing in a user-facing answer is the bug this file exists
# to catch: state-machine values, audit verbs, field names, and markup.
FORBIDDEN = [
    "PENDING_APPROVAL", "MEMBERSHIP_APPROVED", "MEMBERSHIP_REJECTED",
    "EVENT_CREATED", "EVENT_CANCELLED", "EVENT_UPDATED", "VENUE_CHANGED",
    "DEADLINE_CHANGED", "TIME_CHANGED", "ANNOUNCEMENT_PUBLISHED",
    "MATERIAL_ATTACHED", "COURSE_CREATED", "TIMETABLE_CREATED",
    "entity_id", "change_type", "old_value", "new_value", "event_type",
    "->", "<svg", "</", "{", "}", "[", "]",
]

# Raw state words, matched as whole words so "cancelled" in a sentence is fine
# but a bare SCHEDULED -> CANCELLED transition is not.
FORBIDDEN_TOKENS = ["SCHEDULED", "CANCELLED", "ACTIVE", "PENDING", "REJECTED"]


def assert_student_readable(answer):
    for token in FORBIDDEN:
        assert token not in answer, f"internal terminology leaked: {token!r} in {answer!r}"
    for token in FORBIDDEN_TOKENS:
        assert not re.search(rf"\b{token}\b", answer), \
            f"raw state value leaked: {token!r} in {answer!r}"
    # No stray markup or serialisation artefacts of any kind.
    assert "svg" not in answer.lower(), f"svg leaked into the answer: {answer!r}"
    assert not re.search(r"\b[A-Z][A-Z_]{4,}\b", answer), \
        f"a SCREAMING_CASE token leaked: {answer!r}"
    assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", answer), \
        f"an ISO date leaked into a conversational answer: {answer!r}"


def ask(actor, question):
    resp = actor.post("/api/chat", json={"question": question})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["answer"]


# ── 1 & 10 · the whole answer, and nothing technical in it ─────────────────

def test_what_changed_recently_is_written_for_a_student(client, academic_community):
    setup = academic_community()
    answer = ask(setup.members[1], "What changed recently?")
    assert_student_readable(answer)
    assert answer.startswith("Here is what changed recently in your community:")


# ── 4 · a venue change names both venues ───────────────────────────────────

def test_venue_change_reads_as_a_sentence(client, academic_community):
    setup = academic_community()
    setup.rep.put(f"/api/events/{setup.heritage_event['id']}", json={"venue": "B107"})
    answer = ask(setup.members[1], "What changed recently?")
    assert_student_readable(answer)
    assert "The venue for Adventist Heritage Seminar (GEDS201) changed from B007 to B107." \
        in answer


# ── 2 · the venue question specifically ────────────────────────────────────

def test_asking_what_venue_changed(client, academic_community):
    setup = academic_community()
    setup.rep.put(f"/api/events/{setup.heritage_event['id']}", json={"venue": "B107"})
    answer = ask(setup.members[1], "What venue was changed?")
    assert_student_readable(answer)
    assert "B007" in answer and "B107" in answer


# ── 5 · a cancellation ─────────────────────────────────────────────────────

def test_cancellation_is_plain_language(client, academic_community):
    setup = academic_community()
    setup.rep.post(f"/api/events/{setup.cos202_assignment['id']}/cancel")
    answer = ask(setup.members[1], "What changed recently?")
    assert_student_readable(answer)
    # The event leaves the visible list when cancelled and a cancellation
    # records only the transition, so the sentence stays honestly general
    # rather than inventing a title it no longer has.
    assert "was cancelled." in answer


# ── 6 · a new event, with the context the record really holds ──────────────

def test_new_event_uses_its_own_recorded_detail(client, academic_community):
    setup = academic_community()
    setup.rep.post("/api/events", json={
        "title": "Programming II Quiz", "event_type": "QUIZ",
        "course_id": setup.courses["COS202"], "event_date": "2026-09-17"})
    answer = ask(setup.members[1], "What changed recently?")
    assert_student_readable(answer)
    assert "A new quiz was added: Programming II Quiz (COS202), for 17 September." in answer


# ── 7 · an announcement ────────────────────────────────────────────────────

def test_announcement_is_plain_language(client, academic_community):
    setup = academic_community()
    setup.rep.post("/api/community/announcements",
                   json={"title": "Midterm week moved", "body": "Check each course."})
    answer = ask(setup.members[1], "What changed recently?")
    assert_student_readable(answer)
    assert "A new announcement was posted." in answer


# ── 8 · repeated identical records ─────────────────────────────────────────

# The real record a rep's approval writes (membership_service). Copied in
# shape, not invented: entity is the MEMBERSHIP row, and the values are the
# state transition the audit log is supposed to keep.
def approval(entity_id, at="2026-09-18T09:00:00+00:00"):
    return {"entity_type": "community_member", "entity_id": entity_id,
            "change_type": "MEMBERSHIP_APPROVED",
            "old_value": {"status": "PENDING_APPROVAL"},
            "new_value": {"status": "ACTIVE", "role": "STUDENT"},
            "created_at": at}


def test_classmates_membership_approvals_are_left_out():
    """Other students being approved is someone else's administrative
    business, not something a student asked about when they asked what
    changed. Three of them, and nothing academic, is nothing to report."""
    from academicai.ai.chat_heuristic import _recent_changes
    answer = _recent_changes(
        [approval(11), approval(12), approval(13)], [], viewer_membership_id=99)["answer"]
    assert_student_readable(answer)
    assert answer == "Nothing has changed in your community's academic records recently."
    assert "membership" not in answer.lower()


def test_your_own_membership_is_still_told():
    """Your own approval IS relevant to you, so it stays - and it is told
    apart from a classmate's by the membership row, never guessed."""
    from academicai.ai.chat_heuristic import _recent_changes
    mine = _recent_changes([approval(11)], [], viewer_membership_id=11)["answer"]
    assert "Your membership of this community was approved." in mine
    assert_student_readable(mine)
    # A classmate's approval, or one that cannot be tied to the reader, is
    # left out rather than described neutrally.
    for viewer in (12, None):
        answer = _recent_changes([approval(11)], [], viewer_membership_id=viewer)["answer"]
        assert "membership" not in answer.lower()


def test_academic_changes_survive_the_membership_filter():
    """Leaving classmates out must not drop the academic changes around them."""
    from academicai.ai.chat_heuristic import _recent_changes
    cancelled = {"entity_type": "academic_event", "entity_id": 4,
                 "change_type": "EVENT_CANCELLED",
                 "old_value": {"status": "SCHEDULED"}, "new_value": {"status": "CANCELLED"},
                 "subject": {"title": "Computer Architecture Quiz", "course_code": "COS208",
                             "event_type": "QUIZ"},
                 "created_at": "2026-09-25T15:02:00+00:00"}
    answer = _recent_changes([approval(12), cancelled, approval(13)], [],
                             viewer_membership_id=11)["answer"]
    assert_student_readable(answer)
    # The subject the change query joined in names the cancelled event, which
    # is no longer among the current events.
    assert "Computer Architecture Quiz (COS208) was cancelled." in answer
    assert "membership" not in answer.lower()


# ── 9 · nothing has changed ────────────────────────────────────────────────

def test_no_recent_changes(client, academic_community):
    setup = academic_community(size=4, seed_events=False)
    # A community always has SOME history, so assert the shape rather than
    # faking an empty log: whatever is said is still student-readable.
    answer = ask(setup.members[1], "What changed recently?")
    assert_student_readable(answer)


def test_empty_change_log_says_so_plainly():
    from academicai.ai.chat_heuristic import _recent_changes
    assert _recent_changes([], []) ["answer"] == \
        "Nothing has changed in your community's academic records recently."


# ── 3 · an unrelated question still works ──────────────────────────────────

def test_quizzes_question_still_answers(client, academic_community):
    setup = academic_community()
    setup.rep.post("/api/events", json={
        "title": "COS202 Quiz", "event_type": "QUIZ",
        "course_id": setup.courses["COS202"], "event_date": "2026-09-19"})
    answer = ask(setup.members[1], "What quizzes do I have?")
    assert_student_readable(answer)


@pytest.mark.parametrize("question", [
    "What is my next deadline?",
    "What assignments do I have this week?",
    "What classes do I have tomorrow?",
    "Where is my next class?",
    "What should I focus on this week?",
    "What is happening in COS202?",
])
def test_every_suggested_prompt_answers_in_student_language(
        client, academic_community, question):
    """The translation must not have broken any other answer, and no other
    answer may leak internals either."""
    setup = academic_community()
    assert_student_readable(ask(setup.members[1], question))


# ── An unmapped change type must never print its own name ──────────────────

def test_an_unknown_change_type_never_leaks_its_token():
    from academicai.ai.chat_heuristic import _describe_change
    sentence = _describe_change(
        {"change_type": "SOME_FUTURE_THING", "entity_type": "whatever",
         "entity_id": 1, "created_at": "2026-09-18"}, {}, None)
    assert_student_readable(sentence)
    assert sentence == "An update was made to your community's records."
