#!/usr/bin/env python3
"""Populate a DEVELOPMENT database so the UI can be looked at with real data.

Runs against the real services, so what you see is what the rules produce - a
rep who actually won a ballot, events that actually carry change history. Two
shortcuts are taken, both marked below, because they stand in for things that
need a mail server or a 24-hour wait.

NEVER run this against a production database. It refuses to unless the
database path is one you passed in explicitly.

    ACADEMICAI_DB_PATH=instance/demo.db python3 scripts/seed_demo.py
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from academicai import clock                                    # noqa: E402
from academicai.app import create_app                           # noqa: E402
from academicai.db.connection import execute, query_one, transaction  # noqa: E402
from academicai.services import (announcement_service, auth_service,     # noqa: E402
                                 community_service, course_service,
                                 event_service, membership_service,
                                 reminder_service, rep_service,
                                 timetable_service)

PASSWORD = "Password123"
PEOPLE = [
    ("Ada Okafor", "ada@student.babcock.edu.ng", "BU/SEN/0001"),
    ("Bola Adeyemi", "bola@student.babcock.edu.ng", "BU/SEN/0002"),
    ("Chidi Eze", "chidi@student.babcock.edu.ng", "BU/SEN/0003"),
    ("Ngozi Bello", "ngozi@student.babcock.edu.ng", "BU/SEN/0004"),
    ("Emeka Nwosu", "emeka@student.babcock.edu.ng", "BU/SEN/0005"),
]
PROFILE = {
    "university": "Babcock University",
    "department": "Software Engineering",
    "level": "200",
    "academic_session": "2026/2027",
}


def day(offset):
    return (clock.now() + timedelta(days=offset)).date().isoformat()


def main():
    app = create_app()
    if app.config["DATABASE_PATH"] in (":memory:",):
        sys.exit("Point ACADEMICAI_DB_PATH at a development file first.")

    with app.app_context():
        if query_one("SELECT id FROM users WHERE email = ?", (PEOPLE[0][1],)):
            print("Already seeded. Delete the database file to start over.")
            return

        users = []
        for name, email, matric in PEOPLE:
            user, _token = auth_service.register({
                "full_name": name, "email": email,
                "password": PASSWORD, "confirm_password": PASSWORD,
                "student_id_number": matric, **PROFILE,
            })
            # SHORTCUT 1: email verification needs a real round trip. The gate
            # is exercised by the test suite; here it is marked satisfied so the
            # seeded users land on the dashboard. Nothing touches the legacy
            # identity_status column - student ID-card verification is out of
            # MVP scope and no code reads it.
            execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user["id"],))
            users.append(query_one("SELECT * FROM users WHERE id = ?", (user["id"],)))
        print(f"  {len(users)} students registered")

        community, _ = community_service.ensure_community_for_user(users[0]["id"])
        cid = community["id"]
        for user in users:
            membership_service.join_or_request(user["id"], cid)
        print(f"  community {cid}: {PROFILE['department']} level {PROFILE['level']}")

        # A real ballot, really won: nominate, three real votes, then resolve.
        nomination = rep_service.nominate(users[0]["id"], cid, users[0]["id"])
        for voter in users[1:4]:
            rep_service.cast_vote(voter["id"], nomination["id"], "YES")
        # SHORTCUT 2: the window is 24 hours. Move this ballot's deadline into
        # the past rather than waiting, then close it through the ordinary path
        # so the promotion, history and notifications are all genuine.
        with transaction() as conn:
            execute("UPDATE rep_nominations SET closes_at = ? WHERE id = ?",
                    (clock.to_iso(clock.now() - timedelta(minutes=1)), nomination["id"]),
                    conn=conn)
        rep_service.close_ballot(nomination["id"])
        rep = users[0]
        print(f"  {rep['full_name']} elected rep (3 yes / 0 no)")

        courses = {}
        for code, title in [("COS202", "Software Engineering II"),
                            ("SEN201", "Systems Analysis and Design"),
                            ("GST121", "Use of English")]:
            courses[code] = course_service.create_course(
                rep["id"], cid, {"code": code, "title": title})
        for user in users:
            for code in ("COS202", "SEN201", "GST121"):
                course_service.enroll(user["id"], cid, courses[code]["id"])
        print(f"  {len(courses)} courses, everyone enrolled")

        for c, d, start, venue in [("COS202", "MONDAY", "08:00", "B107"),
                                   ("SEN201", "TUESDAY", "10:00", "LT2"),
                                   ("COS202", "WEDNESDAY", "13:00", "B107"),
                                   ("GST121", "THURSDAY", "08:00", "LT1")]:
            timetable_service.create_entry(rep["id"], cid, {
                "course_id": courses[c]["id"], "day_of_week": d,
                "start_time": start, "venue": venue})
        print("  4 weekly classes")

        made = {}
        for key, payload in {
            "assignment": {"title": "COS202 Assignment", "event_type": "ASSIGNMENT",
                           "course_id": courses["COS202"]["id"], "event_date": day(2),
                           "priority": "HIGH",
                           "original_message": "the deadline for the cos202 assignment "
                                               "has been extended to next week monday"},
            "presentation": {"title": "SEN201 Presentation", "event_type": "PRESENTATION",
                             "course_id": courses["SEN201"]["id"], "event_date": day(5),
                             "original_message": "group 6 presentation next week wednesday"},
            "quiz": {"title": "GST121 Quiz", "event_type": "QUIZ",
                     "course_id": courses["GST121"]["id"], "event_date": day(6),
                     "venue": "LT1",
                     "original_message": "gst121 quiz on thursday in LT1"},
            "today": {"title": "Adventist Heritage", "event_type": "CLASS",
                      "event_date": day(0), "event_time": "08:00", "venue": "B007",
                      "original_message": "heritage class today 8am b007"},
            "exam": {"title": "COS202 Mid-semester Exam", "event_type": "TEST",
                     "course_id": courses["COS202"]["id"], "event_date": day(4),
                     "venue": "LT2", "priority": "HIGH",
                     "original_message": "cos202 mid semester test moved to LT2"},
        }.items():
            made[key] = event_service.create_event(rep["id"], cid, payload)

        # Changes, so the dashboard's "Needs attention" band has real history to
        # read rather than an empty projection.
        event_service.update_event(rep["id"], cid, made["assignment"]["id"],
                                   {"event_date": day(4)})
        event_service.update_event(rep["id"], cid, made["today"]["id"],
                                   {"venue": "B107"})
        event_service.cancel_event(rep["id"], cid, made["quiz"]["id"])
        print("  5 events: 1 deadline moved, 1 venue changed, 1 cancelled")

        announcement_service.create_announcement(rep["id"], cid, {
            "title": "Midterm week moved",
            "body": "Midterms now run from the 12th. Check each course for its own date."})

        reminder_service.create_personal(users[1]["id"], {
            "title": "Start the COS202 draft",
            "remind_at": clock.to_iso(clock.now() + timedelta(days=1)),
            "event_id": made["assignment"]["id"]})

        # Someone waiting, so the rep's decision queue is not empty.
        pending, _ = auth_service.register({
            "full_name": "Tunde Bakare", "email": "tunde@student.babcock.edu.ng",
            "password": PASSWORD, "confirm_password": PASSWORD,
            "student_id_number": "BU/SEN/0006", **PROFILE})
        execute("UPDATE users SET email_verified = 1 WHERE id = ?", (pending["id"],))
        membership_service.join_or_request(pending["id"], cid)
        print("  1 announcement, 1 reminder, 1 pending membership request")

    print("\nSign in at http://localhost:5173")
    print(f"  rep      ada@student.babcock.edu.ng   /  {PASSWORD}")
    print(f"  student  bola@student.babcock.edu.ng  /  {PASSWORD}")


if __name__ == "__main__":
    main()
