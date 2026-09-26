"""Academic calendar and session lifecycle (spec 23).

A verified rep uploads the calendar text; the system extracts the session and
term dates from it. At session end the community is archived. Nothing is
carried into a new session automatically: levels are not incremented, courses
and timetables are not copied, and rep authority does not transfer. Students
establish membership of the new session's community themselves, and that
community elects its own reps.
"""
import json
import re

from .. import clock
from ..db.connection import execute, insert_returning_id, query_all, query_one, transaction
from ..errors import AuthorizationError, ConflictError, ValidationError
from ..security import authz
from ..ai import nlp
from . import community_service
from .change_history import record_change

MAX_CALENDAR_LENGTH = 20000

LABELLED_DATE_RE = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z /&-]{2,60}?)\s*[:\-–]\s*(?P<value>[^\n;]{4,40})")

START_HINTS = ("session begins", "session starts", "session commences", "resumption",
               "semester begins", "semester starts", "commencement", "start of session",
               "lectures begin", "first semester begins")
END_HINTS = ("session ends", "end of session", "session closes", "semester ends",
             "end of semester", "vacation begins", "closing", "last day")


def extract(raw_text, reference=None):
    """Pull session/term dates out of free-form calendar text.

    Returns a dict with session_start, session_end and every labelled period
    found. Nothing is guessed: a label whose value is not a readable date is
    simply omitted.
    """
    reference = reference or clock.now().date()
    periods = []
    for match in LABELLED_DATE_RE.finditer(raw_text or ""):
        label = " ".join(match.group("label").split()).strip(" -:")
        value = match.group("value").strip()
        parsed = nlp.parse_explicit_date(value, reference)
        if parsed is None:
            continue
        periods.append({"label": label, "date": parsed.isoformat()})

    lowered = {p["label"].lower(): p["date"] for p in periods}

    def _find(hints):
        # Hints are ordered by specificity: "session ends" must win over
        # "semester ends" even when the semester line appears first.
        for hint in hints:
            for label, value in lowered.items():
                if hint in label:
                    return value
        return None

    session_start = _find(START_HINTS)
    session_end = _find(END_HINTS)
    if session_start is None and periods:
        session_start = min(p["date"] for p in periods)
    if session_end is None and periods:
        session_end = max(p["date"] for p in periods)
    return {"session_start": session_start, "session_end": session_end, "periods": periods}


def upload(actor_id, community_id, payload):
    raw_text = payload.get("raw_text") or payload.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValidationError("Calendar text is required.")
    if len(raw_text) > MAX_CALENDAR_LENGTH:
        raise ValidationError(
            f"Calendar text must be {MAX_CALENDAR_LENGTH} characters or fewer.")

    extracted = extract(raw_text)
    with transaction() as conn:
        if not authz.is_rep(actor_id, community_id, conn=conn):
            raise AuthorizationError("Only a verified course rep can upload the academic calendar.")
        calendar_id = insert_returning_id(
            """INSERT INTO academic_calendars
               (community_id, uploaded_by, raw_text, session_start, session_end, extracted, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (community_id, actor_id, raw_text, extracted["session_start"],
             extracted["session_end"], json.dumps(extracted), clock.now_iso()), conn=conn)
        record_change(community_id, "academic_calendar", calendar_id, "CALENDAR_UPLOADED",
                      None, {"session_start": extracted["session_start"],
                             "session_end": extracted["session_end"]},
                      actor_id=actor_id, conn=conn)
        return query_one("SELECT * FROM academic_calendars WHERE id = ?", (calendar_id,), conn=conn)


def current(community_id, conn=None):
    return query_one(
        "SELECT * FROM academic_calendars WHERE community_id = ? ORDER BY id DESC LIMIT 1",
        (community_id,), conn=conn)


def calendar_payload(row):
    if row is None:
        return None
    try:
        extracted = json.loads(row["extracted"]) if row["extracted"] else {}
    except (TypeError, ValueError):
        extracted = {}
    return {
        "id": row["id"],
        "session_start": row["session_start"],
        "session_end": row["session_end"],
        "periods": extracted.get("periods", []),
        "uploaded_at": row["created_at"],
    }


def archive_session(actor_id, community_id):
    """End a session (spec 23).

    MVP scope decision: this is a BACKEND/OPERATOR action. It is deliberately
    not exposed in the UI, and nothing archives a community automatically when
    the calendar's session-end date passes. Archiving is irreversible and
    community-wide, so a user-facing session-management workflow has to be
    designed before it gets an entry point. Everything below stays intact and
    tested regardless.

    Archiving revokes every rep's authority, because rep authority does not
    carry into a new academic session, and cancels outstanding reminders so an
    archived session stops generating notifications. Memberships and history
    are retained so students keep their record.
    """
    with transaction() as conn:
        community = community_service.get_community(community_id, conn=conn)
        if not authz.is_rep(actor_id, community_id, conn=conn):
            raise AuthorizationError("Only a verified course rep can archive a session.")
        if community["status"] == "ARCHIVED":
            raise ConflictError("This academic session is already archived.")

        reps = query_all(
            """SELECT user_id FROM community_members
               WHERE community_id = ? AND status = 'ACTIVE' AND role = 'VERIFIED_REP'""",
            (community_id,), conn=conn)

        community_service.archive_community(community_id, conn=conn)
        execute(
            """UPDATE community_members SET role = 'STUDENT', rep_since = NULL
               WHERE community_id = ? AND role = 'VERIFIED_REP'""",
            (community_id,), conn=conn)
        execute(
            """UPDATE event_reminders SET status = 'CANCELLED'
               WHERE status = 'PENDING' AND event_id IN
                     (SELECT id FROM academic_events WHERE community_id = ?)""",
            (community_id,), conn=conn)
        execute(
            """UPDATE notifications SET status = 'FAILED', last_error = 'session archived'
               WHERE community_id = ? AND status = 'PENDING'""",
            (community_id,), conn=conn)
        # Reps must re-authenticate; their authority is gone.
        for rep in reps:
            from .auth_service import revoke_all_sessions
            revoke_all_sessions(rep["user_id"], conn=conn)

        record_change(community_id, "academic_community", community_id, "SESSION_ARCHIVED",
                      {"status": community["status"]}, {"status": "ARCHIVED"},
                      actor_id=actor_id, conn=conn)
        return query_one("SELECT * FROM academic_communities WHERE id = ?",
                         (community_id,), conn=conn)
