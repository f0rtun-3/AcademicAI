"""What reaches a student is written for a student.

Two surfaces are covered here that the chat-language tests do not reach:

  * the prompt handed to the LLM provider, which must never contain the raw
    change log (a model cannot repeat a state transition it was never given);
  * the recent-changes feed, which must name WHAT each change is about.

And one form concern: a refused registration says which field it refused, so
the sign-up form can put the message beside that field.
"""
import json

from academicai.ai.prompts import CHAT_SYSTEM_PROMPT, build_chat_prompt

RAW = ["change_type", "old_value", "new_value", "entity_id", "MEMBERSHIP_APPROVED",
       "PENDING_APPROVAL", "EVENT_CANCELLED", "DEADLINE_CHANGED", "SCHEDULED", "->"]


def _context(prompt):
    body = prompt.split("<academic_context>\n", 1)[1].split("\n</academic_context>", 1)[0]
    return json.loads(body)


def _request(changes, viewer_membership_id=11):
    return {
        "question": "What changed recently?",
        "today": "2026-09-26",
        "viewer": {"membership_id": viewer_membership_id},
        "community": {"department": "Computer Science", "level": "300",
                      "academic_session": "2026/2027"},
        "courses": [], "timetable": [], "announcements": [], "reminders": [],
        "events": [{"id": 3, "title": "Discrete Mathematics Test", "course_code": "MTH202",
                    "event_type": "TEST", "event_date": "2026-09-30", "event_time": "14:00",
                    "venue": "B107", "status": "SCHEDULED"}],
        "changes": changes,
    }


CHANGES = [
    {"entity_type": "academic_event", "entity_id": 4, "change_type": "EVENT_CANCELLED",
     "old_value": {"status": "SCHEDULED"}, "new_value": {"status": "CANCELLED"},
     "subject": {"title": "Computer Architecture Quiz", "course_code": "COS208",
                 "event_type": "QUIZ"},
     "created_at": "2026-09-25T15:02:00+00:00"},
    {"entity_type": "academic_event", "entity_id": 3, "change_type": "VENUE_CHANGED",
     "old_value": {"venue": "B007"}, "new_value": {"venue": "B107"},
     "created_at": "2026-09-25T10:00:00+00:00"},
    # A classmate's approval: someone else's administrative business.
    {"entity_type": "community_member", "entity_id": 55, "change_type": "MEMBERSHIP_APPROVED",
     "old_value": {"status": "PENDING_APPROVAL"},
     "new_value": {"status": "ACTIVE", "role": "STUDENT"},
     "created_at": "2026-09-24T08:00:00+00:00"},
]


def test_the_llm_never_receives_the_raw_change_log():
    context = _context(build_chat_prompt(_request(CHANGES)))
    serialised = json.dumps(context["recent_changes"])
    for token in RAW:
        assert token not in serialised, f"{token!r} reached the model"
    summaries = [c["summary"] for c in context["recent_changes"]]
    assert summaries == [
        "Computer Architecture Quiz (COS208) was cancelled.",
        "The venue for Discrete Mathematics Test (MTH202) changed from B007 to B107.",
    ]


def test_the_llm_is_not_told_about_classmates_memberships():
    context = _context(build_chat_prompt(_request(CHANGES)))
    assert "membership" not in json.dumps(context["recent_changes"]).lower()
    # ...but the student's own approval is theirs to know.
    mine = dict(CHANGES[2], entity_id=11)
    context = _context(build_chat_prompt(_request([mine], viewer_membership_id=11)))
    assert context["recent_changes"][0]["summary"] == \
        "Your membership of this community was approved."


def test_the_llm_is_given_spoken_dates_to_say():
    context = _context(build_chat_prompt(_request(CHANGES)))
    assert context["today_spoken"] == "Saturday 26 September"
    assert context["events"][0]["date_spoken"] == "Wednesday 30 September at 14:00"
    assert context["events"][0]["type"] == "test"


def test_the_system_prompt_states_the_plain_language_rules():
    rules = CHAT_SYSTEM_PROMPT
    assert "Never expose database field names" in rules
    assert "SCHEDULED -> CANCELLED" in rules          # named as what NOT to write
    assert "Never write ISO dates" in rules
    assert "internal ids" in rules
    assert "other students' membership" in rules
    # It still forbids invention: translation only, never new facts.
    assert "Never invent academic information" in rules
    assert "do not add detail they do not contain" in rules


# ── The feed names its subject ─────────────────────────────────────────────

def test_recent_changes_name_the_record_they_are_about(client, academic_community):
    setup = academic_community()
    event = setup.cos202_assignment
    setup.rep.put(f"/api/events/{event['id']}", json={
        "event_date": "2026-09-21", "expected_version": event["version"]})
    changes = setup.members[1].get("/api/community/changes?limit=20").get_json()["changes"]

    moved = next(c for c in changes if c["change_type"] == "DEADLINE_CHANGED")
    # The row itself holds two dates; the subject says whose.
    assert moved["subject"] == {"title": "COS202 Assignment", "course_code": "COS202",
                                "event_type": "ASSIGNMENT"}
    course = next(c for c in changes if c["change_type"] == "COURSE_CREATED")
    assert course["subject"]["course_code"] in ("COS202", "SEN212", "PHL101", "GEDS201")


# ── Registration says which field it refused ───────────────────────────────

def _payload(**overrides):
    payload = {
        "full_name": "Ada Student", "email": "ada@student.babcock.edu.ng",
        "password": "Password123", "confirm_password": "Password123",
        "university": "Babcock University", "department": "Software Engineering",
        "level": "200", "academic_session": "2026/2027", "student_id_number": "21/1234",
    }
    payload.update(overrides)
    return payload


def _refused_field(client, **overrides):
    resp = client.post("/api/auth/register", json=_payload(**overrides))
    assert resp.status_code in (400, 409), resp.get_json()
    data = resp.get_json()
    return data.get("details", {}).get("field"), data["message"]


def test_a_password_mismatch_points_at_the_confirmation(client):
    field, message = _refused_field(client, confirm_password="Password124")
    assert field == "confirm_password"
    assert message == "Passwords do not match."


def test_a_weak_password_points_at_the_password(client):
    assert _refused_field(client, password="short", confirm_password="short")[0] == "password"


def test_each_refusal_names_its_own_field(client):
    assert _refused_field(client, full_name="")[0] == "full_name"
    assert _refused_field(client, department="")[0] == "department"
    assert _refused_field(client, level="")[0] == "level"
    assert _refused_field(client, academic_session="")[0] == "academic_session"
    assert _refused_field(client, student_id_number="bad*id")[0] == "student_id_number"
    # A domain that does not match the university is about the address...
    assert _refused_field(client, email="ada@gmail.com")[0] == "email"
    # ...an unsupported university is about the university.
    assert _refused_field(client, university="Nowhere University")[0] == "university"


def test_a_duplicate_address_points_at_the_email(client):
    assert client.post("/api/auth/register", json=_payload()).status_code == 201
    field, _ = _refused_field(client)
    assert field == "email"

