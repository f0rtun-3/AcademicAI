"""A reminder fires at the wall-clock time the student picked, in their zone.

The pipeline is: the browser turns the picked local time into an absolute
instant WITH its offset (DST included) -> the API parses it -> the database
stores it as UTC -> the worker compares UTC instants -> the notification is
created at that instant.

The bug these guard against: Event Detail sent the picked digits relabelled as
UTC ("08:00" + "+00:00"), so a Lagos reminder set for 08:00 fired at 09:00.
The fix is not an hour's arithmetic anywhere; it is that the offset is never
lost or guessed. So the tests state times in real zones and check the instant
end to end.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from academicai import clock

LAGOS = ZoneInfo("Africa/Lagos")      # UTC+1 all year, no DST
LONDON = ZoneInfo("Europe/London")    # observes DST: +1 until 25 Oct 2026, then +0


def local(zone, *parts):
    """The instant a browser in `zone` sends for a picked wall-clock time."""
    return datetime(*parts, tzinfo=zone)


def create(actor, title, instant):
    resp = actor.post("/api/reminders",
                      json={"title": title, "remind_at": instant.isoformat()})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["reminder"]


def fired(actor, title):
    items = actor.get("/api/notifications").get_json()["notifications"]
    return [n for n in items if n["kind"] == "PERSONAL_REMINDER" and n["subject"] == title]


def run_at(run_worker, actor, instant):
    clock.freeze(instant.astimezone(ZoneInfo("UTC")))
    run_worker()
    actor.relogin()


def test_a_lagos_reminder_is_stored_as_the_right_instant(client, academic_community):
    setup = academic_community()
    student = setup.members[1]
    picked = local(LAGOS, 2026, 9, 27, 8, 0)          # 08:00 in Lagos
    reminder = create(student, "Revise pointers", picked)
    # 08:00 WAT is 07:00 UTC. Not 08:00 UTC - that was the bug.
    assert reminder["remind_at"] == "2026-09-27T07:00:00+00:00"


def test_a_lagos_reminder_fires_at_eight_local_and_not_before(
        client, academic_community, run_worker):
    setup = academic_community()
    student = setup.members[1]
    create(student, "Revise pointers", local(LAGOS, 2026, 9, 27, 8, 0))

    run_at(run_worker, student, local(LAGOS, 2026, 9, 27, 7, 59))
    assert fired(student, "Revise pointers") == []

    run_at(run_worker, student, local(LAGOS, 2026, 9, 27, 8, 0))
    notes = fired(student, "Revise pointers")
    assert len(notes) == 1
    # The notification is created at the intended local time.
    created = datetime.fromisoformat(notes[0]["created_at"]).astimezone(LAGOS)
    assert (created.hour, created.minute) == (8, 0)


@pytest.mark.parametrize("day, expected_utc", [
    (24, "2026-10-24T07:00:00+00:00"),   # British Summer Time: 08:00 = 07:00 UTC
    (26, "2026-10-26T08:00:00+00:00"),   # after the clocks go back: 08:00 = 08:00 UTC
])
def test_the_same_local_time_either_side_of_a_dst_change(
        client, academic_community, run_worker, day, expected_utc):
    """Not a fixed offset: the zone's own rules decide the instant."""
    setup = academic_community()
    student = setup.members[1]
    picked = local(LONDON, 2026, 10, day, 8, 0)
    reminder = create(student, f"Seminar prep {day}", picked)
    assert reminder["remind_at"] == expected_utc

    run_at(run_worker, student, picked - timedelta(minutes=1))
    assert fired(student, f"Seminar prep {day}") == []
    run_at(run_worker, student, picked)
    assert len(fired(student, f"Seminar prep {day}")) == 1


def test_a_utc_z_timestamp_is_accepted(client, academic_community):
    setup = academic_community()
    resp = setup.members[1].post("/api/reminders", json={
        "title": "Zulu", "remind_at": "2026-09-27T07:00:00Z"})
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["reminder"]["remind_at"] == "2026-09-27T07:00:00+00:00"


def test_a_time_without_an_offset_is_refused_not_guessed(client, academic_community):
    """"2026-09-27T08:00" does not say which 08:00. Reading it as UTC is how
    the hour went missing, so it is refused with a message saying why."""
    setup = academic_community()
    student = setup.members[1]
    resp = student.post("/api/reminders", json={
        "title": "Ambiguous", "remind_at": "2026-09-27T08:00:00"})
    assert resp.status_code == 400
    assert "timezone offset" in resp.get_json()["message"]


def test_editing_a_reminder_keeps_the_offset_too(client, academic_community):
    setup = academic_community()
    student = setup.members[1]
    reminder = create(student, "Move me", local(LAGOS, 2026, 9, 27, 8, 0))

    resp = student.put(f"/api/reminders/{reminder['id']}", json={
        "remind_at": local(LAGOS, 2026, 9, 28, 18, 30).isoformat()})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["reminder"]["remind_at"] == "2026-09-28T17:30:00+00:00"

    resp = student.put(f"/api/reminders/{reminder['id']}", json={
        "remind_at": "2026-09-28T18:30"})
    assert resp.status_code == 400
    assert "timezone offset" in resp.get_json()["message"]
