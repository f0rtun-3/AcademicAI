"""Deterministic grounded answering for AI Chat (spec 22).

Answers are assembled only from the records the backend supplied. When the
supplied data does not contain the answer, this says so rather than guessing -
the same contract the LLM provider is held to, but verifiable in tests.
"""
import re
from datetime import datetime, timedelta

from .. import wording
from . import nlp

WEEKDAY_ORDER = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]

MODIFY_PHRASES = ("change the", "update the", "move the", "postpone", "cancel the",
                  "add an assignment", "add a quiz", "create an assignment",
                  "delete the", "reschedule the", "extend the deadline", "set the deadline")


def _date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


MONTHS = wording.MONTHS
WEEKDAYS = wording.WEEKDAYS
_MONTH_RE = re.compile(r"\b\d{1,2} (?:" + "|".join(MONTHS) + r")\b")

# Spoken dates are shared with the notification bell (academicai/wording.py),
# so both say "Wednesday 23 September" and neither prints the stored ISO value.
_spoken_date = wording.spoken_date
_spoken_day = wording.spoken_day


def _fmt_event(event, include_course=True):
    """One event, in the words a student would use.

    The date is spoken - "Wednesday 23 September" - rather than printed as the
    ISO value the column stores. A stored date is precise for the system; it is
    not how anyone says a deadline out loud, and the same rule that keeps the
    audit log out of the chat keeps the date format out of it too.
    """
    parts = [event.get("title") or event.get("event_type", "Item").title()]
    if include_course and event.get("course_code"):
        parts.append(f"({event['course_code']})")
    parts.append(f"- {_spoken_day(event.get('event_date')) or 'no date given'}")
    if event.get("event_time"):
        parts.append(f"at {event['event_time']}")
    if event.get("venue"):
        parts.append(f"in {event['venue']}")
    return " ".join(parts)


def _fmt_class(entry):
    parts = [entry.get("title") or entry.get("course_code") or "Class"]
    parts.append(entry["day_of_week"].title())
    if entry.get("start_time"):
        parts.append(entry["start_time"])
    if entry.get("venue"):
        parts.append(f"in {entry['venue']}")
    return " ".join(parts)


def _upcoming(events, today, until=None):
    result = []
    for event in events:
        if event.get("status") == "CANCELLED":
            continue
        day = _date(event.get("event_date"))
        if day is None or day < today:
            continue
        if until is not None and day > until:
            continue
        result.append(event)
    result.sort(key=lambda e: (e.get("event_date"), e.get("event_time") or ""))
    return result


def _match_course(question, courses):
    codes = nlp.extract_course_codes(question)
    by_code = {c["code"].upper(): c for c in courses}
    for code in codes:
        if code in by_code:
            return by_code[code]
    for number in nlp.extract_bare_numbers(question):
        matches = [c for c in courses if c["code"].upper().endswith(number)]
        if len(matches) == 1:
            return matches[0]
    normalized = nlp.normalize(question)
    for course in courses:
        title = (course.get("title") or "").lower()
        if title and title in normalized:
            return course
    return None


def _answer(text, grounded=True, event_ids=None, reminder=None):
    return {
        "answer": text,
        "grounded": grounded,
        "referenced_event_ids": event_ids or [],
        "suggested_reminder": reminder,
    }


def answer_question(request):
    question = request.get("question") or ""
    today = _date(request.get("today"))
    events = request.get("events") or []
    timetable = request.get("timetable") or []
    courses = request.get("courses") or []
    changes = request.get("changes") or []
    # The asking student's own membership row, so an approval can be told
    # apart from a classmate's. Absent for anyone the context did not
    # resolve, and the wording stays neutral rather than guessing.
    viewer_membership_id = (request.get("viewer") or {}).get("membership_id")
    announcements = request.get("announcements") or []
    normalized = nlp.normalize(question)

    if not normalized:
        return _answer("Ask me about your assignments, classes, deadlines or recent changes.",
                       grounded=True)

    # A student asking to change official information is told who can (spec 22).
    if any(phrase in normalized for phrase in MODIFY_PHRASES):
        return _answer(
            "I can't change official academic information. Only a verified course rep can "
            "publish or change it for your community. I can help you track it or set a "
            "personal reminder instead.", grounded=True)

    if _asks_about_changes(normalized):
        return _recent_changes(changes, events, viewer_membership_id)

    course = _match_course(question, courses)

    if _asks_where(normalized):
        return _next_class(timetable, today, course, venue_only=True)

    if nlp.fuzzy_contains(normalized, "tomorrow"):
        return _classes_on(timetable, events, today + timedelta(days=1), "tomorrow")

    if _asks_next_deadline(normalized):
        return _next_deadline(events, today)

    if _asks_about_class_schedule(normalized):
        return _next_class(timetable, today, course)

    if course is not None:
        return _course_summary(course, events, timetable, today)

    window = _window(normalized, today)
    if window is not None:
        return _in_window(events, today, window, normalized)

    if _asks_focus(normalized):
        return _focus(events, today)

    if "announcement" in normalized:
        if not announcements:
            return _answer("There are no announcements for your community yet.")
        lines = [f"- {a['title']}: {a['body']}" for a in announcements[:5]]
        return _answer("Here are the latest announcements:\n" + "\n".join(lines))

    # Nothing matched: say so rather than invent an answer (spec 22).
    return _answer(
        "I don't have that in your community's academic records. You can ask about your "
        "assignments, quizzes, tests, exams, classes, deadlines, venues or recent changes.",
        grounded=False)


def _asks_about_changes(text):
    return ("changed" in text or "change" in text or "updated" in text
            or "what's new" in text or "whats new" in text)


def _asks_where(text):
    return text.startswith("where") or "where is" in text or "what venue" in text


def _asks_next_deadline(text):
    return ("next deadline" in text or "next due" in text
            or ("deadline" in text and "next" in text))


def _asks_about_class_schedule(text):
    return "next class" in text or ("class" in text and ("when" in text or "next" in text))


def _asks_focus(text):
    return "focus" in text or "priorit" in text or "what should i" in text


def _window(text, today):
    if "this week" in text or "the week" in text:
        return today + timedelta(days=(6 - today.weekday()))
    if "next week" in text:
        return today + timedelta(days=(13 - today.weekday()))
    if "today" in text:
        return today
    weekday = nlp.find_weekday(text)
    if weekday and ("before" in text or "by" in text or "until" in text):
        return nlp.next_weekday(today, weekday[0])
    return None


def _in_window(events, today, until, text):
    matching = _upcoming(events, today, until)
    if "assignment" in text:
        matching = [e for e in matching if e["event_type"] == "ASSIGNMENT"]
    if not matching:
        return _answer("You have nothing scheduled between "
                       f"{_spoken_day(today)} and {_spoken_day(until)}.")
    lines = [f"- {_fmt_event(e)}" for e in matching]
    return _answer(f"Between {_spoken_day(today)} and {_spoken_day(until)} you have:\n"
                   + "\n".join(lines),
                   event_ids=[e["id"] for e in matching])


def _next_deadline(events, today):
    upcoming = _upcoming(events, today)
    if not upcoming:
        return _answer("You have no upcoming deadlines in your academic records.")
    nxt = upcoming[0]
    reminder = {"title": f"Prepare for {nxt['title']}",
                "remind_at": f"{nxt['event_date']}T08:00:00+00:00"}
    return _answer(f"Your next deadline is {_fmt_event(nxt)}.",
                   event_ids=[nxt["id"]], reminder=reminder)


def _classes_on(timetable, events, day, label):
    weekday = WEEKDAY_ORDER[day.weekday()]
    classes = [t for t in timetable if t["day_of_week"] == weekday]
    due = [e for e in events if e.get("event_date") == day.isoformat()
           and e.get("status") != "CANCELLED"]
    if not classes and not due:
        # No date in brackets: "tomorrow" already says when, and the stored
        # ISO value is not how anyone says a day out loud.
        return _answer(f"You don't have anything scheduled {label}.")
    lines = []
    if classes:
        lines.append(f"Classes {label} ({weekday.title()}):")
        lines += [f"- {_fmt_class(c)}" for c in classes]
    if due:
        lines.append(f"Also due {label}:")
        lines += [f"- {_fmt_event(e)}" for e in due]
    return _answer("\n".join(lines), event_ids=[e["id"] for e in due])


def _next_class(timetable, today, course, venue_only=False):
    entries = [t for t in timetable
               if course is None or t.get("course_id") == course["id"]]
    if not entries:
        who = f" for {course['code']}" if course else ""
        return _answer(f"There is no timetable{who} in your academic records yet.")
    upcoming = sorted(
        ((nlp.next_weekday(today, t["day_of_week"]), t) for t in entries),
        key=lambda pair: (pair[0], pair[1].get("start_time") or ""))
    when, entry = upcoming[0]
    if venue_only:
        if not entry.get("venue"):
            return _answer(
                f"Your next class is {_fmt_class(entry)} on {_spoken_day(when)}, "
                "but no venue is recorded.")
        return _answer(f"Your next class is {entry.get('title') or 'a class'} on "
                       f"{_spoken_day(when)} in {entry['venue']}.")
    return _answer(f"Your next class is {_fmt_class(entry)} on {_spoken_day(when)}.")


def _course_summary(course, events, timetable, today):
    course_events = _upcoming([e for e in events if e.get("course_id") == course["id"]], today)
    classes = [t for t in timetable if t.get("course_id") == course["id"]]
    lines = [f"{course['code']}" + (f" - {course['title']}" if course.get("title") else "")]
    if classes:
        lines.append("Classes:")
        lines += [f"- {_fmt_class(c)}" for c in classes]
    if course_events:
        lines.append("Upcoming:")
        lines += [f"- {_fmt_event(e, include_course=False)}" for e in course_events]
    if not classes and not course_events:
        lines.append("There is nothing scheduled for this course in your records.")
    return _answer("\n".join(lines), event_ids=[e["id"] for e in course_events])


# ── Turning an audit record into a sentence ────────────────────────────────
#
# DATABASE LANGUAGE IS NOT USER LANGUAGE. change_history stores exactly what
# happened, in the terms the system needs - MEMBERSHIP_APPROVED, a
# PENDING_APPROVAL -> ACTIVE transition, an entity_id. None of that is an
# answer to "what changed recently?", and a student should never have to learn
# a state machine to read their own timetable.
#
# This is the ONLY place that translates. The audit log, the change types, the
# stored values and every other reader of them are untouched; what changes is
# the sentence the assistant says out loud.
#
# The rule for detail: say what the record actually holds, and nothing else. A
# change row for a cancelled event carries only the status transition, so that
# sentence stays general; a row for a venue change carries both venues, so it
# names them. Nothing is inferred to make a sentence read better.

def _event_words(change, events_by_id):
    """What we can honestly call the event this change is about.

    Two sources, both already in hand: the community's current events, and the
    snapshot the change itself stored. A cancelled event is missing from the
    first (the context excludes cancelled events) and absent from the second
    (a cancellation stores only the status), so this legitimately returns
    nothing and the caller stays general.
    """
    if change.get("entity_type") != "academic_event":
        return None, None
    event = events_by_id.get(change.get("entity_id")) or {}
    snapshot = change.get("new_value") if isinstance(change.get("new_value"), dict) else {}
    # The subject the change query joined in (community_service.recent_changes)
    # names the event even when it is cancelled and so absent from `events`.
    subject = change.get("subject") if isinstance(change.get("subject"), dict) else {}
    title = event.get("title") or subject.get("title") or snapshot.get("title")
    course = event.get("course_code") or subject.get("course_code")
    return title, course


def _named(title, course, fallback):
    """"Programming II quiz", or a plain fallback when nothing is recorded."""
    if title and course:
        return f"{title} ({course})"
    return title or fallback


def _moved(change, field):
    old = (change.get("old_value") or {}).get(field) if isinstance(
        change.get("old_value"), dict) else None
    new = (change.get("new_value") or {}).get(field) if isinstance(
        change.get("new_value"), dict) else None
    return old, new


def _describe_change(change, events_by_id, viewer_membership_id):
    """One student-readable sentence for one audit record."""
    kind = change.get("change_type") or ""
    title, course = _event_words(change, events_by_id)
    thing = _named(title, course, "an academic event")
    mine = (change.get("entity_type") == "community_member"
            and viewer_membership_id is not None
            and change.get("entity_id") == viewer_membership_id)

    if kind == "MEMBERSHIP_APPROVED":
        return ("Your membership of this community was approved." if mine
                else "A student's membership of this community was approved.")
    if kind == "MEMBERSHIP_REJECTED":
        return ("Your request to join this community was declined." if mine
                else "A request to join this community was declined.")
    if kind == "JOINED":
        return "You joined this community." if mine else "A student joined this community."

    if kind == "EVENT_CREATED":
        snapshot = change.get("new_value") if isinstance(change.get("new_value"), dict) else {}
        etype = (snapshot.get("event_type") or "").lower().replace("_", " ")
        noun = f"{etype}" if etype and etype != "other" else "academic event"
        when = _spoken_date(snapshot.get("event_date"))
        named = f": {title}" if title else ""
        if course:
            named += f" ({course})"
        return (f"A new {noun} was added{named}"
                + (f", for {when}." if when else "."))
    if kind == "EVENT_CANCELLED":
        return f"{thing[0].upper()}{thing[1:]} was cancelled."
    if kind == "DEADLINE_CHANGED":
        old, new = _moved(change, "event_date")
        old_s, new_s = _spoken_date(old), _spoken_date(new)
        if old_s and new_s:
            return f"The deadline for {thing} moved from {old_s} to {new_s}."
        return f"The deadline for {thing} changed."
    if kind == "VENUE_CHANGED":
        old, new = _moved(change, "venue")
        if old and new:
            return f"The venue for {thing} changed from {old} to {new}."
        if new:
            return f"The venue for {thing} is now {new}."
        return f"The venue for {thing} changed."
    if kind == "TIME_CHANGED":
        old, new = _moved(change, "event_time")
        if old and new:
            return f"The time for {thing} moved from {old} to {new}."
        return f"The time for {thing} changed."
    if kind == "EVENT_UPDATED":
        return f"{thing[0].upper()}{thing[1:]} was updated."

    if kind == "ANNOUNCEMENT_PUBLISHED":
        return "A new announcement was posted."
    if kind == "ANNOUNCEMENT_UPDATED":
        return "An announcement was edited."
    if kind == "ANNOUNCEMENT_WITHDRAWN":
        return "An announcement was withdrawn."

    if kind == "MATERIAL_ATTACHED":
        name = change.get("new_value") if isinstance(change.get("new_value"), str) else None
        where = f" to {thing}" if title else ""
        return (f"Supporting material was added{where}: {name}." if name
                else f"Supporting material was added{where}.")
    if kind == "MATERIAL_REMOVED":
        where = f" from {thing}" if title else ""
        return f"Supporting material was removed{where}."

    if kind in ("COURSE_CREATED", "COURSE_UPDATED", "COURSE_REMOVED"):
        code = None
        for side in ("new_value", "old_value"):
            value = change.get(side)
            if isinstance(value, dict) and value.get("code"):
                code = value["code"]
                break
        what = code or "A course"
        verb = {"COURSE_CREATED": "was added to your course list",
                "COURSE_UPDATED": "was updated",
                "COURSE_REMOVED": "was removed from your course list"}[kind]
        return f"{what} {verb}."
    if kind == "TIMETABLE_CREATED":
        return "A class was added to your weekly timetable."
    if kind == "TIMETABLE_CANCELLED":
        return "A class was removed from your weekly timetable."

    if kind == "CALENDAR_UPLOADED":
        return "The academic calendar was updated."
    if kind == "SESSION_ARCHIVED":
        return "This academic session was archived."
    if kind == "NOMINATION_OPENED":
        return "A course rep election was opened."
    if kind == "REMOVAL_OPENED":
        return "A vote to remove a course rep was opened."

    # An unmapped type. Rather than print the token, say the honest minimum -
    # something changed, and when. A new change type must never be able to leak
    # its own name into a student's chat.
    return "An update was made to your community's records."


# Several identical records read as noise. The count is kept, in words, so
# nothing is hidden and nothing is deleted - the audit log is untouched.
GROUPED = {
    "MEMBERSHIP_APPROVED": "{n} community memberships were approved.",
    "EVENT_CREATED": "{n} new academic events were added.",
    "EVENT_CANCELLED": "{n} academic events were cancelled.",
    "ANNOUNCEMENT_PUBLISHED": "{n} new announcements were posted.",
    "MATERIAL_ATTACHED": "{n} pieces of supporting material were added.",
    "JOINED": "{n} students joined this community.",
    "TIMETABLE_CREATED": "{n} classes were added to your weekly timetable.",
    "TIMETABLE_CANCELLED": "{n} classes were removed from your weekly timetable.",
    "COURSE_CREATED": "{n} courses were added to your course list.",
}


def _relevant_to_student(change, viewer_membership_id):
    """Whether a change belongs in a student's "what changed?" answer.

    Academic records, announcements and elections concern the whole
    community. Membership rows do not: a classmate being approved, joining or
    leaving is someone else's administrative business, so it is left out
    unless the membership is the asking student's own.
    """
    if change.get("entity_type") == "community_member":
        return (viewer_membership_id is not None
                and change.get("entity_id") == viewer_membership_id)
    return True


def describe_recent_changes(changes, events, viewer_membership_id=None, limit=8):
    """The recent changes a student may be told about, one plain sentence each.

    Returns [{"summary": sentence, "date": "18 September" | None}], newest
    first. This is the ONLY form in which the change log leaves the backend
    for a chat answer: the heuristic answer below reads it, and so does the
    LLM prompt (prompts.build_chat_prompt), so neither ever sees a raw
    change_type, field name or state transition.
    """
    events_by_id = {e["id"]: e for e in events if e.get("id") is not None}
    described = []
    for change in changes:
        if not _relevant_to_student(change, viewer_membership_id):
            continue
        sentence = _describe_change(change, events_by_id, viewer_membership_id)
        when = _spoken_date(change.get("created_at"))
        # A sentence that already names a date does not need the date the
        # record was written as well: "for 17 September. (15 September)" reads
        # as a stutter and buries the part that matters.
        if when and _MONTH_RE.search(sentence):
            when = None
        described.append({"summary": sentence, "date": when,
                          "kind": change.get("change_type")})
        if len(described) >= limit:
            break
    return described


def _recent_changes(changes, events, viewer_membership_id=None):
    relevant = describe_recent_changes(changes, events, viewer_membership_id)
    if not relevant:
        return _answer("Nothing has changed in your community's academic records recently.")

    described = [(d["summary"], d["kind"], d["date"]) for d in relevant]

    lines = []
    index = 0
    while index < len(described):
        sentence, kind, when = described[index]
        run = index
        while run + 1 < len(described) and described[run + 1][0] == sentence:
            run += 1
        count = run - index + 1
        if count > 1 and kind in GROUPED:
            lines.append(f"- {GROUPED[kind].format(n=count)}")
        elif count > 1:
            lines.append(f"- {sentence} This happened {count} times.")
        else:
            lines.append(f"- {sentence}" + (f" ({when})" if when else ""))
        index = run + 1

    return _answer("Here is what changed recently in your community:\n" + "\n".join(lines))


def _focus(events, today):
    upcoming = _upcoming(events, today, today + timedelta(days=7))
    if not upcoming:
        return _answer("You have nothing due in the next seven days.")
    high = [e for e in upcoming if e.get("priority") == "HIGH"]
    lines = [f"- {_fmt_event(e)}" for e in (high or upcoming)]
    return _answer("In the next seven days, focus on:\n" + "\n".join(lines),
                   event_ids=[e["id"] for e in upcoming])
