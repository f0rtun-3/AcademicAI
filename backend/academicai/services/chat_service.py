"""AI Chat (spec 22).

The backend identifies the student's exact community, selects only the records
that student is authorised to see, and hands them to the provider. Conversation
history is stored separately from official academic data and is private to the
student who created it.

The chat may PROPOSE a personal reminder. It never creates one on its own and
it never touches official academic information.
"""
from .. import clock
from ..ai import provider as ai_provider
from ..ai.prompts import sanitize_untrusted
from ..db.connection import (execute, insert_returning_id, query_all, query_one,
                             transaction)
from ..errors import NotFoundError, ValidationError
from ..security import authz
from . import (announcement_service, community_service, course_service, event_service,
               reminder_service, timetable_service)
from .change_history import change_payload

MAX_QUESTION_LENGTH = 1000
HISTORY_LIMIT = 20


def _authorized_context(user_id, community_id):
    """Exactly the data this student may see, and nothing else (spec 22, 25)."""
    community = community_service.get_community(community_id)
    membership = authz.active_membership(user_id)
    courses = course_service.list_courses(community_id)
    timetable = timetable_service.list_entries(community_id)
    events = event_service.list_events(community_id, include_cancelled=False)
    announcements = announcement_service.list_announcements(community_id, limit=10)
    changes = community_service.recent_changes(community_id, limit=15)
    reminders = reminder_service.list_personal(user_id)

    return {
        "today": clock.now().date().isoformat(),
        # The asking student's own membership row id. It lets the answer say
        # "your membership was approved" only when it really was theirs; a
        # membership change records the MEMBERSHIP row, not the user, so
        # without this every approval would have to be described neutrally.
        # Their own membership is data they already hold.
        "viewer": {"membership_id": (membership or {})["id"] if membership else None},
        "community": {
            "department": community["department"],
            "level": community["level"],
            "academic_session": community["academic_session"],
        },
        "courses": [{"id": c["id"], "code": c["code"], "title": c["title"]} for c in courses],
        "timetable": [timetable_service.entry_payload(t) for t in timetable],
        "events": [event_service.event_payload(e) for e in events],
        "announcements": [announcement_service.announcement_payload(a) for a in announcements],
        "changes": [change_payload(c) for c in changes],
        "reminders": [reminder_service.reminder_payload(r) for r in reminders],
    }


def ask(user_id, community_id, payload):
    raw_question = payload.get("question") or payload.get("message")
    if not isinstance(raw_question, str) or not raw_question.strip():
        raise ValidationError("A question is required.")
    if len(raw_question) > MAX_QUESTION_LENGTH:
        raise ValidationError(f"Question must be {MAX_QUESTION_LENGTH} characters or fewer.")
    question = sanitize_untrusted(raw_question, MAX_QUESTION_LENGTH)

    conversation_id = payload.get("conversation_id")
    request = _authorized_context(user_id, community_id)
    request["question"] = question
    request["history"] = _recent_messages(conversation_id, user_id) if conversation_id else []

    raw = ai_provider.get_provider().answer(request)
    result = _normalize_answer(raw)

    conversation_id = _persist(user_id, community_id, conversation_id, question, result["answer"])
    result["conversation_id"] = conversation_id
    return result


def _normalize_answer(raw):
    if not isinstance(raw, dict):
        return {"answer": "I could not answer that.", "grounded": False,
                "referenced_event_ids": [], "suggested_reminder": None}
    answer = str(raw.get("answer") or "").strip()[:4000]
    reminder = raw.get("suggested_reminder")
    if not isinstance(reminder, dict) or not reminder.get("title") or not reminder.get("remind_at"):
        reminder = None
    ids = raw.get("referenced_event_ids")
    return {
        "answer": answer or "I could not answer that from your academic records.",
        "grounded": bool(raw.get("grounded", False)),
        "referenced_event_ids": [i for i in ids if isinstance(i, int)][:20]
        if isinstance(ids, list) else [],
        "suggested_reminder": reminder,
    }


def _recent_messages(conversation_id, user_id):
    conversation = query_one(
        "SELECT * FROM chat_conversations WHERE id = ? AND user_id = ?",
        (conversation_id, user_id))
    if conversation is None:
        raise NotFoundError("Conversation not found.")
    rows = query_all(
        "SELECT role, content FROM chat_messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
        (conversation_id, HISTORY_LIMIT))
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def _persist(user_id, community_id, conversation_id, question, answer):
    now = clock.now_iso()
    with transaction() as conn:
        if conversation_id is None:
            conversation_id = insert_returning_id(
                """INSERT INTO chat_conversations (user_id, community_id, title, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, community_id, question[:80], now, now), conn=conn)
        else:
            owned = query_one(
                "SELECT id FROM chat_conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id), conn=conn)
            if owned is None:
                raise NotFoundError("Conversation not found.")
            execute("UPDATE chat_conversations SET updated_at = ? WHERE id = ?",
                    (now, conversation_id), conn=conn)
        for role, content in (("user", question), ("assistant", answer)):
            execute(
                """INSERT INTO chat_messages (conversation_id, role, content, created_at)
                   VALUES (?, ?, ?, ?)""",
                (conversation_id, role, content, now), conn=conn)
    return conversation_id


def history(user_id, conversation_id=None, limit=50):
    if conversation_id is not None:
        conversation = query_one(
            "SELECT * FROM chat_conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id))
        if conversation is None:
            raise NotFoundError("Conversation not found.")
        rows = query_all(
            "SELECT * FROM chat_messages WHERE conversation_id = ? ORDER BY id LIMIT ?",
            (conversation_id, limit))
        return {
            "conversation_id": conversation_id,
            "messages": [{"role": r["role"], "content": r["content"],
                          "created_at": r["created_at"]} for r in rows],
        }
    rows = query_all(
        """SELECT * FROM chat_conversations WHERE user_id = ?
           ORDER BY updated_at DESC LIMIT ?""",
        (user_id, limit))
    return {"conversations": [
        {"id": r["id"], "title": r["title"], "updated_at": r["updated_at"]} for r in rows]}


SUGGESTED_PROMPTS = [
    "What assignments do I have this week?",
    "What classes do I have tomorrow?",
    "What is my next deadline?",
    "What changed recently?",
    "Where is my next class?",
    "What should I focus on this week?",
]
