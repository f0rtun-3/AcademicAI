"""Academic time: every university has its own IANA clock (spec 20).

    academic wall-clock -> university IANA zone -> UTC instant -> database/worker
    UTC instant -> university IANA zone -> what the student reads

Nothing here hard-codes a zone into the code under test: the seeded Nigerian
universities are Africa/Lagos because the registry says so, and tests that need
another clock set it on the university row, exactly as an operator would.
"""
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from academicai import academic_time, clock
from academicai.ai import provider as ai_provider
from tests.conftest import analyze
from academicai.services.auth_service import TERMS_VERSION  # noqa: E402
# What the sign-up form sends when its Terms box is ticked.
TERMS_ACCEPTED = {"accept_terms": True, "terms_version": TERMS_VERSION}

UTC = timezone.utc


# ── helpers ────────────────────────────────────────────────────────────────

def freeze(iso):
    return clock.freeze(clock.parse_iso(iso))


def set_zone(app, university, zone_name):
    with app.app_context():
        from academicai.db.connection import execute, transaction
        with transaction() as conn:
            execute("UPDATE universities SET timezone = ? WHERE name = ?",
                    (zone_name, university), conn=conn)


def rows(app, sql, params=()):
    with app.app_context():
        from academicai.db.connection import query_all
        return [dict(r) for r in query_all(sql, params)]


def official(app, event_id):
    return rows(app, "SELECT * FROM event_reminders WHERE event_id = ? ORDER BY id", (event_id,))


def personal(app, reminder_id):
    return rows(app, "SELECT * FROM personal_reminders WHERE id = ?", (reminder_id,))[0]


def relogin(setup):
    for member in setup.members:
        member.relogin()


def publish(setup, date, **extra):
    resp = setup.rep.post("/api/events", json={
        "title": extra.pop("title", "COS202 Quiz"), "event_type": extra.pop("event_type", "QUIZ"),
        "course_id": setup.courses["COS202"], "event_date": date, **extra})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["event"]


def remind(actor, **body):
    return actor.post("/api/reminders", json={"title": "Revise", **body})


# ── The academic_time module itself ─────────────────────────────────────────

@pytest.mark.parametrize("name", ["Africa/Lagos", "Europe/London", "America/New_York"])
def test_a_geographic_iana_zone_is_accepted(name):
    assert academic_time.zone(name).key == name


@pytest.mark.parametrize("name", [None, "", "  ", "UTC", "GMT", "Etc/GMT-1", "+01:00",
                                  "Mars/Olympus_Mons", "../../etc/passwd"])
def test_a_missing_offset_or_unknown_zone_is_refused(name):
    with pytest.raises(academic_time.InvalidTimezone):
        academic_time.zone(name)


def test_a_skipped_local_time_moves_forward_by_the_gap():
    """zoneinfo fold=0: 01:30 on the UK spring-forward night does not exist
    (01:00 GMT -> 02:00 BST). It fires at the instant the zone calls 02:30."""
    london = academic_time.zone("Europe/London")
    instant = academic_time.local_to_instant(datetime(2027, 3, 28, 1, 30), london)
    assert instant == datetime(2027, 3, 28, 1, 30, tzinfo=UTC)
    assert academic_time.local_string(instant, london) == "2027-03-28T02:30"


def test_a_repeated_local_time_means_its_first_occurrence():
    """zoneinfo fold=0: 01:30 on the fall-back night happens twice. It means
    the first, still on summer time (BST, UTC+1)."""
    london = academic_time.zone("Europe/London")
    instant = academic_time.local_to_instant(datetime(2026, 10, 25, 1, 30), london)
    assert instant == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    assert academic_time.local_string(instant, london) == "2026-10-25T01:30"


def test_today_is_the_university_date_not_the_utc_date():
    freeze("2026-09-16T23:30:00+00:00")              # 00:30 on the 17th in Lagos
    assert academic_time.today(academic_time.zone("Africa/Lagos")).isoformat() == "2026-09-17"
    assert academic_time.today(academic_time.zone("America/New_York")).isoformat() == "2026-09-16"


# ── Instants must state their offset ────────────────────────────────────────

def test_an_offsetless_instant_is_refused_not_read_as_utc():
    with pytest.raises(ValueError):
        clock.parse_iso("2026-09-27T08:00:00")
    with pytest.raises(ValueError):
        clock.to_iso(datetime(2026, 9, 27, 8, 0))


def test_an_instant_with_an_offset_or_z_is_accepted():
    assert clock.parse_iso("2026-09-27T08:00:00+01:00") == datetime(2026, 9, 27, 7, tzinfo=UTC)
    assert clock.parse_iso("2026-09-27T07:00:00Z") == datetime(2026, 9, 27, 7, tzinfo=UTC)


# ── Official reminders: 08:00 the academic day before, on the university clock ──

@pytest.mark.parametrize("zone_name, event_date, expected", [
    ("Africa/Lagos", "2026-10-20", "2026-10-19T07:00:00+00:00"),      # WAT, UTC+1
    ("Europe/London", "2026-10-25", "2026-10-24T07:00:00+00:00"),     # BST, before the change
    ("Europe/London", "2026-10-26", "2026-10-25T08:00:00+00:00"),     # GMT, after it
    ("America/New_York", "2026-10-20", "2026-10-19T12:00:00+00:00"),  # EDT, UTC-4: same day
])
def test_the_official_reminder_is_0800_on_the_university_clock(
        client, app, academic_community, zone_name, event_date, expected):
    set_zone(app, "Babcock University", zone_name)
    setup = academic_community(seed_events=False)
    event = publish(setup, event_date)
    assert [r["remind_at"] for r in official(app, event["id"])] == [expected]


def test_two_universities_on_different_clocks_fire_at_different_instants(
        client, app, academic_community):
    set_zone(app, "Covenant University", "America/New_York")
    lagos = academic_community(seed_events=False)
    new_york = academic_community(seed_events=False, university="Covenant University")
    relogin(lagos)
    a = publish(lagos, "2026-10-20")
    b = publish(new_york, "2026-10-20")
    assert official(app, a["id"])[0]["remind_at"] == "2026-10-19T07:00:00+00:00"
    assert official(app, b["id"])[0]["remind_at"] == "2026-10-19T12:00:00+00:00"


def test_the_worker_fires_on_the_stored_utc_instant(client, app, academic_community, run_worker):
    setup = academic_community(seed_events=False)
    event = publish(setup, "2026-09-25")                         # reminder 07:00Z (08:00 Lagos)
    freeze("2026-09-24T06:59:59+00:00")
    run_worker()
    assert official(app, event["id"])[0]["status"] == "PENDING"
    freeze("2026-09-24T07:00:00+00:00")
    run_worker()
    assert official(app, event["id"])[0]["status"] == "SENT"


def test_moving_an_event_across_a_dst_change_reschedules_on_the_new_offset(
        client, app, academic_community):
    set_zone(app, "Babcock University", "Europe/London")
    setup = academic_community(seed_events=False)
    event = publish(setup, "2026-10-25")
    resp = setup.rep.put(f"/api/events/{event['id']}", json={"event_date": "2026-10-26"})
    assert resp.status_code == 200, resp.get_json()
    reminders = official(app, event["id"])
    assert [(r["status"], r["remind_at"]) for r in reminders] == [
        ("CANCELLED", "2026-10-24T07:00:00+00:00"),
        ("PENDING", "2026-10-25T08:00:00+00:00"),
    ]


# ── Late publishing: no reminder after its moment, and no substitute ─────────

def test_an_event_published_before_its_reminder_moment_gets_one(client, app, academic_community):
    setup = academic_community(seed_events=False)
    freeze("2026-09-27T06:59:00+00:00")                          # 07:59 Sunday, Lagos
    relogin(setup)
    event = publish(setup, "2026-09-28", event_time="10:00")     # Monday 10:00
    assert [(r["status"], r["remind_at"]) for r in official(app, event["id"])] == [
        ("PENDING", "2026-09-27T07:00:00+00:00")]


def test_an_event_published_after_its_reminder_moment_gets_none(client, app, academic_community):
    setup = academic_community(seed_events=False)
    freeze("2026-09-27T07:01:00+00:00")                          # 08:01 Sunday, Lagos
    relogin(setup)
    event = publish(setup, "2026-09-28", event_time="10:00")     # Monday 10:00
    assert official(app, event["id"]) == []


# ── Personal reminders: remind_at_local on the university clock ─────────────

def test_remind_at_local_is_read_on_the_university_clock(client, app, academic_community):
    setup = academic_community(seed_events=False)
    resp = remind(setup.members[1], remind_at_local="2026-09-27T08:00")
    assert resp.status_code == 201, resp.get_json()
    reminder = resp.get_json()["reminder"]
    assert reminder["remind_at"] == "2026-09-27T07:00:00+00:00"
    assert reminder["remind_at_local"] == "2026-09-27T08:00"
    assert reminder["timezone"] == "Africa/Lagos"


def test_a_linked_reminder_uses_its_events_university_clock(client, app, academic_community):
    set_zone(app, "Babcock University", "America/New_York")
    setup = academic_community(seed_events=False)
    event = publish(setup, "2026-10-20")
    reminder = remind(setup.members[1], event_id=event["id"],
                      remind_at_local="2026-10-19T20:00").get_json()["reminder"]
    assert reminder["remind_at"] == "2026-10-20T00:00:00+00:00"   # 20:00 EDT
    assert reminder["timezone"] == "America/New_York"


def test_an_explicit_offset_remind_at_is_still_accepted(client, academic_community):
    setup = academic_community(seed_events=False)
    reminder = remind(setup.members[1],
                      remind_at="2026-09-27T08:00:00+01:00").get_json()["reminder"]
    assert reminder["remind_at"] == "2026-09-27T07:00:00+00:00"
    assert reminder["remind_at_local"] == "2026-09-27T08:00"


def test_an_offsetless_remind_at_is_refused(client, academic_community):
    setup = academic_community(seed_events=False)
    resp = remind(setup.members[1], remind_at="2026-09-27T08:00:00")
    assert resp.status_code == 400
    assert "remind_at_local" in resp.get_json()["message"]


@pytest.mark.parametrize("value", [
    "2026-09-27 08:00", "2026-09-27T08:00:00", "2026-09-27T08:00Z", "2026-09-27T08:00+01:00",
    "27/09/2026 08:00", "2026-02-30T08:00", "2026-09-27T25:00", "tomorrow at 8", 1727420400,
])
def test_a_malformed_remind_at_local_is_refused(client, academic_community, value):
    setup = academic_community(seed_events=False)
    assert remind(setup.members[1], remind_at_local=value).status_code == 400


def test_a_malformed_remind_at_is_refused(client, academic_community):
    setup = academic_community(seed_events=False)
    assert remind(setup.members[1], remind_at="next friday").status_code == 400


def test_sending_both_forms_is_refused_as_ambiguous(client, academic_community):
    setup = academic_community(seed_events=False)
    resp = remind(setup.members[1], remind_at_local="2026-09-27T08:00",
                  remind_at="2026-09-27T07:00:00+00:00")
    assert resp.status_code == 400
    assert "not both" in resp.get_json()["message"]


def test_a_reminder_cannot_choose_another_timezone(client, academic_community):
    setup = academic_community(seed_events=False)
    student = setup.members[1]
    assert remind(student, remind_at_local="2026-09-27T08:00",
                  timezone="Europe/London").status_code == 400
    # Posting the API's own payload back (its timezone included) is fine.
    assert remind(student, remind_at_local="2026-09-27T08:00",
                  timezone="Africa/Lagos").status_code == 201


def test_editing_with_remind_at_local_moves_it_and_a_title_edit_keeps_it(
        client, academic_community):
    setup = academic_community(seed_events=False)
    student = setup.members[1]
    reminder = remind(student, remind_at_local="2026-09-27T08:00").get_json()["reminder"]
    moved = student.put(f"/api/reminders/{reminder['id']}",
                        json={"remind_at_local": "2026-09-28T18:30"}).get_json()["reminder"]
    assert moved["remind_at"] == "2026-09-28T17:30:00+00:00"
    kept = student.put(f"/api/reminders/{reminder['id']}",
                       json={"title": "Revise trees"}).get_json()["reminder"]
    assert kept["remind_at"] == "2026-09-28T17:30:00+00:00"
    assert kept["remind_at_local"] == "2026-09-28T18:30"


def test_a_skipped_local_time_is_stored_as_the_moment_it_really_fires(
        client, app, academic_community):
    set_zone(app, "Babcock University", "Europe/London")
    setup = academic_community(seed_events=False)
    reminder = remind(setup.members[1], remind_at_local="2027-03-28T01:30").get_json()["reminder"]
    assert reminder["remind_at"] == "2027-03-28T01:30:00+00:00"
    assert reminder["remind_at_local"] == "2027-03-28T02:30"      # what the student is shown


def test_a_repeated_local_time_is_stored_as_its_first_occurrence(
        client, app, academic_community):
    set_zone(app, "Babcock University", "Europe/London")
    setup = academic_community(seed_events=False)
    reminder = remind(setup.members[1], remind_at_local="2026-10-25T01:30").get_json()["reminder"]
    assert reminder["remind_at"] == "2026-10-25T00:30:00+00:00"   # 01:30 BST
    assert reminder["remind_at_local"] == "2026-10-25T01:30"


def test_a_personal_reminder_fires_on_its_utc_instant(client, app, academic_community, run_worker):
    setup = academic_community(seed_events=False)
    reminder = remind(setup.members[1], remind_at_local="2026-09-20T08:00").get_json()["reminder"]
    freeze("2026-09-20T06:59:59+00:00")
    run_worker()
    assert personal(app, reminder["id"])["status"] == "PENDING"
    freeze("2026-09-20T07:00:00+00:00")
    run_worker()
    assert personal(app, reminder["id"])["status"] == "SENT"


def test_reminder_lists_carry_the_local_time_for_display(client, academic_community):
    setup = academic_community(seed_events=False)
    student = setup.members[1]
    remind(student, remind_at_local="2026-09-27T00:30")            # 23:30Z the day before
    listed = student.get("/api/reminders").get_json()["reminders"][0]
    assert (listed["remind_at"], listed["remind_at_local"]) == (
        "2026-09-26T23:30:00+00:00", "2026-09-27T00:30")
    on_dashboard = student.get("/api/dashboard").get_json()["reminders"][0]
    assert on_dashboard["remind_at_local"] == "2026-09-27T00:30"


# ── Cancelling an event ─────────────────────────────────────────────────────

def test_cancelling_an_event_cancels_its_linked_reminders_and_nothing_else(
        client, app, academic_community, run_worker):
    setup = academic_community(seed_events=False)
    student, other = setup.members[1], setup.members[2]
    event = publish(setup, "2026-10-20")
    linked = remind(student, event_id=event["id"],
                    remind_at_local="2026-10-19T20:00").get_json()["reminder"]
    unrelated = remind(student, remind_at_local="2026-10-19T20:00").get_json()["reminder"]
    # Already fired before the cancellation: history, and must stay history.
    fired = remind(other, event_id=event["id"],
                   remind_at_local="2026-09-16T08:00").get_json()["reminder"]
    freeze("2026-09-16T07:00:00+00:00")
    run_worker()
    fired_before = personal(app, fired["id"])
    assert fired_before["status"] == "SENT"

    relogin(setup)
    assert setup.rep.post(f"/api/events/{event['id']}/cancel").status_code == 200

    assert [r["status"] for r in official(app, event["id"])] == ["CANCELLED"]
    assert personal(app, linked["id"])["status"] == "CANCELLED"
    assert personal(app, unrelated["id"])["status"] == "PENDING"
    assert personal(app, fired["id"]) == fired_before


def test_cancelling_never_rewrites_an_official_reminder_that_already_fired(
        client, app, academic_community, run_worker):
    setup = academic_community(seed_events=False)
    event = publish(setup, "2026-09-17")                         # reminder 2026-09-16T07:00Z
    freeze("2026-09-16T07:05:00+00:00")
    run_worker()
    sent = official(app, event["id"])
    assert [r["status"] for r in sent] == ["SENT"]
    relogin(setup)
    assert setup.rep.post(f"/api/events/{event['id']}/cancel").status_code == 200
    assert official(app, event["id"]) == sent


def test_a_linked_reminder_for_an_event_cancelled_earlier_is_withdrawn_not_sent(
        client, app, academic_community, run_worker):
    """An event cancelled before cancellation reached linked reminders left
    them PENDING. The worker withdraws such a reminder instead of sending it."""
    setup = academic_community(seed_events=False)
    event = publish(setup, "2026-10-20")
    linked = remind(setup.members[1], event_id=event["id"],
                    remind_at_local="2026-09-20T08:00").get_json()["reminder"]
    with app.app_context():
        from academicai.db.connection import execute, transaction
        with transaction() as conn:
            execute("UPDATE academic_events SET status = 'CANCELLED' WHERE id = ?",
                    (event["id"],), conn=conn)
    freeze("2026-09-20T07:00:00+00:00")
    run_worker()
    assert personal(app, linked["id"])["status"] == "CANCELLED"
    assert rows(app, "SELECT * FROM notifications WHERE dedupe_key = ?",
                (f"personal_reminder:{linked['id']}",)) == []


# ── Chat reminders ──────────────────────────────────────────────────────────

def test_the_built_in_suggestion_is_university_local_and_accepted_unchanged(
        client, academic_community):
    setup = academic_community()                    # COS202 Assignment due 2026-09-18
    student = setup.members[1]
    result = student.post("/api/chat", json={"question": "What is my next deadline?"}).get_json()
    suggestion = result["suggested_reminder"]
    assert suggestion == {"title": "Prepare for COS202 Assignment",
                          "remind_at_local": "2026-09-17T08:00",
                          "timezone": "Africa/Lagos",
                          "event_id": setup.cos202_assignment["id"]}
    resp = student.post("/api/reminders", json=suggestion)
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["reminder"]["remind_at"] == "2026-09-17T07:00:00+00:00"


def test_a_built_in_suggestion_whose_moment_has_passed_is_not_offered(client, academic_community):
    setup = academic_community()
    freeze("2026-09-17T07:30:00+00:00")             # 08:30 on the 17th in Lagos
    relogin(setup)
    result = setup.members[1].post(
        "/api/chat", json={"question": "What is my next deadline?"}).get_json()
    assert "COS202 Assignment" in result["answer"]
    assert result["suggested_reminder"] is None


class _Provider:
    """A stand-in model: returns whatever suggestion the test hands it."""
    name = "stub"

    def __init__(self, suggestion):
        self.suggestion = suggestion
        self.seen = None

    def answer(self, request):
        self.seen = request
        return {"answer": "Here you go.", "grounded": True, "referenced_event_ids": [],
                "suggested_reminder": self.suggestion}


def _ask_with(student, suggestion):
    stub = _Provider(suggestion)
    ai_provider.set_provider(stub)
    try:
        result = student.post("/api/chat", json={"question": "Remind me"}).get_json()
    finally:
        ai_provider.set_provider(None)
    return result, stub


def test_the_model_is_given_the_zone_and_academic_now_not_utc(client, academic_community):
    setup = academic_community()
    remind(setup.members[1], remind_at_local="2026-09-27T08:00")
    freeze("2026-09-16T23:30:00+00:00")             # 00:30 on the 17th in Lagos
    relogin(setup)
    _result, stub = _ask_with(setup.members[1], None)
    assert stub.seen["timezone"] == "Africa/Lagos"
    assert stub.seen["today"] == "2026-09-17"
    assert stub.seen["now_local"] == "2026-09-17T00:30"
    from academicai.ai.prompts import CHAT_SYSTEM_PROMPT, build_chat_prompt
    prompt = build_chat_prompt(stub.seen)
    assert '"timezone": "Africa/Lagos"' in prompt
    assert '"remind_at_local": "2026-09-27T08:00"' in prompt
    assert "+00:00" not in prompt.split('"personal_reminders"')[1]
    assert "YYYY-MM-DDTHH:MM" in CHAT_SYSTEM_PROMPT


def test_the_models_schema_asks_for_a_local_time_not_an_instant():
    from academicai.ai.anthropic_provider import CHAT_JSON_SCHEMA
    fields = CHAT_JSON_SCHEMA["properties"]["suggested_reminder"]["properties"]
    assert set(fields) == {"title", "remind_at_local", "event_id"}


def test_a_valid_model_suggestion_is_normalised_for_the_student(client, academic_community):
    setup = academic_community()
    event_id = setup.cos202_assignment["id"]                    # due 2026-09-18, no time
    result, _ = _ask_with(setup.members[1], {
        "title": " Start the COS202 assignment ", "remind_at_local": "2026-09-17T18:00",
        "event_id": event_id})
    assert result["suggested_reminder"] == {
        "title": "Start the COS202 assignment", "remind_at_local": "2026-09-17T18:00",
        "timezone": "Africa/Lagos", "event_id": event_id}


def _bad_suggestions(event_id):
    return [
        {"title": "x", "remind_at_local": "2026-09-17T18:00:00"},        # seconds
        {"title": "x", "remind_at_local": "2026-09-17T18:00Z"},          # Z
        {"title": "x", "remind_at_local": "2026-09-17T18:00+01:00"},     # an offset
        {"title": "x", "remind_at_local": "2026-09-17T17:00:00+00:00"},  # a UTC instant
        {"title": "x", "remind_at": "2026-09-17T17:00:00+00:00"},        # the old field
        {"title": "x", "remind_at_local": "tomorrow evening"},           # prose
        {"title": "x", "remind_at_local": "2026-09-13T08:00"},           # in the past
        {"title": "", "remind_at_local": "2026-09-17T18:00"},            # no title
        {"title": "x", "remind_at_local": "2026-09-17T18:00", "event_id": 99999},  # not theirs
        {"title": "x", "remind_at_local": "2026-09-19T08:00", "event_id": event_id},  # after it
        {"title": "x", "remind_at_local": "2026-09-17T18:00", "event_id": True},
        "remind me tomorrow",
    ]


def test_invalid_or_impossible_model_suggestions_never_reach_the_student(
        client, academic_community):
    setup = academic_community()
    event_id = setup.cos202_assignment["id"]
    for bad in _bad_suggestions(event_id):
        result, _ = _ask_with(setup.members[1], bad)
        assert result["suggested_reminder"] is None, bad
        assert result["answer"] == "Here you go."


def test_a_suggestion_for_a_cancelled_event_is_dropped(client, academic_community):
    setup = academic_community()
    event_id = setup.cos202_assignment["id"]
    assert setup.rep.post(f"/api/events/{event_id}/cancel").status_code == 200
    result, _ = _ask_with(setup.members[1], {
        "title": "x", "remind_at_local": "2026-09-17T18:00", "event_id": event_id})
    assert result["suggested_reminder"] is None


def test_a_suggestion_exactly_at_the_event_start_is_offered(client, academic_community):
    """Spec 20 drops a suggestion only when it comes AFTER its event, so the
    event's own start is still acceptable; one minute later is not."""
    setup = academic_community()
    student = setup.members[1]
    event = publish(setup, "2026-09-28", event_time="10:00")     # Monday 10:00 Lagos
    result, _ = _ask_with(student, {
        "title": "Quiz starts", "remind_at_local": "2026-09-28T10:00", "event_id": event["id"]})
    assert result["suggested_reminder"] == {
        "title": "Quiz starts", "remind_at_local": "2026-09-28T10:00",
        "timezone": "Africa/Lagos", "event_id": event["id"]}
    resp = student.post("/api/reminders", json=result["suggested_reminder"])
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["reminder"]["remind_at"] == "2026-09-28T09:00:00+00:00"

    late, _ = _ask_with(student, {
        "title": "Quiz starts", "remind_at_local": "2026-09-28T10:01", "event_id": event["id"]})
    assert late["suggested_reminder"] is None


def test_a_date_only_event_allows_its_whole_day_but_not_the_next(client, academic_community):
    setup = academic_community()
    event_id = setup.cos202_assignment["id"]                    # due 2026-09-18, no time
    last_minute, _ = _ask_with(setup.members[1], {
        "title": "x", "remind_at_local": "2026-09-18T23:59", "event_id": event_id})
    assert last_minute["suggested_reminder"]["remind_at_local"] == "2026-09-18T23:59"
    next_day, _ = _ask_with(setup.members[1], {
        "title": "x", "remind_at_local": "2026-09-19T00:00", "event_id": event_id})
    assert next_day["suggested_reminder"] is None


# ── "Today" and "tomorrow" around midnight in Lagos ────────────────────────

def test_chat_tomorrow_at_0030_lagos_is_the_lagos_tomorrow(client, academic_community):
    """00:30 Thursday 17th in Lagos is still Wednesday 16th in UTC. Tomorrow is
    Friday 18th (COS202 Assignment due), not Thursday (Philosophy class)."""
    setup = academic_community()
    freeze("2026-09-16T23:30:00+00:00")
    relogin(setup)
    answer = setup.members[1].post(
        "/api/chat", json={"question": "What classes do I have tomorrow?"}).get_json()["answer"]
    assert "COS202" in answer
    assert "Philosophy" not in answer


def test_dashboard_upcoming_at_0030_lagos_starts_from_the_lagos_date(client, academic_community):
    setup = academic_community(seed_events=False)
    yesterday = publish(setup, "2026-09-16", title="Yesterday's quiz")
    today = publish(setup, "2026-09-17", title="Today's quiz")
    freeze("2026-09-16T23:30:00+00:00")
    relogin(setup)
    upcoming = {e["id"] for e in setup.members[1].get("/api/dashboard").get_json()["upcoming"]}
    assert today["id"] in upcoming
    assert yesterday["id"] not in upcoming


def test_a_rep_posting_due_tomorrow_at_0030_lagos_gets_the_lagos_tomorrow(
        client, academic_community):
    setup = academic_community(seed_events=False)
    freeze("2026-09-16T23:30:00+00:00")
    relogin(setup)
    proposal = analyze(setup.rep, "COS202 assignment is due tomorrow")
    assert proposal["event_date"] == "2026-09-18"


def test_a_calendar_date_without_a_year_reads_the_lagos_year(client, academic_community):
    """00:30 on 1 January in Lagos is still 31 December in UTC."""
    setup = academic_community(seed_events=False)
    freeze("2026-12-31T23:30:00+00:00")
    relogin(setup)
    resp = setup.rep.post("/api/community/calendar",
                          json={"raw_text": "Session begins: 12 January\nSession ends: 16 July"})
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["calendar"]["session_start"] == "2027-01-12"


# ── The zone reaches the client ─────────────────────────────────────────────

def test_the_session_community_and_event_carry_the_academic_clock(
        client, app, academic_community):
    setup = academic_community()
    student = setup.members[1]
    assert student.get("/api/auth/me").get_json()["timezone"] == "Africa/Lagos"
    assert student.get("/api/community").get_json()["community"]["timezone"] == "Africa/Lagos"
    detail = student.get(f"/api/events/{setup.cos202_assignment['id']}").get_json()
    assert detail["reminder_default_local"] == "2026-09-17T08:00"
    set_zone(app, "Babcock University", "Europe/London")
    assert student.get("/api/auth/me").get_json()["timezone"] == "Europe/London"


def test_sign_up_never_creates_a_university_without_a_clock(client, app):
    """Even with development's relaxed email check, an unknown university is
    refused instead of being created with no timezone."""
    app.config["ALLOW_ANY_EMAIL_DOMAIN"] = True
    try:
        resp = client.post("/api/auth/register", json={**TERMS_ACCEPTED, 
            "full_name": "New Place", "email": "someone@example.com",
            "password": "Password123", "confirm_password": "Password123",
            "university": "University of Nowhere", "department": "SE",
            "level": "200", "academic_session": "2026/2027",
            "student_id_number": "BU/SEN/9901"})
    finally:
        app.config["ALLOW_ANY_EMAIL_DOMAIN"] = False
    assert resp.status_code == 400
    assert resp.get_json()["details"]["field"] == "university"
    assert rows(app, "SELECT * FROM universities WHERE name = 'University of Nowhere'") == []


# ── Migrating a database from before universities had a clock ─────────────

def _file_app(path):
    from academicai.app import create_app
    from academicai.config import TestConfig

    class FileConfig(TestConfig):
        DATABASE_PATH = path
        SQLITE_WAL = True

    return create_app(FileConfig)


def _legacy_database(tmp_path, extra_university=None):
    """A real database, then the timezone column removed: exactly what a
    deployment from before this change looks like. Official reminders carry
    the old 08:00 UTC instants."""
    path = str(tmp_path / "legacy.db")
    _file_app(path)
    conn = sqlite3.connect(path)
    now = "2026-09-14T09:00:00+00:00"
    babcock = conn.execute("SELECT id FROM universities WHERE name = 'Babcock University'"
                           ).fetchone()[0]
    conn.execute("""INSERT INTO users (id, full_name, email, password_hash, university_id,
                    created_at, updated_at) VALUES (1, 'Legacy', 'l@student.babcock.edu.ng',
                    'x', ?, ?, ?)""", (babcock, now, now))
    conn.execute("""INSERT INTO academic_communities (id, university_id, department, level,
                    academic_session, status, created_at, updated_at)
                    VALUES (1, ?, 'SE', '200', '2026/2027', 'ACTIVE', ?, ?)""",
                 (babcock, now, now))
    for event_id, status, date in ((1, "SCHEDULED", "2026-10-20"), (2, "CANCELLED", "2026-10-21"),
                                   (3, "SCHEDULED", "2026-10-22")):
        conn.execute("""INSERT INTO academic_events (id, community_id, event_type, title,
                        event_date, status, created_by, created_at, updated_at)
                        VALUES (?, 1, 'QUIZ', 'Quiz', ?, ?, 1, ?, ?)""",
                     (event_id, date, status, now, now))
    reminders = (
        (1, 1, "2026-10-19T08:00:00+00:00", "PENDING"),    # -> 07:00Z
        (2, 2, "2026-10-20T08:00:00+00:00", "PENDING"),    # event cancelled: untouched
        (3, 3, "2026-09-10T08:00:00+00:00", "SENT"),       # history: untouched
        (4, 3, "2026-10-21T08:00:00+00:00", "CANCELLED"),  # history: untouched
        (5, 3, "2026-10-21T08:00:00+00:00", "PENDING"),    # -> 07:00Z
    )
    for rid, event_id, at, status in reminders:
        conn.execute("""INSERT INTO event_reminders (id, event_id, remind_at, status, created_at)
                        VALUES (?, ?, ?, ?, ?)""", (rid, event_id, at, status, now))
    for rid, at, status in ((1, "2026-10-19T08:00:00+00:00", "PENDING"),
                            (2, "2026-09-10T08:00:00+00:00", "SENT")):
        conn.execute("""INSERT INTO personal_reminders (id, user_id, event_id, title, remind_at,
                        status, created_at) VALUES (?, 1, 1, 'Mine', ?, ?, ?)""",
                     (rid, at, status, now))
    if extra_university:
        conn.execute("INSERT INTO universities (name, created_at, timezone) VALUES (?, ?, 'x')",
                     (extra_university, now))
    conn.execute("ALTER TABLE universities DROP COLUMN timezone")
    conn.commit()
    conn.close()
    return path


def _personal(path):
    conn = sqlite3.connect(path)
    out = conn.execute("SELECT * FROM personal_reminders ORDER BY id").fetchall()
    conn.close()
    return out


def _snapshot(path):
    conn = sqlite3.connect(path)
    out = {
        "universities": conn.execute("SELECT name, timezone FROM universities ORDER BY id").fetchall(),
        "official": conn.execute("SELECT id, remind_at, status FROM event_reminders ORDER BY id").fetchall(),
        "personal": conn.execute("SELECT * FROM personal_reminders ORDER BY id").fetchall(),
    }
    conn.close()
    return out


def test_migration_backfills_zones_and_moves_only_pending_official_reminders(tmp_path):
    path = _legacy_database(tmp_path)
    personal_before = _personal(path)

    _file_app(path)
    after = _snapshot(path)
    assert {tz for _name, tz in after["universities"]} == {"Africa/Lagos"}
    assert after["official"] == [
        (1, "2026-10-19T07:00:00+00:00", "PENDING"),
        (2, "2026-10-20T08:00:00+00:00", "PENDING"),
        (3, "2026-09-10T08:00:00+00:00", "SENT"),
        (4, "2026-10-21T08:00:00+00:00", "CANCELLED"),
        (5, "2026-10-21T07:00:00+00:00", "PENDING"),
    ]
    assert after["personal"] == personal_before        # intent unknown: never shifted

    _file_app(path)                                    # idempotent
    assert _snapshot(path) == after


def test_migration_keeps_a_zone_an_operator_already_set(tmp_path):
    path = _legacy_database(tmp_path)
    _file_app(path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE universities SET timezone = 'America/New_York' "
                 "WHERE name = 'Covenant University'")
    conn.commit()
    conn.close()
    _file_app(path)
    zones = dict(_snapshot(path)["universities"])
    assert zones["Covenant University"] == "America/New_York"


def test_start_up_refuses_a_university_it_cannot_give_a_clock(tmp_path):
    path = _legacy_database(tmp_path, extra_university="Unlisted University")
    with pytest.raises(RuntimeError) as excinfo:
        _file_app(path)
    message = str(excinfo.value)
    assert "Unlisted University" in message
    assert "No timezone has been assumed or written" in message
    # Nothing was guessed - not even for the universities it does know.
    assert {tz for _name, tz in _snapshot(path)["universities"]} == {None}


def test_start_up_refuses_a_fixed_offset_or_unknown_zone(tmp_path):
    path = str(tmp_path / "bad.db")
    _file_app(path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE universities SET timezone = 'UTC' WHERE name = 'Babcock University'")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError) as excinfo:
        _file_app(path)
    assert "Babcock University" in str(excinfo.value)
    assert "not a geographic IANA timezone" in str(excinfo.value)
