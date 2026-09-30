"""The same database behaviour on SQLite and on PostgreSQL.

Every test here runs twice, once per engine, against the application's own
helpers (connection.py) - the only way the application reaches its database.
The PostgreSQL run needs ACADEMICAI_TEST_POSTGRES_URL and is skipped, and
reported as skipped, without it.
"""
import pytest

from academicai.db.connection import (insert_returning_id, query_all, query_one,
                                      transaction)
from academicai.services import event_service, notification_service
from tests import pg_support
from tests.pg_support import INTEGRITY_ERRORS


@pytest.fixture(params=["sqlite", pytest.param("postgresql", marks=pytest.mark.postgres)])
def db_app(request, tmp_path):
    if request.param == "sqlite":
        from academicai.app import create_test_app
        app = create_test_app(DATABASE_BACKEND="sqlite", DATABASE_PATH=":memory:",
                              UPLOAD_DIR=str(tmp_path / "uploads"))
        yield app
        app.config["_SHARED_MEMORY_CONN"].close()
    else:
        url = request.getfixturevalue("pg_schema")
        yield pg_support.make_pg_app(url, UPLOAD_DIR=str(tmp_path / "uploads"))


def _user(n=1):
    return insert_returning_id(
        """INSERT INTO users (full_name, email, password_hash, created_at, updated_at)
           VALUES (?, ?, 'x', '2026-09-14T09:00:00Z', '2026-09-14T09:00:00Z')""",
        (f"Person {n}", f"person{n}@student.babcock.edu.ng"))


def _community(university_id=None):
    if university_id is None:
        university_id = query_one("SELECT MIN(id) AS id FROM universities")["id"]
    return insert_returning_id(
        """INSERT INTO academic_communities
           (university_id, department, level, academic_session, status, created_at, updated_at)
           VALUES (?, 'Software Engineering', '200', '2026/2027', 'ACTIVE',
                   '2026-09-14T09:00:00Z', '2026-09-14T09:00:00Z')""",
        (university_id,))


# ── Generated ids ───────────────────────────────────────────────────────────

def test_insert_returning_id_gives_each_new_row_its_id(db_app):
    with db_app.app_context():
        first, second = _user(1), _user(2)
        assert isinstance(first, int) and second == first + 1
        assert query_one("SELECT email FROM users WHERE id = ?", (second,))["email"] == \
            "person2@student.babcock.edu.ng"
        with transaction() as conn:
            third = insert_returning_id(
                "INSERT INTO users (full_name, email, password_hash, created_at, updated_at) "
                "VALUES ('P3', 'p3@x', 'x', 'now', 'now')", conn=conn)
        assert third == second + 1


# ── Rows ────────────────────────────────────────────────────────────────────

def test_rows_are_read_by_name_position_and_as_a_mapping(db_app):
    with db_app.app_context():
        row = query_one("SELECT id, name, timezone FROM universities WHERE name = ?",
                        ("Babcock University",))
        assert row["name"] == row["NAME"] == row[1] == "Babcock University"
        assert row.keys() == ["id", "name", "timezone"]
        assert dict(row) == {"id": row[0], "name": "Babcock University",
                             "timezone": "Africa/Lagos"}
        assert list(row) == [row["id"], "Babcock University", "Africa/Lagos"]
        assert len(row) == 3
        with pytest.raises(IndexError):
            row["missing"]
        # Two columns of one name: the first wins, as with sqlite3.Row.
        twice = query_one("SELECT 1 AS n, 2 AS n")
        assert twice["n"] == 1 and list(twice) == [1, 2]
        assert query_one("SELECT id FROM universities WHERE name = ?", ("Nowhere",)) is None
        assert query_all("SELECT id FROM universities WHERE name = ?", ("Nowhere",)) == []


# ── Literal % and ? ─────────────────────────────────────────────────────────

def test_literal_percent_and_question_marks_survive(db_app):
    with db_app.app_context():
        row = query_one("SELECT ? AS value, 'a%b' AS literal, '?' AS mark", ("50%? off",))
        assert (row["value"], row["literal"], row["mark"]) == ("50%? off", "a%b", "?")
        assert query_one("SELECT '100%' AS v")["v"] == "100%"             # no parameters
        n = query_one("SELECT COUNT(*) AS n FROM universities "
                      "WHERE name LIKE '%University%' AND id > ?", (0,))["n"]
        assert n == 4


# ── Transactions ────────────────────────────────────────────────────────────

def test_a_failed_transaction_leaves_nothing_behind(db_app):
    with db_app.app_context():
        with pytest.raises(RuntimeError):
            with transaction():
                _user(1)
                raise RuntimeError("boom")
        assert query_one("SELECT COUNT(*) AS n FROM users")["n"] == 0


def test_an_inner_transaction_joins_the_outer_one(db_app):
    with db_app.app_context():
        with pytest.raises(RuntimeError):
            with transaction() as outer:
                _user(1)
                with transaction() as inner:
                    assert inner is outer and inner.in_transaction
                    _user(2)
                # The inner block ending does not commit: the outer one decides.
                raise RuntimeError("outer fails after the inner block finished")
        assert query_one("SELECT COUNT(*) AS n FROM users")["n"] == 0

        with transaction():
            _user(3)
            with transaction():
                _user(4)
        assert query_one("SELECT COUNT(*) AS n FROM users")["n"] == 2


def test_a_constraint_failure_rolls_back_the_whole_transaction(db_app):
    with db_app.app_context():
        with pytest.raises(INTEGRITY_ERRORS):
            with transaction():
                _user(1)
                _user(1)                       # same email: UNIQUE
        assert query_one("SELECT COUNT(*) AS n FROM users")["n"] == 0
        _user(1)                               # and the connection is still usable
        assert query_one("SELECT COUNT(*) AS n FROM users")["n"] == 1


# ── Constraints ─────────────────────────────────────────────────────────────

def test_one_active_membership_per_user_is_enforced_by_the_database(db_app):
    with db_app.app_context():
        user = _user()
        first, second = _community(), None
        other_uni = query_one("SELECT MAX(id) AS id FROM universities")["id"]
        second = _community(other_uni)

        def join(community_id, status):
            return insert_returning_id(
                """INSERT INTO community_members (community_id, user_id, status, requested_at)
                   VALUES (?, ?, ?, 'now')""", (community_id, user, status))

        membership = join(first, "ACTIVE")
        with pytest.raises(INTEGRITY_ERRORS):
            join(second, "ACTIVE")
        # Any number of non-active rows is fine: a transfer's destination waits
        # as PENDING_APPROVAL while the old membership is still ACTIVE.
        pending = join(second, "PENDING_APPROVAL")
        with transaction() as conn:
            conn.execute("UPDATE community_members SET status = 'ENDED' WHERE id = ?",
                         (membership,))
            conn.execute("UPDATE community_members SET status = 'ACTIVE' WHERE id = ?",
                         (pending,))
        rows = query_all("SELECT community_id, status FROM community_members "
                         "WHERE user_id = ? ORDER BY id", (user,))
        assert [tuple(r) for r in rows] == [(first, "ENDED"), (second, "ACTIVE")]


@pytest.mark.parametrize("sql", [
    "UPDATE academic_communities SET status = 'CLOSED'",
    "UPDATE universities SET name = NULL",
    "UPDATE users SET identity_status = 'MAYBE'",
])
def test_check_and_not_null_constraints_are_enforced(db_app, sql):
    with db_app.app_context():
        _user()
        _community()
        with pytest.raises(INTEGRITY_ERRORS):
            with transaction() as conn:
                conn.execute(sql)


def test_foreign_keys_are_enforced(db_app):
    with db_app.app_context():
        with pytest.raises(INTEGRITY_ERRORS):
            _community(university_id=987654)


# ── Notification de-duplication ─────────────────────────────────────────────

def test_a_duplicate_notification_is_skipped_and_the_transaction_carries_on(db_app):
    with db_app.app_context():
        user = _user()
        with transaction() as conn:
            assert notification_service.enqueue([user], None, "S", "B",
                                                dedupe_key="k", conn=conn) == 1
            assert notification_service.enqueue([user], None, "S", "B",
                                                dedupe_key="k", conn=conn) == 0
            # PostgreSQL aborts a whole transaction on any error, so the old
            # catch-the-IntegrityError approach would have failed right here.
            assert notification_service.enqueue([user], None, "S2", "B2",
                                                dedupe_key="k2", conn=conn) == 1
        keys = [r["dedupe_key"] for r in
                query_all("SELECT dedupe_key FROM notifications ORDER BY id")]
        assert keys == [f"k:u{user}", f"k2:u{user}"]


def test_a_notification_without_a_key_is_never_deduplicated(db_app):
    with db_app.app_context():
        user = _user()
        for _ in range(2):
            assert notification_service.enqueue([user], None, "S", "B") == 1
        assert query_one("SELECT COUNT(*) AS n FROM notifications")["n"] == 2


def test_an_unrelated_failure_while_queueing_is_not_swallowed(db_app):
    with db_app.app_context():
        user = _user()
        with pytest.raises(INTEGRITY_ERRORS):          # no such user: a real error
            with transaction() as conn:
                notification_service.enqueue([user], None, "S", "B", dedupe_key="a",
                                             conn=conn)
                notification_service.enqueue([424242], None, "S", "B", dedupe_key="b",
                                             conn=conn)
        assert query_one("SELECT COUNT(*) AS n FROM notifications")["n"] == 0
        with pytest.raises(INTEGRITY_ERRORS):          # NOT NULL subject
            notification_service.enqueue([user], None, None, "B", dedupe_key="c")


# ── Ordering ────────────────────────────────────────────────────────────────

def test_events_are_listed_by_date_then_untimed_first_then_time_undated_last(db_app):
    with db_app.app_context():
        user, community = _user(), _community()
        for title, day, time in [("A", "2026-10-02", "14:00"), ("B", "2026-10-01", None),
                                 ("C", None, "09:00"), ("D", "2026-10-01", "08:00"),
                                 ("E", None, None), ("F", "2026-10-02", None),
                                 ("G", "2026-10-01", "08:00")]:
            insert_returning_id(
                """INSERT INTO academic_events
                   (community_id, event_type, title, event_date, event_time,
                    created_by, created_at, updated_at)
                   VALUES (?, 'ASSIGNMENT', ?, ?, ?, ?, 'now', 'now')""",
                (community, title, day, time, user))
        titles = [e["title"] for e in event_service.list_events(community)]
        assert titles == ["B", "D", "G", "F", "A", "E", "C"]
