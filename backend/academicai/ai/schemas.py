"""The AI proposal contract (spec 14).

Every provider - heuristic or LLM - returns this same shape, and the service
layer normalises whatever comes back before anything else sees it. A provider
is untrusted output: it can propose, but the values are clamped here so a
malformed or adversarial response cannot reach the publishing path.
"""
ACTIONS = ("CREATE", "UPDATE", "DUPLICATE", "CLARIFICATION", "CANCEL")
SCOPES = ("EVENT", "TIMETABLE", "ANNOUNCEMENT")
EVENT_TYPES = ("ASSIGNMENT", "PROJECT", "QUIZ", "TEST", "PRESENTATION",
               "EXAM", "CLASS", "OTHER")
PRIORITIES = ("LOW", "NORMAL", "HIGH")

# JSON Schema handed to the LLM provider for structured output.
PROPOSAL_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "scope": {"type": "string", "enum": list(SCOPES)},
        "course_code": {"type": ["string", "null"]},
        "event_type": {"type": ["string", "null"], "enum": list(EVENT_TYPES) + [None]},
        "title": {"type": ["string", "null"]},
        "event_date": {"type": ["string", "null"]},
        "event_time": {"type": ["string", "null"]},
        "venue": {"type": ["string", "null"]},
        "day_of_week": {"type": ["string", "null"]},
        "priority": {"type": ["string", "null"], "enum": list(PRIORITIES) + [None]},
        "old_value": {"type": ["object", "null"], "additionalProperties": True},
        "new_value": {"type": ["object", "null"], "additionalProperties": True},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "needs_clarification": {"type": "boolean"},
        "possible_match_id": {"type": ["integer", "null"]},
        "matching_confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "explanation": {"type": "string"},
        "clarification_question": {"type": ["string", "null"]},
        "discrepancies": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["action", "scope", "confidence", "needs_clarification", "explanation"],
    "additionalProperties": False,
}


def empty_proposal(**overrides):
    proposal = {
        "action": "CLARIFICATION",
        "scope": "EVENT",
        "course_code": None,
        "event_type": None,
        "title": None,
        "event_date": None,
        "event_time": None,
        "venue": None,
        "day_of_week": None,
        "priority": "NORMAL",
        "old_value": None,
        "new_value": None,
        "confidence": 0.0,
        "needs_clarification": True,
        "possible_match_id": None,
        "matching_confidence": None,
        "explanation": "",
        "clarification_question": None,
        "discrepancies": [],
    }
    proposal.update(overrides)
    return proposal


def _clamp_enum(value, allowed, default=None):
    if value is None:
        return default
    candidate = str(value).strip().upper()
    return candidate if candidate in allowed else default


def _clamp_float(value, low=0.0, high=1.0, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _clamp_text(value, max_len=500):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_len]


def normalize(raw):
    """Clamp a provider response into the contract.

    Anything unrecognised degrades to CLARIFICATION rather than being guessed
    at: the system never silently chooses between interpretations (spec 15).
    """
    if not isinstance(raw, dict):
        return empty_proposal(explanation="The AI response could not be interpreted.")

    proposal = empty_proposal()
    proposal["action"] = _clamp_enum(raw.get("action"), ACTIONS, "CLARIFICATION")
    proposal["scope"] = _clamp_enum(raw.get("scope"), SCOPES, "EVENT")
    proposal["event_type"] = _clamp_enum(raw.get("event_type"), EVENT_TYPES, None)
    proposal["priority"] = _clamp_enum(raw.get("priority"), PRIORITIES, "NORMAL")
    proposal["course_code"] = _clamp_text(raw.get("course_code"), 32)
    proposal["title"] = _clamp_text(raw.get("title"), 200)
    proposal["event_date"] = _clamp_text(raw.get("event_date"), 10)
    proposal["event_time"] = _clamp_text(raw.get("event_time"), 5)
    proposal["venue"] = _clamp_text(raw.get("venue"), 100)
    proposal["day_of_week"] = _clamp_enum(
        raw.get("day_of_week"),
        ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"), None)
    proposal["confidence"] = _clamp_float(raw.get("confidence"))
    proposal["needs_clarification"] = bool(raw.get("needs_clarification", False))
    proposal["explanation"] = _clamp_text(raw.get("explanation"), 1000) or ""
    proposal["clarification_question"] = _clamp_text(raw.get("clarification_question"), 500)
    proposal["old_value"] = raw.get("old_value") if isinstance(raw.get("old_value"), dict) else None
    proposal["new_value"] = raw.get("new_value") if isinstance(raw.get("new_value"), dict) else None

    match_id = raw.get("possible_match_id")
    proposal["possible_match_id"] = match_id if isinstance(match_id, int) else None
    proposal["matching_confidence"] = (
        _clamp_float(raw.get("matching_confidence")) if raw.get("matching_confidence") is not None
        else None)

    discrepancies = raw.get("discrepancies")
    proposal["discrepancies"] = (
        [str(d)[:200] for d in discrepancies][:10] if isinstance(discrepancies, list) else [])

    # An UPDATE or CANCEL without a target cannot be published, so it degrades
    # to a clarification rather than being applied to the wrong record.
    if proposal["action"] in ("UPDATE", "CANCEL") and proposal["possible_match_id"] is None:
        proposal["action"] = "CLARIFICATION"
        proposal["needs_clarification"] = True
        if not proposal["clarification_question"]:
            proposal["clarification_question"] = (
                "Which existing record does this message refer to?")

    if proposal["action"] == "CLARIFICATION":
        proposal["needs_clarification"] = True

    return proposal
