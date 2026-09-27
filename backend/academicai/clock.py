"""Single source of current time, and the owner of INSTANTS.

Every service reads the clock through here rather than calling datetime.now()
directly, so ballot windows, cooldowns and reminder scheduling are testable
without sleeping.

Everything here is an absolute instant, stored as ISO-8601 in UTC with its
offset ("2026-09-27T07:00:00+00:00"). A value without an offset does not say
which moment it means, so it is REFUSED rather than assumed to be UTC - that
assumption is exactly how a Lagos reminder once fired an hour late. Academic
wall-clock values (event_date + event_time, remind_at_local) are a different
kind of value and live in academic_time.py.
"""
from datetime import datetime, timedelta, timezone

_override = None


def now():
    if _override is not None:
        return _override()
    return datetime.now(timezone.utc)


def now_iso():
    return to_iso(now())


def to_iso(dt):
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"to_iso needs an aware datetime; {dt!r} has no timezone")
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value):
    """A stored or supplied instant. The offset is required: an offset-less
    string raises ValueError instead of silently becoming UTC."""
    if value is None:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{value!r} is not an instant: it has no timezone offset")
    return dt


def set_now(fn):
    """Install a clock override. fn() must return an aware datetime."""
    global _override
    _override = fn


def freeze(dt):
    set_now(lambda: dt)
    return dt


def advance(delta):
    """Move a frozen clock forward. Requires freeze() first."""
    current = now()
    freeze(current + delta)
    return now()


def reset():
    global _override
    _override = None


def minutes(n):
    return timedelta(minutes=n)


def hours(n):
    return timedelta(hours=n)


def days(n):
    return timedelta(days=n)
