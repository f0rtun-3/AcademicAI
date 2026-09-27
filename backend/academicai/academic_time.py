"""Academic time: the university's own clock (spec 20).

AcademicAI handles two kinds of time value, and they must never be confused.

  INSTANT - an absolute moment. Stored and exchanged as ISO-8601 WITH an offset,
            normalised to UTC: "2026-09-27T07:00:00+00:00". Reminder firing
            times, created_at, ballot deadlines. clock.py owns instants and
            refuses one that does not state its offset.

  ACADEMIC WALL-CLOCK - a date and time as people at the university read them:
            an event's event_date + event_time, a timetable start_time, a
            reminder's remind_at_local ("2026-09-27T08:00"). It deliberately
            carries NO offset: it means "on this university's clock".

Every university has a required IANA timezone (universities.timezone). This
module is the one place a wall-clock value becomes an instant, or an instant
becomes a wall-clock value, and it always asks the university which zone:

    academic wall-clock -> university IANA zone -> UTC instant -> database/worker
    UTC instant -> university IANA zone -> what the student reads

The worker never comes here. It compares stored UTC instants and nothing else.

DAYLIGHT SAVING is Python's zoneinfo, never a hand-written offset. A local time
is attached with zoneinfo's default fold=0, which gives two documented results
(pinned by tests/test_academic_timezone.py, Europe/London):

  * a time the clocks skip (01:30 on the spring-forward night) moves FORWARD by
    the length of the gap: it fires at the instant the zone calls 02:30.
  * a time the clocks repeat (01:30 on the fall-back night) means its FIRST
    occurrence, still on summer time.
"""
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import clock
from .errors import ValidationError

# The only accepted spelling of a wall-clock value in the API: minute precision,
# 24-hour, no offset, no "Z", no seconds. Anything else is refused rather than
# guessed at.
LOCAL_FORMAT = "%Y-%m-%dT%H:%M"
_LOCAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


class InvalidTimezone(ValueError):
    """A university timezone that is missing or not a geographic IANA zone."""


def zone(name):
    """The ZoneInfo for a university timezone name, or InvalidTimezone.

    A university's clock is a PLACE ("Africa/Lagos"), never a fixed offset.
    "UTC", "GMT", "Etc/GMT-1" and friends are valid IANA keys but they are not
    where a university is, and accepting them would let a lazy default stand
    in for a real answer, so they are refused.
    """
    if not isinstance(name, str) or not name.strip():
        raise InvalidTimezone("no timezone is set")
    name = name.strip()
    if "/" not in name or name.startswith("Etc/"):
        raise InvalidTimezone(
            f"{name!r} is not a geographic IANA timezone (expected e.g. 'Africa/Lagos')")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidTimezone(f"{name!r} is not a known IANA timezone") from exc


# ── Which zone ──────────────────────────────────────────────────────────────

def zone_name_for_community(community_id, conn=None):
    from .db.connection import query_one
    row = query_one(
        """SELECT u.timezone FROM academic_communities c
           JOIN universities u ON u.id = c.university_id WHERE c.id = ?""",
        (community_id,), conn=conn)
    if row is None:
        raise LookupError(f"community {community_id} has no university")
    zone(row["timezone"])  # startup guarantees this; fail loudly if not
    return row["timezone"]


def zone_for_community(community_id, conn=None):
    return zone(zone_name_for_community(community_id, conn=conn))


def zone_name_for_user(user_id, conn=None):
    """The academic clock a student reads: their active community's university,
    or, before they have one, the university they registered with. None only
    for an account with no university at all."""
    from .db.connection import query_one
    row = query_one(
        """SELECT u.timezone FROM community_members m
           JOIN academic_communities c ON c.id = m.community_id
           JOIN universities u ON u.id = c.university_id
           WHERE m.user_id = ? AND m.status = 'ACTIVE'""",
        (user_id,), conn=conn)
    if row is None:
        row = query_one(
            """SELECT u.timezone FROM users s JOIN universities u ON u.id = s.university_id
               WHERE s.id = ?""", (user_id,), conn=conn)
    if row is None:
        return None
    zone(row["timezone"])
    return row["timezone"]


# ── Now, today ──────────────────────────────────────────────────────────────

def now_local(tz):
    """The current academic wall-clock time, to the minute."""
    return clock.now().astimezone(tz).replace(second=0, microsecond=0, tzinfo=None)


def today(tz):
    """Today's date on the university's clock - not the UTC date, which is a
    different day for part of every night anywhere east or west of UTC."""
    return clock.now().astimezone(tz).date()


# ── Wall-clock <-> instant ──────────────────────────────────────────────────

def parse_local(value, field="remind_at_local"):
    """A wall-clock value from the API. Strictly YYYY-MM-DDTHH:MM."""
    if not isinstance(value, str) or not _LOCAL_RE.match(value.strip()):
        raise ValidationError(
            f"{field} must be a date and time on your university's clock, written "
            "like 2026-09-27T08:00 (24-hour, no timezone offset).")
    try:
        return datetime.strptime(value.strip(), LOCAL_FORMAT)
    except ValueError:
        raise ValidationError(f"{field} is not a real date and time.")


def format_local(local):
    return local.strftime(LOCAL_FORMAT)


def local_to_instant(local, tz):
    """A naive academic wall-clock datetime -> an aware UTC instant.

    fold=0 (zoneinfo's default): a skipped time moves forward by the gap, a
    repeated time means its first occurrence. See the module docstring."""
    if local.tzinfo is not None:
        raise ValueError("local_to_instant expects a wall-clock (naive) datetime")
    return local.replace(tzinfo=tz, fold=0).astimezone(timezone.utc)


def instant_to_local(instant, tz):
    """An instant (aware datetime or ISO string with offset) -> naive wall-clock."""
    if isinstance(instant, str):
        instant = clock.parse_iso(instant)
    return instant.astimezone(tz).replace(second=0, microsecond=0, tzinfo=None)


def local_string(instant, tz):
    return format_local(instant_to_local(instant, tz))


def event_end_instant(event_date, event_time, tz):
    """The latest moment a reminder about an event still makes sense, INCLUSIVE:
    its time, or - for an event with a date but no time - the last minute of
    that academic day (23:59; reminder times are minute-precision, so that is
    "any time that day" and never 00:00 the day after)."""
    if not event_date:
        return None
    day = datetime.strptime(event_date, "%Y-%m-%d")
    if event_time:
        hours, minutes = (int(p) for p in event_time.split(":")[:2])
        return local_to_instant(day.replace(hour=hours, minute=minutes), tz)
    return local_to_instant(day.replace(hour=23, minute=59), tz)
