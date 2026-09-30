"""Official-record integrity: removed courses, optimistic versioning, and the
single-active-membership invariant.

Ensures:
  * a REMOVED course cannot be re-enrolled into or attached to new official
    events;
  * announcement and course updates include the version in the UPDATE itself,
    so the guarantee does not depend on the engine's write lock;
  * at most one ACTIVE membership per user is enforced by the database.
"""
import pytest

from academicai import clock
from tests.pg_support import INTEGRITY_ERRORS

pytestmark = pytest.mark.security


# --- A removed course is gone for every purpose ----------------------------

def test_a_removed_course_cannot_be_enrolled_into(client, academic_community):
    setup = academic_community(size=5, seed_events=False)
    student = setup.members[1]
    course = setup.rep.post("/api/community/courses",
                            json={"code": "COS777"}).get_json()["course"]
    assert student.post(f"/api/community/courses/{course['id']}/enroll").status_code == 201

    setup.rep.delete(f"/api/community/courses/{course['id']}")
    # Enrolling in a removed course is refused rather than resurrecting it.
    assert student.post(f"/api/community/courses/{course['id']}/enroll").status_code == 404


def test_a_removed_course_cannot_be_attached_to_a_new_event(client, academic_community, app):
    setup = academic_community(size=5, seed_events=False)
    course = setup.rep.post("/api/community/courses",
                            json={"code": "COS778"}).get_json()["course"]
    setup.rep.delete(f"/api/community/courses/{course['id']}")

    resp = setup.rep.post("/api/events", json={
        "title": "Ghost assignment", "event_type": "ASSIGNMENT",
        "course_id": course["id"], "event_date": "2026-11-05"})
    assert resp.status_code == 404

    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT COUNT(*) AS n FROM academic_events WHERE title = ?",
                         ("Ghost assignment",))["n"] == 0
        assert query_one("SELECT COUNT(*) AS n FROM notifications WHERE subject LIKE ?",
                         ("%Ghost assignment%",))["n"] == 0


def test_ai_publish_cannot_attach_a_removed_course(client, academic_community, app):
    setup = academic_community(size=5, seed_events=False)
    course = setup.rep.post("/api/community/courses",
                            json={"code": "COS779"}).get_json()["course"]
    setup.rep.delete(f"/api/community/courses/{course['id']}")

    resp = setup.rep.post("/api/ai/publish", json={
        "action": "CREATE", "scope": "EVENT", "title": "Ghost via AI",
        "event_type": "ASSIGNMENT", "course_id": course["id"],
        "event_date": "2026-11-05"})
    assert resp.status_code == 404
    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT COUNT(*) AS n FROM academic_events WHERE title = ?",
                         ("Ghost via AI",))["n"] == 0


def test_a_removed_course_cannot_be_edited_or_removed_again(client, academic_community):
    setup = academic_community(size=5, seed_events=False)
    course = setup.rep.post("/api/community/courses",
                            json={"code": "COS780"}).get_json()["course"]
    setup.rep.delete(f"/api/community/courses/{course['id']}")

    assert setup.rep.put(f"/api/community/courses/{course['id']}",
                         json={"title": "Resurrected"}).status_code == 404
    assert setup.rep.delete(f"/api/community/courses/{course['id']}").status_code == 404


def test_recreating_a_course_under_the_same_code_still_works(client, academic_community):
    """Removal must not permanently burn the course code."""
    setup = academic_community(size=5, seed_events=False)
    first = setup.rep.post("/api/community/courses",
                           json={"code": "COS781"}).get_json()["course"]
    setup.rep.delete(f"/api/community/courses/{first['id']}")

    again = setup.rep.post("/api/community/courses",
                           json={"code": "COS781", "title": "Back"})
    assert again.status_code == 201
    listed = [c["code"] for c in
              setup.rep.get("/api/community/courses").get_json()["courses"]]
    assert "COS781" in listed


def test_events_created_before_removal_keep_their_history(client, academic_community, app):
    """Removing a course must not rewrite records that already referenced it."""
    setup = academic_community(size=5, seed_events=False)
    course = setup.rep.post("/api/community/courses",
                            json={"code": "COS782"}).get_json()["course"]
    event = setup.rep.post("/api/events", json={
        "title": "Before removal", "event_type": "ASSIGNMENT",
        "course_id": course["id"], "event_date": "2026-10-20"}).get_json()["event"]

    setup.rep.delete(f"/api/community/courses/{course['id']}")
    with app.app_context():
        from academicai.db.connection import query_one
        row = query_one("SELECT course_id, status FROM academic_events WHERE id = ?",
                        (event["id"],))
        assert row["course_id"] == course["id"]
        assert row["status"] == "SCHEDULED"


# --- Optimistic versioning is in the WHERE clause --------------------------

def test_a_stale_announcement_update_is_rejected(client, academic_community, app):
    setup = academic_community(size=5, seed_events=False)
    rep = setup.rep
    ann = rep.post("/api/community/announcements",
                   json={"title": "Original", "body": "b"}).get_json()["announcement"]
    stale = ann["version"]

    assert rep.put(f"/api/community/announcements/{ann['id']}",
                   json={"title": "First", "expected_version": stale}).status_code == 200
    second = rep.put(f"/api/community/announcements/{ann['id']}",
                     json={"title": "Second", "expected_version": stale})
    assert second.status_code == 409

    with app.app_context():
        from academicai.db.connection import query_one
        row = query_one("SELECT title, version FROM announcements WHERE id = ?", (ann["id"],))
        assert row["title"] == "First"
        assert row["version"] == stale + 1


def test_the_announcement_update_carries_the_version_in_its_where_clause(
        client, academic_community, app):
    """Proves the guarantee does not rest on the earlier check alone.

    The version is bumped underneath the service after it has read the row,
    which only a compare-and-swap UPDATE can catch.
    """
    from academicai.errors import ConflictError
    from academicai.services import announcement_service

    setup = academic_community(size=5, seed_events=False)
    ann = setup.rep.post("/api/community/announcements",
                         json={"title": "CAS", "body": "b"}).get_json()["announcement"]

    real_get = announcement_service.get_announcement

    def bump_then_get(announcement_id, community_id, conn=None):
        row = real_get(announcement_id, community_id, conn=conn)
        from academicai.db.connection import execute
        execute("UPDATE announcements SET version = version + 1 WHERE id = ?",
                (announcement_id,), conn=conn)
        return row

    announcement_service.get_announcement = bump_then_get
    try:
        with app.app_context():
            with pytest.raises(ConflictError):
                announcement_service.update_announcement(
                    setup.rep.user_id, setup.community_id, ann["id"], {"title": "Lost"})
    finally:
        announcement_service.get_announcement = real_get

    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT title FROM announcements WHERE id = ?",
                         (ann["id"],))["title"] == "CAS"


def test_the_course_update_carries_the_version_in_its_where_clause(
        client, academic_community, app):
    from academicai.errors import ConflictError
    from academicai.services import course_service

    setup = academic_community(size=5, seed_events=False)
    course = setup.rep.post("/api/community/courses",
                            json={"code": "COS783", "title": "Keep"}).get_json()["course"]

    real_get = course_service.get_course

    def bump_then_get(course_id, community_id, conn=None, include_removed=False):
        row = real_get(course_id, community_id, conn=conn, include_removed=include_removed)
        from academicai.db.connection import execute
        execute("UPDATE courses SET version = version + 1 WHERE id = ?",
                (course_id,), conn=conn)
        return row

    course_service.get_course = bump_then_get
    try:
        with app.app_context():
            with pytest.raises(ConflictError):
                course_service.update_course(setup.rep.user_id, setup.community_id,
                                             course["id"], {"title": "Lost"})
    finally:
        course_service.get_course = real_get

    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT title FROM courses WHERE id = ?",
                         (course["id"],))["title"] == "Keep"


def test_a_rejected_stale_update_generates_no_notification(client, academic_community, app):
    setup = academic_community(size=5)
    rep = setup.rep
    event = setup.cos202_assignment
    stale = event["version"]

    rep.put(f"/api/events/{event['id']}",
            json={"venue": "B100", "expected_version": stale})
    with app.app_context():
        from academicai.db.connection import query_one
        before = query_one("SELECT COUNT(*) AS n FROM notifications")["n"]

    assert rep.put(f"/api/events/{event['id']}",
                   json={"venue": "B200", "expected_version": stale}).status_code == 409

    with app.app_context():
        from academicai.db.connection import query_one
        assert query_one("SELECT COUNT(*) AS n FROM notifications")["n"] == before
        assert query_one("SELECT venue FROM academic_events WHERE id = ?",
                         (event["id"],))["venue"] == "B100"


# --- One ACTIVE membership, enforced by the database -----------------------

def test_the_database_refuses_a_second_active_membership(client, academic_community, app):
    """Bypass the service layer entirely and write directly."""
    setup = academic_community(size=4, seed_events=False)
    other = academic_community(size=4, department="Computer Science", seed_events=False)
    member = setup.members[1]

    with app.app_context():
        from academicai.db.connection import execute, transaction
        with pytest.raises(INTEGRITY_ERRORS):
            with transaction() as conn:
                execute("""INSERT INTO community_members
                           (community_id, user_id, role, status, requested_at)
                           VALUES (?, ?, 'STUDENT', 'ACTIVE', ?)""",
                        (other.community_id, member.user_id, clock.now_iso()), conn=conn)


def test_a_pending_request_alongside_an_active_membership_is_allowed(
        client, academic_community, rep_community, app):
    """The transfer flow depends on this combination remaining legal."""
    destination_rep, _ = rep_community(size=4, level="300")
    origin = academic_community(size=4, seed_events=False)
    mover = origin.members[1]

    assert mover.post("/api/community/transfer", json={
        "university": "Babcock University", "department": "Software Engineering",
        "level": "300", "academic_session": "2026/2027"}).status_code == 201

    with app.app_context():
        from academicai.db.connection import query_all
        rows = query_all("SELECT community_id, status FROM community_members WHERE user_id = ?",
                         (mover.user_id,))
        statuses = sorted(r["status"] for r in rows)
        assert statuses == ["ACTIVE", "PENDING_APPROVAL"]


def test_transfer_approval_keeps_exactly_one_active_membership(
        client, academic_community, rep_community, app):
    destination_rep, _ = rep_community(size=4, level="300")
    origin = academic_community(size=4, seed_events=False)
    mover = origin.members[1]
    mover.post("/api/community/transfer", json={
        "university": "Babcock University", "department": "Software Engineering",
        "level": "300", "academic_session": "2026/2027"})

    assert destination_rep.relogin().post(
        f"/api/community/requests/{mover.user_id}/approve").status_code == 200

    with app.app_context():
        from academicai.db.connection import query_all
        active = query_all("""SELECT community_id FROM community_members
                              WHERE user_id = ? AND status = 'ACTIVE'""", (mover.user_id,))
        assert len(active) == 1
        assert active[0]["community_id"] != origin.community_id


def test_bootstrap_join_into_a_pending_community_replaces_the_old_membership(
        client, joined_user, app):
    """The auto-join path must also never hold two ACTIVE rows."""
    actor = joined_user(client)
    resp = actor.post("/api/community/transfer", json={
        "university": "Babcock University", "department": "Software Engineering",
        "level": "400", "academic_session": "2026/2027"})
    assert resp.status_code == 201
    # A brand-new community is PENDING, so the join completes immediately.
    assert resp.get_json()["awaiting_approval"] is False

    with app.app_context():
        from academicai.db.connection import query_all
        active = query_all("""SELECT community_id FROM community_members
                              WHERE user_id = ? AND status = 'ACTIVE'""", (actor.user_id,))
        assert len(active) == 1
