"""In-app notification copy, kept apart from the email copy.

One notifications row is both an email outbox entry and an in-app notification
(see schema.sql). The two are read in different places, so they are worded
differently:

  * the EMAIL (subject, body) must be understandable without opening the app,
    so it carries every detail (spec 19);
  * the BELL shows a small kind label, a subject and a two-line body, so it
    names the thing, says what happened in one sentence, and links to it.

Each function here returns the in-app half as a dict of the keyword arguments
notification_service.enqueue() accepts: kind, link, app_subject, app_body.

The kind label is the category the bell prints ("Reminder", "Cancelled"), so
neither the subject nor the body repeats it.
"""
from .. import wording

# The bell's categories. The frontend maps each to its label; an unknown kind
# simply shows no label rather than printing its own token.
EVENT_CREATED = "EVENT_CREATED"
EVENT_CHANGED = "EVENT_CHANGED"
EVENT_CANCELLED = "EVENT_CANCELLED"
EVENT_REMINDER = "EVENT_REMINDER"
PERSONAL_REMINDER = "PERSONAL_REMINDER"
ANNOUNCEMENT = "ANNOUNCEMENT"
TIMETABLE = "TIMETABLE"
COURSE_REPS = "COURSE_REPS"

# Where each kind of thing lives in the app.
COMMUNITY_LINK = "/community"
ELECTIONS_LINK = "/community/elections"
REMINDERS_LINK = "/reminders"

BODY_LIMIT = 160


def _event_link(event):
    return f"/events/{event['id']}"


def _short(text, limit=BODY_LIMIT):
    """One line of prose for the bell. Whitespace (including the newlines an
    email body is written with) collapses to single spaces."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"


def event_created(event, course_code=None):
    noun = wording.type_noun(event["event_type"])
    when = wording.when_phrase(event["event_date"], event["event_time"])
    body = f"A new {noun} was added"
    if course_code:
        body += f" for {course_code}"
    if when:
        body += f", due {when}" if wording.is_due_type(event["event_type"]) else f", on {when}"
    return {
        "kind": EVENT_CREATED,
        "link": _event_link(event),
        "app_subject": wording.named_event(event["title"], course_code),
        "app_body": body + ".",
    }


def _moved(label, old, new, speak=lambda v: v):
    old_s, new_s = (speak(old) if old else None), (speak(new) if new else None)
    if old_s and new_s:
        return f"The {label} moved from {old_s} to {new_s}."
    if new_s:
        return f"The {label} is now {new_s}."
    return f"The {label} was removed."


def event_changed(event, change_type, old_values, new_values, course_code=None):
    noun = wording.type_noun(event["event_type"])
    if change_type == "DEADLINE_CHANGED":
        label = "deadline" if wording.is_due_type(event["event_type"]) else "date"
        body = _moved(label, old_values.get("event_date"), new_values.get("event_date"),
                      wording.spoken_day)
    elif change_type == "VENUE_CHANGED":
        old, new = old_values.get("venue"), new_values.get("venue")
        body = (f"The venue changed from {old} to {new}." if old and new
                else f"The venue is now {new}." if new else "The venue was removed.")
    elif change_type == "TIME_CHANGED":
        body = _moved("time", old_values.get("event_time"), new_values.get("event_time"))
    else:
        body = f"The details of this {noun} were updated."
    return {
        "kind": EVENT_CHANGED,
        "link": _event_link(event),
        "app_subject": wording.named_event(event["title"], course_code),
        "app_body": body,
    }


def event_cancelled(event, course_code=None):
    noun = wording.type_noun(event["event_type"])
    day = wording.spoken_day(event["event_date"])
    body = (f"This {noun}, planned for {day}, has been cancelled." if day
            else f"This {noun} has been cancelled.")
    return {
        "kind": EVENT_CANCELLED,
        "link": _event_link(event),
        "app_subject": wording.named_event(event["title"], course_code),
        "app_body": body,
    }


def event_reminder(row, course_code=None):
    """`row` carries the event's own columns (title, event_type, event_date,
    event_time, venue) and its event_id."""
    when = wording.when_phrase(row["event_date"], row["event_time"])
    if wording.is_due_type(row["event_type"]):
        body = f"Due {when}." if when else "The due date has not been confirmed."
    else:
        noun = wording.capitalise(wording.type_noun(row["event_type"]))
        body = f"{noun} on {when}" if when else f"{noun}, date to be confirmed"
        if row["venue"]:
            body += f" in {row['venue']}"
        body += "."
    return {
        "kind": EVENT_REMINDER,
        "link": f"/events/{row['event_id']}",
        "app_subject": wording.named_event(row["title"], course_code),
        "app_body": body,
    }


def personal_reminder(row):
    # The kind label already says "Reminder", and the title is the whole
    # message the student wrote for themselves - so there is no body to add.
    return {
        "kind": PERSONAL_REMINDER,
        "link": REMINDERS_LINK,
        "app_subject": row["title"],
        "app_body": None,
    }


def announcement(title, body_text):
    return {
        "kind": ANNOUNCEMENT,
        "link": COMMUNITY_LINK,
        "app_subject": title,
        "app_body": _short(body_text),
    }


def _class_words(entry):
    """"Data Structures on Mondays at 08:00 in LT2"."""
    words = entry["title"] or "A class"
    day = (entry["day_of_week"] or "").title()
    if day:
        words += f" on {day}s"
    if entry["start_time"]:
        words += f" at {entry['start_time']}"
    if entry["venue"]:
        words += f" in {entry['venue']}"
    return words


def timetable_added(entry):
    return {"kind": TIMETABLE, "link": COMMUNITY_LINK,
            "app_subject": "Class added to your timetable",
            "app_body": f"{_class_words(entry)}."}


def timetable_changed(entry):
    return {"kind": TIMETABLE, "link": COMMUNITY_LINK,
            "app_subject": "Timetable changed",
            "app_body": f"{_class_words(entry)} has changed."}


def timetable_removed(entry):
    return {"kind": TIMETABLE, "link": COMMUNITY_LINK,
            "app_subject": "Class removed from your timetable",
            "app_body": f"{_class_words(entry)} is no longer on the timetable."}


def course_reps(subject, email_body):
    """Election and removal outcomes. The email's first paragraph is already a
    plain sentence; the vote counts that follow it belong to the email."""
    first = str(email_body or "").split("\n\n")[0]
    return {"kind": COURSE_REPS, "link": ELECTIONS_LINK,
            "app_subject": subject, "app_body": _short(first)}
