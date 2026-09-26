"""Student-facing wording shared by chat answers and in-app notifications.

The database is precise in its own terms - ISO dates, ASSIGNMENT, a
course_id. A student reads "Wednesday 23 September", "assignment" and
"COS202". Everything that turns the first kind of value into the second lives
here, so the chat and the notification bell say the same thing the same way.

Nothing in this module invents information: every function only rewords a
value it was given, and returns None (or a neutral fallback) when the value is
missing.
"""
from datetime import datetime

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday")

# The event_type column, as the noun a student would use in a sentence.
TYPE_NOUN = {
    "ASSIGNMENT": "assignment", "PROJECT": "project", "QUIZ": "quiz",
    "TEST": "test", "EXAM": "exam", "PRESENTATION": "presentation",
    "CLASS": "class", "OTHER": "academic event",
}

# Work that is handed in has a deadline; everything else happens on a date.
DUE_TYPES = frozenset({"ASSIGNMENT", "PROJECT"})


def _date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def spoken_date(value):
    """"18 September" - a date a person would say, from an ISO date."""
    parsed = _date(value)
    if parsed is None:
        return None
    return f"{parsed.day} {MONTHS[parsed.month - 1]}"


def spoken_day(value):
    """"Wednesday 23 September". The weekday is what a student plans around."""
    parsed = _date(value)
    if parsed is None:
        return None
    return f"{WEEKDAYS[parsed.weekday()]} {parsed.day} {MONTHS[parsed.month - 1]}"


def type_noun(event_type):
    """"assignment" for ASSIGNMENT; a neutral noun for anything unmapped."""
    return TYPE_NOUN.get((event_type or "").upper(), "academic event")


def is_due_type(event_type):
    return (event_type or "").upper() in DUE_TYPES


def named_event(title, course_code=None, fallback="An academic event"):
    """"Programming II Quiz (COS202)", or the fallback when nothing is recorded."""
    if title and course_code:
        return f"{title} ({course_code})"
    return title or fallback


def when_phrase(event_date, event_time=None):
    """"Saturday 26 September at 23:59", or None when there is no date."""
    day = spoken_day(event_date)
    if day is None:
        return None
    return f"{day} at {event_time}" if event_time else day


def capitalise(sentence):
    return sentence[:1].upper() + sentence[1:] if sentence else sentence
