"""Single source of current time.

Every service reads the clock through here rather than calling datetime.now()
directly, so ballot windows, cooldowns and reminder scheduling are testable
without sleeping.
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
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value):
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
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
