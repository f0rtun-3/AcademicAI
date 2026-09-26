"""Shared test fixtures.

Helpers build real users through the real HTTP API rather than inserting rows,
so every test exercises the same gates production traffic does.
"""
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from academicai import clock  # noqa: E402
from academicai.app import create_test_app  # noqa: E402
from academicai.security import rate_limit  # noqa: E402
from academicai.services import email_service  # noqa: E402

BASE_TIME = datetime(2026, 9, 14, 9, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_state():
    clock.freeze(BASE_TIME)
    email_service.clear()
    email_service.set_failure_hook(None)
    rate_limit.reset()
    yield
    clock.reset()
    email_service.set_failure_hook(None)


@pytest.fixture
def app(tmp_path):
    # Supporting material is written to disk, so every test gets its own
    # directory. Nothing in the suite may touch instance/uploads.
    application = create_test_app(UPLOAD_DIR=str(tmp_path / "uploads"))
    yield application
    conn = application.config.get("_SHARED_MEMORY_CONN")
    if conn is not None:
        conn.close()


@pytest.fixture
def client(app):
    return app.test_client()


class Actor:
    """A registered user plus the helpers a test needs to act as them."""

    def __init__(self, client, user_id, email, token, full_name):
        self.client = client
        self.user_id = user_id
        self.email = email
        self.token = token
        self.full_name = full_name
        self.community_id = None

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path, **kw):
        return self.client.get(path, headers=self.headers, **kw)

    def post(self, path, json=None, **kw):
        # A file upload is multipart, not JSON. Werkzeug refuses both at once,
        # so an explicit `data=` wins and the empty-JSON default is skipped.
        if "data" in kw:
            return self.client.post(path, headers=self.headers, **kw)
        return self.client.post(path, json=json if json is not None else {},
                                headers=self.headers, **kw)

    def put(self, path, json=None, **kw):
        return self.client.put(path, json=json if json is not None else {},
                               headers=self.headers, **kw)

    def delete(self, path, **kw):
        return self.client.delete(path, headers=self.headers, **kw)

    def relogin(self):
        resp = self.client.post("/api/auth/login",
                                json={"email": self.email, "password": "Password123"})
        assert resp.status_code == 200, resp.get_json()
        self.token = resp.get_json()["token"]
        return self


DEFAULT_PROFILE = {
    "university": "Babcock University",
    "department": "Software Engineering",
    "level": "200",
    "academic_session": "2026/2027",
}

# Mirrors the backend registry (db/reference_data.py). Tests that select a
# university get a matching approved email domain automatically.
APPROVED_DOMAINS = {
    "Babcock University": "student.babcock.edu.ng",
    "University of Ibadan": "stu.ui.edu.ng",
    "University of Lagos": "unilag.edu.ng",
    "Covenant University": "stu.cu.edu.ng",
}


@pytest.fixture
def register():
    """Register a user. Returns an Actor with no email verification yet."""
    counter = {"n": 0}

    def _register(client, name=None, email=None, **profile):
        counter["n"] += 1
        n = counter["n"]
        name = name or f"Student {n}"
        payload = dict(DEFAULT_PROFILE)
        payload.update(profile)
        # The email domain must be one approved for the selected university
        # (Gate 1), so derive it rather than hard-coding one.
        if email is None:
            domain = APPROVED_DOMAINS[payload["university"]]
            email = f"student{n}@{domain}"
        payload.update({
            "full_name": name,
            "email": email,
            "password": "Password123",
            "confirm_password": "Password123",
            "student_id_number": payload.get("student_id_number", f"BU/SEN/{n:04d}"),
        })
        resp = client.post("/api/auth/register", json=payload)
        assert resp.status_code == 201, resp.get_json()
        data = resp.get_json()
        actor = Actor(client, data["user"]["id"], email, None, name)
        actor.otp = data["verification_code"]
        actor.profile = payload
        return actor

    return _register


@pytest.fixture
def verified_user(register):
    """Register + verify email + log in. Still has NO membership.

    "Verified" here means the account gate only: the email address is
    confirmed and sits on an approved institutional domain. Student ID-card
    verification is out of MVP scope, so there is no second account gate, and
    this fixture must not be read as establishing who the student is.
    """

    def _verified(client, **kwargs):
        actor = register(client, **kwargs)
        resp = client.post("/api/auth/verify-email", json={"email": actor.email, "code": actor.otp})
        assert resp.status_code == 200, resp.get_json()
        resp = client.post("/api/auth/login",
                           json={"email": actor.email, "password": "Password123"})
        assert resp.status_code == 200, resp.get_json()
        actor.token = resp.get_json()["token"]
        # Email verification alone grants nothing beyond the gate itself.
        assert resp.get_json()["user"]["email_verified"] is True
        return actor

    return _verified


@pytest.fixture
def joined_user(verified_user):
    """A verified student who has joined (or requested to join) their community."""

    def _joined(client, **kwargs):
        actor = verified_user(client, **kwargs)
        resp = actor.post("/api/community/setup")
        assert resp.status_code in (200, 201), resp.get_json()
        resp = actor.post("/api/community/join")
        assert resp.status_code == 201, resp.get_json()
        data = resp.get_json()
        actor.community_id = data["community"]["id"]
        actor.awaiting_approval = data["awaiting_approval"]
        return actor

    return _joined


@pytest.fixture
def community(joined_user):
    """N eligible students all auto-joined to the same PENDING community."""

    def _community(client, size=4, **profile):
        return [joined_user(client, **profile) for _ in range(size)]

    return _community


@pytest.fixture
def elect_rep():
    """Run a full verification ballot and return the elected rep.

    Note the arithmetic: the candidate may not vote, and a ballot needs 3 actual
    votes, so a community needs at least 4 eligible members to elect anyone.
    """

    def _elect(client, members, candidate=None, votes=None):
        candidate = candidate or members[0]
        voters = [m for m in members if m.user_id != candidate.user_id]
        resp = candidate.post("/api/rep/nominate", json={"candidate_id": candidate.user_id})
        assert resp.status_code == 201, resp.get_json()
        nomination_id = resp.get_json()["nomination"]["id"]
        ballots = votes or ["YES"] * 3
        for voter, vote in zip(voters, ballots):
            r = voter.post(f"/api/rep/candidates/{nomination_id}/vote", json={"vote": vote})
            assert r.status_code == 201, r.get_json()
        return nomination_id

    return _elect


@pytest.fixture
def run_worker(app):
    """Run every background job once, inside an app context."""

    def _run():
        from academicai.worker.jobs import run_once
        with app.app_context():
            return run_once()

    return _run


@pytest.fixture
def rep_community(client, community, elect_rep, run_worker):
    """A community that has completed its first election.

    Returns (rep, members). The community is ACTIVE and `rep` holds authority.
    """

    def _build(size=4, **profile):
        members = community(client, size=size, **profile)
        nomination_id = elect_rep(client, members)
        from datetime import timedelta
        clock.advance(timedelta(hours=25))
        run_worker()
        rep = members[0]
        for m in members:
            m.relogin()
        return rep, members

    return _build


@pytest.fixture
def academic_community(client, rep_community):
    """A rep-led ACTIVE community pre-loaded with courses, timetable and events.

    Mirrors the scenario the spec's AI examples assume.
    """

    class Setup:
        pass

    def _build(size=4, seed_events=True, **profile):
        rep, members = rep_community(size=size, **profile)
        setup = Setup()
        setup.rep = rep
        setup.members = members
        setup.community_id = rep.community_id

        setup.courses = {}
        for code, title in (("COS202", "Data Structures"),
                            ("SEN212", "Software Requirements"),
                            ("PHL101", "Philosophy"),
                            ("GEDS201", "Adventist Heritage")):
            resp = rep.post("/api/community/courses", json={"code": code, "title": title})
            assert resp.status_code == 201, resp.get_json()
            setup.courses[code] = resp.get_json()["course"]["id"]

        # Every member enrols in COS202 so course-scoped notifications have targets.
        for member in members:
            member.post(f"/api/community/courses/{setup.courses['COS202']}/enroll")

        resp = rep.post("/api/community/timetable", json={
            "course_id": setup.courses["PHL101"], "title": "Philosophy",
            "day_of_week": "THURSDAY", "start_time": "10:00", "venue": "B007"})
        assert resp.status_code == 201, resp.get_json()
        setup.philosophy_entry = resp.get_json()["timetable_entry"]["id"]

        resp = rep.post("/api/community/timetable", json={
            "course_id": setup.courses["COS202"], "title": "Data Structures",
            "day_of_week": "WEDNESDAY", "start_time": "08:00", "venue": "LT1"})
        assert resp.status_code == 201, resp.get_json()
        setup.cos202_class = resp.get_json()["timetable_entry"]["id"]

        setup.cos202_assignment = None
        setup.heritage_event = None
        if seed_events:
            resp = rep.post("/api/events", json={
                "title": "COS202 Assignment", "event_type": "ASSIGNMENT",
                "course_id": setup.courses["COS202"], "event_date": "2026-09-18"})
            assert resp.status_code == 201, resp.get_json()
            setup.cos202_assignment = resp.get_json()["event"]

            resp = rep.post("/api/events", json={
                "title": "Adventist Heritage Seminar", "event_type": "PRESENTATION",
                "course_id": setup.courses["GEDS201"], "event_date": "2026-09-23",
                "venue": "B007"})
            assert resp.status_code == 201, resp.get_json()
            setup.heritage_event = resp.get_json()["event"]

        return setup

    return _build


def analyze(actor, message, **kwargs):
    payload = {"message": message}
    payload.update(kwargs)
    resp = actor.post("/api/ai/analyze-message", json=payload)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["proposal"]


@pytest.fixture
def unverified_email_member(client, register, app):
    """A community member whose email is no longer verified.

    This replaces the old needs_review_member fixture. With ID-card
    verification out of MVP scope, the email gate is the account gate, so THIS
    is the boundary worth proving: an account that stops being email-verified
    must lose access to protected community data on the very next request,
    even though its membership row is still ACTIVE.

    Production reaches this state through a change of email address; the
    fixture writes the column directly so the test does not depend on that
    flow's other side effects.
    """

    def _build(member):
        with app.app_context():
            from academicai import clock
            from academicai.db.connection import execute, transaction
            with transaction() as conn:
                execute("UPDATE users SET email_verified = 0, updated_at = ? "
                        "WHERE id = ?", (clock.now_iso(), member.user_id), conn=conn)
        return member

    return _build


def seed_rep_community_over_http(app):
    """Build a rep-led community on a file-backed app, through the real API.

    Returns (rep_headers, rep_user_id, community_id). Used by tests that need
    real threads, where the shared in-memory connection cannot be used.
    """
    from datetime import timedelta

    client = app.test_client()
    actors = []
    for i in range(4):
        email = f"race{i}@student.babcock.edu.ng"
        resp = client.post("/api/auth/register", json={
            "full_name": f"Race Student {i}", "email": email,
            "password": "Password123", "confirm_password": "Password123",
            "university": "Babcock University", "department": "Software Engineering",
            "level": "200", "academic_session": "2026/2027",
            "student_id_number": f"BU/SEN/{i:04d}"})
        client.post("/api/auth/verify-email",
                    json={"email": email, "code": resp.get_json()["verification_code"]})
        session = client.post("/api/auth/login",
                              json={"email": email, "password": "Password123"}).get_json()
        headers = {"Authorization": f"Bearer {session['token']}"}
        client.post("/api/community/setup", headers=headers)
        client.post("/api/community/join", headers=headers)
        actors.append({"email": email, "id": session["user"]["id"], "headers": headers})

    nomination = client.post("/api/rep/nominate", json={"candidate_id": actors[0]["id"]},
                             headers=actors[0]["headers"]).get_json()["nomination"]["id"]
    for actor in actors[1:]:
        client.post(f"/api/rep/candidates/{nomination}/vote", json={"vote": "YES"},
                    headers=actor["headers"])

    clock.advance(timedelta(hours=25))
    with app.app_context():
        from academicai.worker.jobs import run_once
        run_once()

    session = client.post("/api/auth/login",
                          json={"email": actors[0]["email"],
                                "password": "Password123"}).get_json()
    headers = {"Authorization": f"Bearer {session['token']}"}
    community_id = client.get("/api/community",
                              headers=headers).get_json()["community"]["id"]
    return headers, actors[0]["id"], community_id
