"""Transfers between communities (spec 10)."""


TARGET = {"university": "Babcock University", "department": "Software Engineering",
          "level": "300", "academic_session": "2026/2027"}


def test_transfer_request_leaves_old_membership_active(client, joined_user, rep_community):
    """Old membership remains ACTIVE until the destination approves (spec 10)."""
    rep_dest, _ = rep_community(size=4, level="300")
    student = joined_user(client, level="200")
    old_community = student.community_id

    resp = student.post("/api/community/transfer", json=TARGET)
    assert resp.status_code == 201
    assert resp.get_json()["awaiting_approval"] is True
    # Still a full member of the original community.
    assert student.get("/api/community").get_json()["community"]["id"] == old_community


def test_identity_verification_does_not_auto_grant_destination_membership(
        client, joined_user, rep_community):
    rep_dest, _ = rep_community(size=4, level="300")
    student = joined_user(client, level="200")
    student.post("/api/community/transfer", json=TARGET)
    requests = rep_dest.get("/api/community/requests").get_json()["requests"]
    assert student.user_id in [r["user_id"] for r in requests]


def test_transfer_approval_moves_the_student(client, joined_user, rep_community):
    rep_dest, _ = rep_community(size=4, level="300")
    student = joined_user(client, level="200")
    old_community = student.community_id
    student.post("/api/community/transfer", json=TARGET)

    resp = rep_dest.post(f"/api/community/requests/{student.user_id}/approve")
    assert resp.status_code == 200
    community = student.get("/api/community").get_json()["community"]
    assert community["id"] != old_community
    assert community["level"] == "300"


def test_transfer_rejection_leaves_student_in_old_community(client, joined_user, rep_community):
    """A rejected transfer must not strand the student (spec 10)."""
    rep_dest, _ = rep_community(size=4, level="300")
    student = joined_user(client, level="200")
    old_community = student.community_id
    student.post("/api/community/transfer", json=TARGET)

    rep_dest.post(f"/api/community/requests/{student.user_id}/reject")
    assert student.get("/api/community").get_json()["community"]["id"] == old_community


def test_transfer_ends_old_enrollments(client, joined_user, rep_community, app):
    rep_dest, _ = rep_community(size=4, level="300")
    student = joined_user(client, level="200")
    with app.app_context():
        from academicai.db.connection import execute, insert_returning_id, transaction
        from academicai import clock
        with transaction() as conn:
            course_id = insert_returning_id(
                """INSERT INTO courses (community_id, code, title, created_at, updated_at)
                   VALUES (?, 'COS202', 'Data Structures', ?, ?)""",
                (student.community_id, clock.now_iso(), clock.now_iso()), conn=conn)
            execute("""INSERT INTO course_enrollments (course_id, user_id, created_at)
                       VALUES (?, ?, ?)""",
                    (course_id, student.user_id, clock.now_iso()), conn=conn)

    student.post("/api/community/transfer", json=TARGET)
    rep_dest.post(f"/api/community/requests/{student.user_id}/approve")

    with app.app_context():
        from academicai.db.connection import query_all
        rows = query_all("SELECT * FROM course_enrollments WHERE user_id = ?", (student.user_id,))
        assert rows == []


def test_transferring_rep_loses_authority_and_sessions(client, rep_community, run_worker):
    """A rep who transfers loses rep authority and has sessions invalidated (spec 10)."""
    rep_dest, _ = rep_community(size=4, level="300")
    rep_old, _members = rep_community(size=4, level="200")
    rep_old.relogin()
    assert rep_old.get("/api/community").get_json()["membership"]["role"] == "VERIFIED_REP"

    rep_old.post("/api/community/transfer", json=TARGET)
    rep_dest.relogin()
    rep_dest.post(f"/api/community/requests/{rep_old.user_id}/approve")

    # Session epoch was invalidated by the transfer.
    assert rep_old.get("/api/community").status_code == 401
    rep_old.relogin()
    membership = rep_old.get("/api/community").get_json()["membership"]
    assert membership["role"] == "STUDENT"


def test_transfer_to_pending_community_joins_immediately(client, joined_user):
    student = joined_user(client, level="200")
    old_community = student.community_id
    resp = student.post("/api/community/transfer", json=TARGET)
    assert resp.status_code == 201
    # Destination did not exist, so it was created PENDING and bootstrap applies.
    assert resp.get_json()["awaiting_approval"] is False
    assert student.get("/api/community").get_json()["community"]["id"] != old_community


def test_student_keeps_single_active_membership(client, joined_user, rep_community, app):
    rep_dest, _ = rep_community(size=4, level="300")
    student = joined_user(client, level="200")
    student.post("/api/community/transfer", json=TARGET)
    rep_dest.post(f"/api/community/requests/{student.user_id}/approve")
    with app.app_context():
        from academicai.db.connection import query_all
        active = query_all(
            "SELECT * FROM community_members WHERE user_id = ? AND status = 'ACTIVE'",
            (student.user_id,))
        assert len(active) == 1
