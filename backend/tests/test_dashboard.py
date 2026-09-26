"""Dashboard and calendar aggregates (spec 28)."""


def test_student_dashboard_shows_identity_and_upcoming(client, academic_community):
    setup = academic_community()
    data = setup.members[1].get("/api/dashboard").get_json()
    assert data["greeting"].startswith("Welcome back,")
    assert data["community"]["department"] == "Software Engineering"
    assert data["community"]["level"] == "200"
    assert data["community"]["academic_session"] == "2026/2027"
    assert data["community"]["university"] == "Babcock University"
    assert any(e["title"] == "COS202 Assignment" for e in data["upcoming"])
    assert "rep" not in data


def test_rep_dashboard_includes_management_counts(client, academic_community, verified_user):
    setup = academic_community()
    newcomer = verified_user(client)
    newcomer.post("/api/community/setup")
    newcomer.post("/api/community/join")

    data = setup.rep.get("/api/dashboard").get_json()
    assert data["rep"]["rep_count"] == 1
    assert data["rep"]["student_count"] >= 4
    assert data["rep"]["course_count"] == 4
    assert [r["user_id"] for r in data["rep"]["pending_requests"]] == [newcomer.user_id]


def test_dashboard_shows_recent_changes(client, academic_community):
    setup = academic_community()
    setup.rep.put(f"/api/events/{setup.cos202_assignment['id']}",
                  json={"event_date": "2026-09-21"})
    data = setup.members[1].get("/api/dashboard").get_json()
    assert any(c["change_type"] == "DEADLINE_CHANGED" for c in data["recent_changes"])


def test_calendar_returns_events_and_timetable(client, academic_community):
    setup = academic_community()
    data = setup.members[1].get("/api/calendar").get_json()
    assert any(e["title"] == "COS202 Assignment" for e in data["events"])
    assert any(t["day_of_week"] == "WEDNESDAY" for t in data["timetable"])


def test_dashboard_requires_active_membership(client, verified_user):
    actor = verified_user(client)
    assert actor.get("/api/dashboard").status_code == 403
