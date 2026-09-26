"""Deterministic message interpretation (spec 15, 16).

This provider encodes the product's interpretation rules directly, which makes
them testable and stable: the same message always yields the same proposal.

The rules it must never break:
  * never invent information - an unparseable value becomes a clarification
  * never silently choose between conflicting interpretations
  * a message that clearly states a change but whose NEW value cannot be read
    is a CLARIFICATION, never a DUPLICATE
  * explicitly unspecified date/time/venue stay null and are not failures
"""
from datetime import datetime, timedelta

from . import nlp
from .provider import AIProvider
from .schemas import empty_proposal

# Order matters: the first type whose keywords appear wins, so PROJECT is
# checked before ASSIGNMENT. "project" and "assignment" often appear in the
# same sentence ("the project assignment is due"), and the more specific word
# is the one a rep means.
EVENT_TYPE_KEYWORDS = {
    "PROJECT": ("project", "capstone", "final year project", "fyp"),
    "ASSIGNMENT": ("assignment", "homework", "coursework", "submission"),
    "QUIZ": ("quiz",),
    "TEST": ("test", "cat"),
    "PRESENTATION": ("presentation", "present", "seminar"),
    "EXAM": ("exam", "examination"),
    "CLASS": ("class", "lecture", "lesson"),
}
CHANGE_WORDS = ("changed", "change", "extended", "extension", "moved", "postponed",
                "shifted", "rescheduled", "pushed", "swapped", "replaced", "instead")
CANCEL_WORDS = ("cancelled", "canceled", "cancel", "called off", "no longer holding",
                "will not hold", "wont hold")
VENUE_WORDS = ("venue", "hall", "room", "lab", "theatre", "theater", "location")
DATE_WORDS = ("deadline", "due", "date", "submission", "submit")

MATCH_THRESHOLD = 0.55
MATCH_MARGIN = 0.15


class HeuristicProvider(AIProvider):
    name = "heuristic"

    def interpret(self, request):
        message = request.get("message") or ""
        reference = _as_date(request.get("today"))
        courses = request.get("courses") or []
        events = request.get("events") or []
        timetable = request.get("timetable") or []
        explicit = request.get("explicit") or {}

        proposal = empty_proposal()
        proposal["scope"] = _detect_scope(message, request.get("information_type"))

        course = _resolve_course(message, courses, request.get("selected_course"))
        proposal["course_code"] = course["code"] if course else None

        event_type = _resolve_event_type(message, request.get("information_type"))
        proposal["event_type"] = event_type

        discrepancies = _discrepancies(message, courses, explicit, request.get("selected_course"))
        proposal["discrepancies"] = discrepancies

        if _mentions_any(message, CANCEL_WORDS):
            return _finish(_cancellation(proposal, message, course, event_type, events),
                           discrepancies)

        if proposal["scope"] == "TIMETABLE":
            return _finish(_timetable_change(proposal, message, course, timetable), discrepancies)

        if _is_change_message(message):
            return _finish(
                _change(proposal, message, reference, course, event_type, events, explicit),
                discrepancies)

        return _finish(
            _creation(proposal, message, reference, course, event_type, events, timetable,
                      explicit),
            discrepancies)

    # -- chat ------------------------------------------------------------
    def answer(self, request):
        """Grounded answer built only from the records the backend supplied.

        The heuristic answerer never speculates: if the supplied records do not
        contain the answer, it says so (spec 22).
        """
        from .chat_heuristic import answer_question
        return answer_question(request)


def _finish(proposal, discrepancies):
    if proposal["action"] != "CLARIFICATION":
        proposal["needs_clarification"] = False
    if discrepancies:
        proposal["needs_clarification"] = True
        if proposal["action"] not in ("CLARIFICATION",):
            proposal["confidence"] = min(proposal["confidence"], 0.5)
        if not proposal["clarification_question"]:
            proposal["clarification_question"] = (
                "The message does not match the details you selected. Which is correct?")
    return proposal


def _as_date(value):
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    return value


def _mentions_any(text, words):
    return any(nlp.fuzzy_contains(text, word) for word in words)


def _detect_scope(message, information_type):
    if (information_type or "").upper() in ("TIMETABLE", "CLASS_SCHEDULE"):
        return "TIMETABLE"
    if (information_type or "").upper() == "ANNOUNCEMENT":
        return "ANNOUNCEMENT"
    normalized = nlp.normalize(message)
    # "every wednesday" describes a recurring class, i.e. the timetable.
    if "every" in normalized and nlp.all_weekdays(message):
        return "TIMETABLE"
    return "EVENT"


def _resolve_course(message, courses, selected_course):
    """Match a course by code, by bare number, or by title words."""
    if selected_course:
        for course in courses:
            if course["id"] == selected_course.get("id"):
                return course
    by_code = {c["code"].upper(): c for c in courses}
    for code in nlp.extract_course_codes(message):
        if code in by_code:
            return by_code[code]
    for number in nlp.extract_bare_numbers(message):
        matches = [c for c in courses if c["code"].upper().endswith(number)]
        if len(matches) == 1:
            return matches[0]
    # Title match, e.g. "philosophy", "adventist heritage".
    normalized = nlp.normalize(message)
    best, best_score = None, 0.0
    for course in courses:
        title = (course.get("title") or "").lower()
        if not title:
            continue
        if title in normalized:
            return course
        title_tokens = [t for t in nlp.tokens(title) if len(t) > 4]
        if title_tokens:
            hits = sum(1 for t in title_tokens if nlp.fuzzy_contains(message, t))
            score = hits / len(title_tokens)
            if score > best_score:
                best, best_score = course, score
    return best if best_score >= 0.5 else None


def _resolve_event_type(message, information_type):
    declared = (information_type or "").upper()
    if declared in EVENT_TYPE_KEYWORDS:
        return declared
    for event_type, keywords in EVENT_TYPE_KEYWORDS.items():
        if any(nlp.fuzzy_contains(message, kw) for kw in keywords):
            return event_type
    return None


def _mentioned_event_types(message, exclude_filler=True):
    """Event types named in a message.

    CLASS is excluded by default: "class" appears as a filler word in phrases
    like "next class" and would otherwise make a single-item message look like
    two separate items.
    """
    found = {etype for etype, kws in EVENT_TYPE_KEYWORDS.items()
             if any(nlp.fuzzy_contains(message, kw) for kw in kws)}
    if exclude_filler:
        found.discard("CLASS")
    return found


def _discrepancies(message, courses, explicit, selected_course):
    """Flag conflicts between what the rep typed into the form and the message
    itself. The system never silently picks one (spec 15)."""
    found = []
    if selected_course:
        codes = nlp.extract_course_codes(message)
        selected_code = (selected_course.get("code") or "").upper()
        if codes and selected_code and selected_code not in codes:
            found.append(
                f"You selected {selected_code} but the message mentions {', '.join(codes)}.")
    explicit_venue = (explicit.get("venue") or "").upper().replace(" ", "")
    if explicit_venue:
        venues = nlp.extract_venue_tokens(message)
        if venues and explicit_venue not in venues:
            found.append(
                f"You entered venue {explicit_venue} but the message mentions "
                f"{', '.join(venues)}.")
    return found


def _resolve_date_from_message(message, reference, course, timetable):
    """Return (date_iso, reason). reason is None on success."""
    if nlp.is_vague_timeframe(message):
        return None, "vague_timeframe"

    explicit_date = nlp.parse_explicit_date(message, reference)
    if explicit_date:
        return explicit_date.isoformat(), None

    normalized = nlp.normalize(message)
    if nlp.fuzzy_contains(message, "tomorrow"):
        return (reference + timedelta(days=1)).isoformat(), None
    if nlp.fuzzy_contains(message, "today"):
        return reference.isoformat(), None

    # "next class" needs the timetable, and the course must be known (spec 15).
    if nlp.fuzzy_contains(message, "next class") or nlp.fuzzy_contains(normalized, "nextclass"):
        if course is None:
            return None, "next_class_unknown_course"
        entries = [t for t in timetable if t.get("course_id") == course["id"]]
        if not entries:
            return None, "next_class_no_timetable"
        candidates = [nlp.next_weekday(reference + timedelta(days=1), t["day_of_week"])
                      for t in entries if t.get("day_of_week")]
        if not candidates:
            return None, "next_class_no_timetable"
        return min(candidates).isoformat(), None

    weekday = nlp.find_weekday(message)
    if weekday:
        name, _pos = weekday
        next_week = bool(
            nlp.fuzzy_contains(message, "next week") or nlp.fuzzy_contains(message, "nextweek"))
        return nlp.next_weekday(reference, name, next_week=next_week).isoformat(), None

    return None, "no_date_found"


def _is_change_message(message):
    if _mentions_any(message, CHANGE_WORDS):
        return True
    old, new = nlp.from_to_values(message)
    return bool(old and new)


def _looks_like_venue(value):
    if not value:
        return False
    return bool(nlp.extract_venue_tokens(value))


def _score_candidate(event, course, event_type, message, old_value):
    score, signals = 0.0, []
    if course and event.get("course_id") == course["id"]:
        score += 0.40
        signals.append("course")
    if event_type and event.get("event_type") == event_type:
        score += 0.20
        signals.append("event_type")
    title = (event.get("title") or "").lower()
    if title:
        title_tokens = [t for t in nlp.tokens(title) if len(t) > 3]
        if title_tokens:
            hits = sum(1 for t in title_tokens if nlp.fuzzy_contains(message, t))
            ratio = hits / len(title_tokens)
            score += 0.20 * ratio
            if ratio >= 0.5:
                signals.append("title")
    # The strongest signal: the message quotes the record's current value.
    if old_value:
        normalized_old = str(old_value).upper().replace(" ", "")
        if event.get("venue") and event["venue"].upper().replace(" ", "") == normalized_old:
            score += 0.35
            signals.append("old_venue")
        if event.get("event_date") and event["event_date"] == old_value:
            score += 0.35
            signals.append("old_date")
    return score, signals


def _match_events(events, course, event_type, message, old_value):
    """Return (best, second_best) scored candidates (spec 16)."""
    scored = []
    for event in events:
        if event.get("status") == "CANCELLED":
            continue
        score, signals = _score_candidate(event, course, event_type, message, old_value)
        if score > 0:
            scored.append((score, signals, event))
    scored.sort(key=lambda item: item[0], reverse=True)
    best = scored[0] if scored else None
    second = scored[1] if len(scored) > 1 else None
    return best, second


def _clarify(proposal, question, explanation, confidence=0.3):
    proposal["action"] = "CLARIFICATION"
    proposal["needs_clarification"] = True
    proposal["clarification_question"] = question
    proposal["explanation"] = explanation
    proposal["confidence"] = confidence
    return proposal


def _cancellation(proposal, message, course, event_type, events):
    best, second = _match_events(events, course, event_type, message, None)
    if best is None:
        return _clarify(proposal, "Which class or event is being cancelled?",
                        "A cancellation was detected but no matching record was found.")
    if second is not None and (best[0] - second[0]) < MATCH_MARGIN:
        return _clarify(proposal, "Which of the matching records is being cancelled?",
                        "More than one existing record could match this cancellation.")
    proposal["action"] = "CANCEL"
    proposal["possible_match_id"] = best[2]["id"]
    proposal["matching_confidence"] = round(min(best[0], 1.0), 2)
    proposal["confidence"] = round(min(best[0], 0.95), 2)
    proposal["title"] = best[2].get("title")
    proposal["old_value"] = {"status": "SCHEDULED"}
    proposal["new_value"] = {"status": "CANCELLED"}
    proposal["explanation"] = (
        f"The message cancels the existing record '{best[2].get('title')}' "
        f"(matched on {', '.join(best[1])}).")
    return proposal


def _timetable_change(proposal, message, course, timetable):
    """'philosophy every wednesdays instead of every thursdays' (spec 31 case 5)."""
    days = nlp.all_weekdays(message)
    proposal["scope"] = "TIMETABLE"
    if not days:
        return _clarify(proposal, "Which day should this class move to?",
                        "A timetable change was detected but no day could be read.")

    old_day = new_day = None
    instead = nlp.instead_of_value(message)
    if instead:
        instead_days = nlp.all_weekdays(instead)
        if instead_days:
            old_day = instead_days[0][0]
        new_day = next((d for d, _ in days if d != old_day), None)
    if new_day is None:
        old_from, new_from = nlp.from_to_values(message)
        if old_from and new_from:
            old_days, new_days = nlp.all_weekdays(old_from), nlp.all_weekdays(new_from)
            old_day = old_days[0][0] if old_days else old_day
            new_day = new_days[0][0] if new_days else None
    if new_day is None and len(days) == 1:
        new_day = days[0][0]

    if new_day is None:
        return _clarify(proposal, "Which day should this class move to?",
                        "The message states a timetable change but the new day is unclear.")

    candidates = [t for t in timetable
                  if course is None or t.get("course_id") == course["id"]]
    if old_day:
        exact = [t for t in candidates if t.get("day_of_week") == old_day]
        if exact:
            candidates = exact

    if not candidates:
        proposal["action"] = "CREATE"
        proposal["day_of_week"] = new_day
        proposal["confidence"] = 0.55
        proposal["new_value"] = {"day_of_week": new_day}
        proposal["explanation"] = (
            f"No existing timetable entry matched, so this proposes a new class on "
            f"{new_day.title()}.")
        return proposal
    if len(candidates) > 1:
        return _clarify(proposal, "Which timetable entry should change?",
                        "More than one timetable entry could match this message.")

    entry = candidates[0]
    if entry.get("day_of_week") == new_day:
        proposal["action"] = "DUPLICATE"
        proposal["possible_match_id"] = entry["id"]
        proposal["confidence"] = 0.8
        proposal["explanation"] = (
            f"The timetable already has this class on {new_day.title()}.")
        return proposal

    proposal["action"] = "UPDATE"
    proposal["possible_match_id"] = entry["id"]
    proposal["matching_confidence"] = 0.9
    proposal["confidence"] = 0.85
    proposal["day_of_week"] = new_day
    proposal["old_value"] = {"day_of_week": entry.get("day_of_week")}
    proposal["new_value"] = {"day_of_week": new_day}
    proposal["explanation"] = (
        f"The class moves from {str(entry.get('day_of_week')).title()} to {new_day.title()}.")
    return proposal


def _change(proposal, message, reference, course, event_type, events, explicit):
    """A message that states something changed (spec 16)."""
    old_raw, new_raw = nlp.from_to_values(message)
    venue_change = _mentions_any(message, VENUE_WORDS) or (
        _looks_like_venue(old_raw) and _looks_like_venue(new_raw))

    if venue_change:
        return _venue_change(proposal, message, course, event_type, events, old_raw, new_raw)
    return _date_change(proposal, message, reference, course, event_type, events, old_raw, new_raw)


def _venue_change(proposal, message, course, event_type, events, old_raw, new_raw):
    old_venue = _first_venue(old_raw) if old_raw else None
    new_venue = _first_venue(new_raw) if new_raw else None
    if new_venue is None:
        target = nlp.target_value(message)
        new_venue = _first_venue(target) if target else None
    if new_venue is None:
        venues = nlp.extract_venue_tokens(message)
        if old_venue and len(venues) == 2:
            new_venue = next((v for v in venues if v != old_venue), None)

    if new_venue is None:
        # Change stated, new value unreadable -> clarification, never duplicate.
        return _clarify(
            proposal, "What is the new venue?",
            "The message says the venue changed but the new venue could not be read.")

    best, second = _match_events(events, course, event_type, message, old_venue)
    if best is None or best[0] < MATCH_THRESHOLD:
        return _clarify(proposal, "Which class or event has moved venue?",
                        "A venue change was detected but no existing record matched.")
    if second is not None and (best[0] - second[0]) < MATCH_MARGIN:
        return _clarify(proposal, "Which of the matching records changed venue?",
                        "More than one existing record could match this venue change.")

    event = best[2]
    if (event.get("venue") or "").upper().replace(" ", "") == new_venue:
        proposal["action"] = "DUPLICATE"
        proposal["possible_match_id"] = event["id"]
        proposal["confidence"] = 0.8
        proposal["explanation"] = f"The venue is already recorded as {new_venue}."
        return proposal

    proposal["action"] = "UPDATE"
    proposal["possible_match_id"] = event["id"]
    proposal["matching_confidence"] = round(min(best[0], 1.0), 2)
    proposal["confidence"] = round(min(best[0] + 0.15, 0.95), 2)
    proposal["venue"] = new_venue
    proposal["title"] = event.get("title")
    proposal["old_value"] = {"venue": event.get("venue")}
    proposal["new_value"] = {"venue": new_venue}
    proposal["explanation"] = (
        f"Venue changes from {event.get('venue') or 'not specified'} to {new_venue} "
        f"for '{event.get('title')}'.")
    return proposal


def _first_venue(text):
    venues = nlp.extract_venue_tokens(text or "")
    return venues[0] if venues else None


def _date_change(proposal, message, reference, course, event_type, events, old_raw, new_raw):
    new_date, reason = None, None
    target = nlp.target_value(message) or new_raw
    if target:
        new_date, reason = _resolve_date_from_message(target, reference, course, [])
    if new_date is None:
        # Fall back to reading a date out of the whole message, but only when the
        # message is not merely vague.
        if nlp.is_vague_timeframe(message):
            reason = "vague_timeframe"
        else:
            new_date, reason = _resolve_date_from_message(message, reference, course, [])

    if new_date is None:
        question = ("What is the new deadline?" if reason != "vague_timeframe"
                    else "What exact date should this be moved to?")
        return _clarify(
            proposal, question,
            "The message says something changed but the new date could not be determined.")

    old_date = None
    if old_raw:
        old_date, _ = _resolve_date_from_message(old_raw, reference, course, [])

    best, second = _match_events(events, course, event_type, message, old_date)
    if best is None or best[0] < MATCH_THRESHOLD:
        return _clarify(proposal, "Which existing item does this change refer to?",
                        "A change was detected but no existing record matched it.")
    if second is not None and (best[0] - second[0]) < MATCH_MARGIN:
        return _clarify(proposal, "Which of the matching records changed?",
                        "More than one existing record could match this change.")

    event = best[2]
    if event.get("event_date") == new_date:
        proposal["action"] = "DUPLICATE"
        proposal["possible_match_id"] = event["id"]
        proposal["confidence"] = 0.8
        proposal["explanation"] = f"The date is already recorded as {new_date}."
        return proposal

    proposal["action"] = "UPDATE"
    proposal["possible_match_id"] = event["id"]
    proposal["matching_confidence"] = round(min(best[0], 1.0), 2)
    proposal["confidence"] = round(min(best[0] + 0.15, 0.95), 2)
    proposal["event_date"] = new_date
    proposal["title"] = event.get("title")
    proposal["old_value"] = {"event_date": event.get("event_date")}
    proposal["new_value"] = {"event_date": new_date}
    proposal["explanation"] = (
        f"Deadline moves from {event.get('event_date') or 'not specified'} to {new_date} "
        f"for '{event.get('title')}'.")
    return proposal


def _creation(proposal, message, reference, course, event_type, events, timetable, explicit):
    """A message announcing something new (spec 16: no match -> CREATE)."""
    if len(_mentioned_event_types(message)) > 1:
        return _clarify(
            proposal, "This message seems to mention more than one item. Which should be created?",
            "Several different academic items were detected in one message.")

    if event_type is None:
        return _clarify(proposal, "What kind of academic item is this?",
                        "The type of academic item could not be determined.")

    # An explicit "no specified date" from the rep is authoritative and is not a
    # failure; the date simply stays null (spec 14).
    if explicit.get("no_date"):
        event_date, reason = None, None
    elif explicit.get("event_date"):
        event_date, reason = explicit["event_date"], None
    else:
        event_date, reason = _resolve_date_from_message(message, reference, course, timetable)
        if event_date is None and reason in (
                "vague_timeframe", "next_class_unknown_course", "next_class_no_timetable"):
            questions = {
                "vague_timeframe": "What exact date should this be scheduled for?",
                "next_class_unknown_course": "Which course is this for, so the next class can be found?",
                "next_class_no_timetable": "There is no timetable for this course yet. What date is this?",
            }
            return _clarify(proposal, questions[reason],
                            "The message does not state a date that can be resolved.")

    venue = explicit.get("venue")
    if not venue and not explicit.get("no_venue"):
        venues = nlp.extract_venue_tokens(message)
        venue = venues[0] if len(venues) == 1 and _mentions_any(message, VENUE_WORDS) else None

    event_time = explicit.get("event_time")
    if not event_time and not explicit.get("no_time"):
        event_time = nlp.parse_time(message)

    title = _build_title(course, event_type)

    duplicate = _find_duplicate(events, course, event_type, event_date)
    if duplicate is not None:
        proposal["action"] = "DUPLICATE"
        proposal["possible_match_id"] = duplicate["id"]
        proposal["matching_confidence"] = 0.9
        proposal["confidence"] = 0.85
        proposal["title"] = duplicate.get("title")
        proposal["explanation"] = (
            f"An identical {event_type.lower()} already exists for this course and date.")
        return proposal

    proposal["action"] = "CREATE"
    proposal["event_date"] = event_date
    proposal["event_time"] = event_time
    proposal["venue"] = venue
    proposal["title"] = title
    proposal["confidence"] = 0.8 if (course and event_date) else 0.6
    proposal["new_value"] = {
        "title": title, "event_type": event_type, "event_date": event_date,
        "event_time": event_time, "venue": venue,
    }
    proposal["explanation"] = (
        f"New {event_type.lower()}"
        + (f" for {course['code']}" if course else "")
        + (f" on {event_date}" if event_date else " with no date specified") + ".")
    return proposal


def _build_title(course, event_type):
    label = event_type.title()
    if course:
        return f"{course['code']} {label}"
    return label


def _find_duplicate(events, course, event_type, event_date):
    for event in events:
        if event.get("status") == "CANCELLED":
            continue
        if event.get("event_type") != event_type:
            continue
        if course and event.get("course_id") != course["id"]:
            continue
        if not course and event.get("course_id") is not None:
            continue
        if event.get("event_date") == event_date:
            return event
    return None
