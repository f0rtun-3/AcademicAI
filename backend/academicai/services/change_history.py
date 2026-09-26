"""Change history (spec 18).

The current record represents current state; this table preserves the
transitions. History is append-only and is never deleted because a current
value changed (spec 16).
"""
import json

from .. import clock
from ..db.connection import insert_returning_id, query_all


def _encode(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)


def record_change(community_id, entity_type, entity_id, change_type,
                  old_value, new_value, actor_id=None, source_message=None,
                  context=None, conn=None):
    return insert_returning_id(
        """INSERT INTO change_history
           (community_id, entity_type, entity_id, change_type, old_value, new_value,
            actor_id, source_message, context, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (community_id, entity_type, entity_id, change_type, _encode(old_value),
         _encode(new_value), actor_id, source_message, _encode(context), clock.now_iso()),
        conn=conn,
    )


def history_for(entity_type, entity_id, conn=None):
    return query_all(
        """SELECT * FROM change_history
           WHERE entity_type = ? AND entity_id = ? ORDER BY id""",
        (entity_type, entity_id), conn=conn,
    )


def _decode(value):
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _subject(row):
    """The record a change is about, when the query joined it in (see
    community_service.recent_changes). None when it did not, or when nothing
    is recorded - the reader then words the change without a subject."""
    keys = row.keys()
    if "subject_title" not in keys:
        return None
    subject = {
        "title": row["subject_title"],
        "course_code": row["subject_course_code"],
        "event_type": row["subject_event_type"],
    }
    return subject if any(subject.values()) else None


def change_payload(row):
    return {
        "id": row["id"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "change_type": row["change_type"],
        "old_value": _decode(row["old_value"]),
        "new_value": _decode(row["new_value"]),
        "actor_id": row["actor_id"],
        "actor_name": row["actor_name"] if "actor_name" in row.keys() else None,
        "source_message": row["source_message"],
        "created_at": row["created_at"],
        "subject": _subject(row),
    }
