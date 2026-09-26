"""Typo-tolerant text and date helpers for message interpretation (spec 15).

WhatsApp messages arrive with missing spaces, doubled letters and dropped
characters, so every keyword match here is fuzzy. Dates are always resolved
against the submission date supplied by the backend, never against the
machine's own clock.
"""
import re
from datetime import date, timedelta
from difflib import SequenceMatcher

WEEKDAYS = {
    "MONDAY": 0, "TUESDAY": 1, "WEDNESDAY": 2, "THURSDAY": 3,
    "FRIDAY": 4, "SATURDAY": 5, "SUNDAY": 6,
}
WEEKDAY_NAMES = list(WEEKDAYS.keys())

# Phrases that state a timeframe without pinning a date. These must produce a
# clarification rather than an invented date (spec 15, 16).
VAGUE_TIME_PATTERNS = (
    r"next\s+(two|three|four|couple\s+of|few|2|3|4)\s+weeks?",
    r"in\s+(a\s+)?(couple|few)\s+of?\s+(days|weeks)",
    r"(some\s*time|sometime)\b",
    r"\bsoon\b",
    r"later\s+(this|next)\s+(week|month)",
    r"next\s+month\b",
    r"\bshortly\b",
    r"before\s+(the\s+)?(semester|session)\s+ends",
)


def normalize(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def tokens(text):
    return re.findall(r"[a-z0-9]+", normalize(text))


def similar(a, b):
    return SequenceMatcher(None, a or "", b or "").ratio()


def fuzzy_contains(text, keyword, threshold=0.82):
    """True when `keyword` appears in `text`, tolerating typos.

    Checks exact substring first (which also catches run-together words like
    "assignmentto"), then compares each token and each adjacent token pair.
    """
    normalized = normalize(text)
    keyword = keyword.lower()
    if keyword in normalized:
        return True
    word_list = tokens(normalized)
    for word in word_list:
        if similar(word, keyword) >= threshold:
            return True
        # Handles a keyword fused to a neighbouring word.
        if len(word) > len(keyword) and similar(word[:len(keyword) + 2], keyword) >= threshold:
            return True
    for i in range(len(word_list) - 1):
        joined = word_list[i] + word_list[i + 1]
        if similar(joined, keyword) >= threshold:
            return True
    return False


def find_weekday(text, threshold=0.78):
    """Return (WEEKDAY, position) for the first weekday mentioned, else None."""
    word_list = re.findall(r"[a-z]+", normalize(text))
    position = 0
    for word in word_list:
        position = normalize(text).find(word, position)
        for name in WEEKDAY_NAMES:
            stem = name.lower()[:5]          # 'monda', 'tuesd', ...
            candidate = word[:len(stem) + 3]
            if similar(candidate, stem) >= threshold or word.startswith(stem):
                return name, position
        position += len(word)
    return None


def all_weekdays(text, threshold=0.78):
    """Every weekday mentioned, in order of appearance, with position."""
    found = []
    for match in re.finditer(r"[a-z]+", normalize(text)):
        word = match.group(0)
        for name in WEEKDAY_NAMES:
            stem = name.lower()[:5]
            if word.startswith(stem) or similar(word[:len(stem) + 3], stem) >= threshold:
                found.append((name, match.start()))
                break
    return found


def is_vague_timeframe(text):
    normalized = normalize(text)
    return any(re.search(pattern, normalized) for pattern in VAGUE_TIME_PATTERNS)


def next_weekday(reference, weekday_name, next_week=False):
    """Resolve a weekday name to a concrete date relative to `reference`.

    Plain "friday" means the next Friday on or after the reference date.
    "next week monday" means the Monday of the following calendar week.
    """
    target = WEEKDAYS[weekday_name]
    if next_week:
        # Monday of next week, then offset to the requested day.
        start_of_next_week = reference + timedelta(days=7 - reference.weekday())
        return start_of_next_week + timedelta(days=target)
    delta = (target - reference.weekday()) % 7
    return reference + timedelta(days=delta)


EXPLICIT_DATE_PATTERNS = (
    (r"\b(\d{4})-(\d{2})-(\d{2})\b", ("y", "m", "d")),
    (r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", ("d", "m", "y")),
)
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}


def parse_explicit_date(text, reference):
    normalized = normalize(text)
    for pattern, order in EXPLICIT_DATE_PATTERNS:
        match = re.search(pattern, normalized)
        if match:
            parts = dict(zip(order, match.groups()))
            try:
                return date(int(parts["y"]), int(parts["m"]), int(parts["d"]))
            except ValueError:
                return None
    # "12th of october", "october 12"
    month_match = re.search(r"\b(" + "|".join(MONTHS) + r")\w*\s+(\d{1,2})\b", normalized)
    if month_match:
        try:
            return date(reference.year, MONTHS[month_match.group(1)], int(month_match.group(2)))
        except ValueError:
            return None
    day_first = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + "|".join(MONTHS) + r")",
                          normalized)
    if day_first:
        try:
            return date(reference.year, MONTHS[day_first.group(2)], int(day_first.group(1)))
        except ValueError:
            return None
    return None


def parse_time(text):
    """Extract a time of day as HH:MM, if one is stated."""
    normalized = normalize(text)
    match = re.search(r"\b(\d{1,2})\s*[:.]\s*(\d{2})\s*(am|pm)?\b", normalized)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        meridiem = match.group(3)
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    match = re.search(r"\b(\d{1,2})\s*(am|pm)\b", normalized)
    if match:
        hour = int(match.group(1))
        if match.group(2) == "pm" and hour < 12:
            hour += 12
        if match.group(2) == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23:
            return f"{hour:02d}:00"
    return None


COURSE_CODE_RE = re.compile(r"\b([a-z]{2,4})\s*[-/]?\s*(\d{3})\b")
BARE_NUMBER_RE = re.compile(r"\b(\d{3})\b")


def extract_course_codes(text):
    """Course codes written as 'cos202', 'cos 202', 'COS-202'."""
    return [f"{m.group(1)}{m.group(2)}".upper() for m in COURSE_CODE_RE.finditer(normalize(text))]


def extract_bare_numbers(text):
    """Three-digit numbers that may be a course number without its prefix."""
    normalized = normalize(text)
    prefixed = {m.group(2) for m in COURSE_CODE_RE.finditer(normalized)}
    return [n for n in BARE_NUMBER_RE.findall(normalized) if n not in prefixed]


VENUE_RE = re.compile(r"\b([a-z]{1,3}\s?-?\s?\d{2,4}[a-z]?)\b")


def extract_venue_tokens(text):
    """Venue-like tokens such as 'b007', 'th202', 'lt 1'."""
    normalized = normalize(text)
    return [re.sub(r"[\s-]", "", m.group(1)).upper() for m in VENUE_RE.finditer(normalized)]


FROM_TO_RE = re.compile(r"\bfrom\s+(.{1,40}?)\s+to\s+(.{1,40}?)(?:[.,;]|$)")
TO_RE = re.compile(r"\b(?:extended|moved|shifted|postponed|changed|pushed|rescheduled)\s+"
                   r"(?:to|till|until)\s+(.{1,60}?)(?:[.,;]|$)")
# Tolerates "instead of", "insted of", "instd of" and a fused "ofevery".
INSTEAD_RE = re.compile(r"\binst\w{0,3}\s*of\s*(.{1,40}?)(?:[.,;]|$)")


def from_to_values(text):
    """Old/new values from 'changed from X to Y'."""
    match = FROM_TO_RE.search(normalize(text))
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return None, None


def target_value(text):
    match = TO_RE.search(normalize(text))
    return match.group(1).strip() if match else None


def instead_of_value(text):
    match = INSTEAD_RE.search(normalize(text))
    return match.group(1).strip() if match else None
