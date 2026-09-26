"""File-backed concurrency harness.

Real threads against a real SQLite file. Every setup step asserts, so a broken
fixture fails loudly instead of being mistaken for a passing race.
"""
import os
import tempfile
import threading

from academicai import clock
from academicai.app import create_app
from academicai.config import TestConfig

DOMAIN = "student.babcock.edu.ng"


def make_file_app(tmp_path, name="conc"):
    handle, path = tempfile.mkstemp(suffix=f"-{name}.db")
    os.close(handle)
    os.unlink(path)

    class Cfg(TestConfig):
        DATABASE_PATH = path
        SQLITE_WAL = True

    app = create_app(Cfg)
    app.config["_TEST_DB_PATH"] = path
    return app, path


def cleanup(path):
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except OSError:
            pass


_counter = {"n": 0}


def make_member(app, department="Software Engineering", level="200",
                academic_session="2026/2027"):
    """Register + verify email + setup + join. Asserts every step."""
    _counter["n"] += 1
    i = _counter["n"]
    client = app.test_client()
    email = f"c{i}@{DOMAIN}"
    name = f"Conc {i}"
    sid = f"BU/SEN/{i:04d}"

    reg = client.post("/api/auth/register", json={
        "full_name": name, "email": email, "password": "Password123",
        "confirm_password": "Password123", "university": "Babcock University",
        "department": department, "level": level,
        "academic_session": academic_session, "student_id_number": sid})
    assert reg.status_code == 201, f"register: {reg.get_json()}"

    ver = client.post("/api/auth/verify-email",
                      json={"email": email, "code": reg.get_json()["verification_code"]})
    assert ver.status_code == 200, f"verify-email: {ver.get_json()}"

    login = client.post("/api/auth/login", json={"email": email, "password": "Password123"})
    assert login.status_code == 200, f"login: {login.get_json()}"
    headers = {"Authorization": f"Bearer {login.get_json()['token']}"}
    user_id = login.get_json()["user"]["id"]

    setup = client.post("/api/community/setup", headers=headers)
    assert setup.status_code in (200, 201), f"setup: {setup.get_json()}"

    join = client.post("/api/community/join", headers=headers)
    assert join.status_code == 201, f"join: {join.get_json()}"
    community_id = join.get_json()["community"]["id"]

    return {"id": user_id, "email": email, "name": name, "headers": headers,
            "client": client, "community_id": community_id,
            "awaiting": join.get_json()["awaiting_approval"]}


def relogin(app, member):
    client = member["client"]
    resp = client.post("/api/auth/login",
                       json={"email": member["email"], "password": "Password123"})
    assert resp.status_code == 200, f"relogin: {resp.get_json()}"
    member["headers"] = {"Authorization": f"Bearer {resp.get_json()['token']}"}
    return member


def relogin_all(app, members):
    """Re-authenticate everyone.

    Sessions expire after SESSION_TTL_HOURS (24h). Any test that advances the
    clock past a ballot deadline also expires every outstanding session, so
    votes would silently 401 and a ballot would close with zero votes - which
    looks like a passing race but proves nothing.
    """
    for member in members:
        relogin(app, member)
    return members


def advance_and_relogin(app, members, delta):
    """Advance the clock, then restore sessions so later calls still work."""
    clock.advance(delta)
    return relogin_all(app, members)


def elect_rep(app, candidate, voters, run_worker_fn):
    """Run a full election so `candidate` becomes a VERIFIED_REP."""
    from datetime import timedelta

    client = candidate["client"]
    resp = client.post("/api/rep/nominate", headers=candidate["headers"],
                       json={"candidate_id": candidate["id"]})
    assert resp.status_code == 201, f"nominate: {resp.get_json()}"
    nomination_id = resp.get_json()["nomination"]["id"]

    for voter in voters:
        vote = voter["client"].post(f"/api/rep/candidates/{nomination_id}/vote",
                                    headers=voter["headers"], json={"vote": "YES"})
        assert vote.status_code == 201, f"vote: {vote.get_json()}"

    clock.advance(timedelta(hours=25))
    run_worker_fn(app)
    relogin_all(app, [candidate] + list(voters))

    check = client.get("/api/community", headers=candidate["headers"])
    assert check.status_code == 200, check.get_json()
    role = check.get_json()["membership"]["role"]
    assert role == "VERIFIED_REP", f"election did not seat the rep: role={role}"
    return nomination_id


def run_worker(app):
    with app.app_context():
        from academicai.worker.jobs import run_once
        return run_once()


def race(*fns, threads_per_fn=1):
    """Run callables concurrently, released together by a barrier."""
    calls = []
    for fn in fns:
        calls.extend([fn] * threads_per_fn)
    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)

    def wrapped(index, fn):
        try:
            barrier.wait(timeout=10)
        except threading.BrokenBarrierError:
            pass
        try:
            results[index] = fn()
        except Exception as exc:  # recorded, never swallowed
            results[index] = f"EXC {type(exc).__name__}: {exc}"

    threads = [threading.Thread(target=wrapped, args=(i, fn))
               for i, fn in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def db(app):
    """A fresh connection for final-state assertions."""
    from academicai.db.connection import connect
    return connect(app.config["_TEST_DB_PATH"], busy_timeout_ms=5000, wal=True)
