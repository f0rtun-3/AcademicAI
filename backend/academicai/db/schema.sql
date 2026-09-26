-- AcademicAI schema (SQLite dialect).
-- Portability note: this file is the ONLY place SQLite-specific DDL lives.
-- Application SQL stays standard so a PostgreSQL schema can replace this file.
-- Timestamps are ISO-8601 UTC strings. Dates are YYYY-MM-DD. Times are HH:MM.

CREATE TABLE IF NOT EXISTS users (
    id                INTEGER PRIMARY KEY,
    full_name         TEXT NOT NULL,
    email             TEXT NOT NULL UNIQUE,
    password_hash     TEXT NOT NULL,
    email_verified    INTEGER NOT NULL DEFAULT 0,
    -- 'OTP' when a code was entered, 'SKIPPED_NO_VERIFICATION' when the
    -- deployment had email verification switched off. Keeps email_verified
    -- from meaning two different things at once.
    email_verification_method TEXT,
    -- LEGACY, UNREAD. Student ID-card verification was removed from the MVP;
    -- no application code reads this column any more and nothing can change it
    -- from its default. It is kept rather than dropped because the schema
    -- migrator only ADDs columns, so removing it would mean rebuilding this
    -- table on live databases for no functional gain. Historical rows may
    -- still say VERIFIED/REJECTED/NEEDS_REVIEW; those values now mean nothing
    -- and must NOT be treated as a gate. See security/authz.py.
    identity_status   TEXT NOT NULL DEFAULT 'UNVERIFIED'
                      CHECK (identity_status IN ('UNVERIFIED','NEEDS_REVIEW','VERIFIED','REJECTED')),
    token_epoch       INTEGER NOT NULL DEFAULT 1,
    -- Declared academic profile, captured at registration (spec 7) and updated on
    -- transfer (spec 10). This is the student's claim; it is NOT membership.
    university_id     INTEGER REFERENCES universities(id),
    department        TEXT,
    level             TEXT,
    academic_session  TEXT,
    -- The student's own declared Matric Number. PROFILE DATA ONLY: it used to
    -- be the account-side value an ID card was compared against, and with
    -- ID-card verification out of MVP scope nothing checks it against
    -- anything. It is kept because the student owns it and it belongs on
    -- their record; it is not evidence and grants nothing.
    student_id_number TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS universities (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL
);

-- A community is uniquely identified by university + department + level + session (spec 4).
-- Approved institutional/student email domains per university.
--
-- Registering requires the email's domain to be an ACTIVE domain of the
-- SELECTED university. This is an additional identity signal: it shows the
-- registrant controls an address on an approved institution domain. It is not
-- proof of current enrolment, and it is separate from the ID-card check.
--
-- A domain is deactivated rather than deleted so historical configuration
-- survives; `active` is what the lookup filters on.
CREATE TABLE IF NOT EXISTS university_email_domains (
    id              INTEGER PRIMARY KEY,
    university_id   INTEGER NOT NULL REFERENCES universities(id),
    -- Stored lowercase with no leading '@'. Unique across all universities, so
    -- one domain can never be claimed by two institutions.
    domain          TEXT NOT NULL UNIQUE,
    domain_type     TEXT NOT NULL DEFAULT 'STUDENT'
                    CHECK (domain_type IN ('STUDENT', 'INSTITUTIONAL')),
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    deactivated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_uni_domains_lookup
    ON university_email_domains(domain, active);
CREATE INDEX IF NOT EXISTS idx_uni_domains_university
    ON university_email_domains(university_id, active);

CREATE TABLE IF NOT EXISTS academic_communities (
    id                INTEGER PRIMARY KEY,
    university_id     INTEGER NOT NULL REFERENCES universities(id),
    department        TEXT NOT NULL,
    level             TEXT NOT NULL,
    academic_session  TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'PENDING'
                      CHECK (status IN ('PENDING','ACTIVE','ARCHIVED')),
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE (university_id, department, level, academic_session)
);

-- Membership requests are represented as rows in PENDING_APPROVAL status rather than
-- a separate table (spec 26: do not add tables merely for abstraction aesthetics).
CREATE TABLE IF NOT EXISTS community_members (
    id            INTEGER PRIMARY KEY,
    community_id  INTEGER NOT NULL REFERENCES academic_communities(id),
    user_id       INTEGER NOT NULL REFERENCES users(id),
    role          TEXT NOT NULL DEFAULT 'STUDENT'
                  CHECK (role IN ('STUDENT','VERIFIED_REP')),
    status        TEXT NOT NULL DEFAULT 'PENDING_APPROVAL'
                  CHECK (status IN ('PENDING_APPROVAL','ACTIVE','REJECTED','ENDED')),
    requested_at  TEXT NOT NULL,
    approved_by   INTEGER REFERENCES users(id),
    approved_at   TEXT,
    ended_at      TEXT,
    rep_since     TEXT,
    UNIQUE (community_id, user_id)
);
-- At most one ACTIVE membership per user, enforced by the database rather than
-- by application code alone. During a transfer the destination row is
-- PENDING_APPROVAL, so the rule is never in tension with the transfer flow
-- (spec 10): the old membership ends in the same transaction that activates
-- the new one, and must end first.
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_membership_per_user
    ON community_members(user_id) WHERE status = 'ACTIVE';
CREATE INDEX IF NOT EXISTS idx_members_community ON community_members(community_id, status);
CREATE INDEX IF NOT EXISTS idx_members_user ON community_members(user_id, status);

-- LEGACY, UNWRITTEN. This table recorded student ID-card verification
-- attempts. That feature was removed from the MVP, so nothing inserts into it
-- or reads from it any more, and no route exposes it (a test asserts that).
-- It is kept so existing databases and their audit history are not destroyed;
-- it holds decisions and non-sensitive metadata only - never held an image.
CREATE TABLE IF NOT EXISTS identity_verifications (
    id             INTEGER PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    status         TEXT NOT NULL
                   CHECK (status IN ('NEEDS_REVIEW','VERIFIED','REJECTED')),
    -- Which provider decided, and whether it checks a real source of truth.
    provider       TEXT,
    authoritative  INTEGER NOT NULL DEFAULT 0,
    -- Shape of the evidence that was seen, for audit. Not the evidence itself.
    evidence_format TEXT,
    evidence_width  INTEGER,
    evidence_height INTEGER,
    evidence_bytes  INTEGER,
    -- When the temporary image was destroyed.
    evidence_deleted_at TEXT,
    submitted_at   TEXT NOT NULL,
    reviewed_at    TEXT,
    reviewer_note  TEXT
);
CREATE INDEX IF NOT EXISTS idx_identity_user ON identity_verifications(user_id);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    token_hash  TEXT NOT NULL UNIQUE,
    token_epoch INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    revoked_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

-- Email verification codes. `token_hash` holds the KEYED digest of a six-digit
-- code (HMAC over code_salt + user_id, keyed with SECRET_KEY) rather than a
-- plain hash of a long token - a six-digit value has too small a space for a
-- bare digest to be anything but plaintext. `attempts` counts wrong guesses
-- against this specific code; the row is spent when it reaches the ceiling.
CREATE TABLE IF NOT EXISTS email_verification_tokens (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    token_hash  TEXT NOT NULL UNIQUE,
    code_salt   TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    expires_at  TEXT NOT NULL,
    used_at     TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  TEXT NOT NULL,
    used_at     TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    id            INTEGER PRIMARY KEY,
    community_id  INTEGER NOT NULL REFERENCES academic_communities(id),
    code          TEXT NOT NULL,
    title         TEXT,
    status        TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','REMOVED')),
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE (community_id, code)
);

-- Not every community member is enrolled in every course (spec 24).
CREATE TABLE IF NOT EXISTS course_enrollments (
    id          INTEGER PRIMARY KEY,
    course_id   INTEGER NOT NULL REFERENCES courses(id),
    user_id     INTEGER NOT NULL REFERENCES users(id),
    status      TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','DROPPED')),
    created_at  TEXT NOT NULL,
    UNIQUE (course_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_enrollments_course ON course_enrollments(course_id, status);

CREATE TABLE IF NOT EXISTS timetable_entries (
    id            INTEGER PRIMARY KEY,
    community_id  INTEGER NOT NULL REFERENCES academic_communities(id),
    course_id     INTEGER REFERENCES courses(id),
    title         TEXT,
    day_of_week   TEXT NOT NULL
                  CHECK (day_of_week IN ('MONDAY','TUESDAY','WEDNESDAY','THURSDAY','FRIDAY','SATURDAY','SUNDAY')),
    start_time    TEXT,
    end_time      TEXT,
    venue         TEXT,
    status        TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','CANCELLED')),
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_timetable_community ON timetable_entries(community_id, status);

CREATE TABLE IF NOT EXISTS academic_events (
    id              INTEGER PRIMARY KEY,
    community_id    INTEGER NOT NULL REFERENCES academic_communities(id),
    course_id       INTEGER REFERENCES courses(id),
    event_type      TEXT NOT NULL
                    CHECK (event_type IN ('ASSIGNMENT','PROJECT','QUIZ','TEST','PRESENTATION','EXAM','CLASS','OTHER')),
    title           TEXT NOT NULL,
    -- The instructions a rep typed: what the work actually is. Optional, like
    -- every other descriptive field here - an event created from a one-line
    -- WhatsApp message legitimately has none.
    description     TEXT,
    -- NULL means explicitly unspecified; that is not an AI failure (spec 14).
    event_date      TEXT,
    event_time      TEXT,
    venue           TEXT,
    priority        TEXT NOT NULL DEFAULT 'NORMAL' CHECK (priority IN ('LOW','NORMAL','HIGH')),
    status          TEXT NOT NULL DEFAULT 'SCHEDULED'
                    CHECK (status IN ('SCHEDULED','CANCELLED','RESCHEDULED')),
    original_message TEXT,
    version         INTEGER NOT NULL DEFAULT 1,
    created_by      INTEGER NOT NULL REFERENCES users(id),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_community ON academic_events(community_id, status);
CREATE INDEX IF NOT EXISTS idx_events_course ON academic_events(course_id);

-- Supporting material for an event: the ORIGINAL assignment or project brief,
-- when the lecturer gave one as a file. It never replaces the structured
-- record - the record is what is searchable, dated and remindable; the file is
-- what stops a student hunting through WhatsApp for the exact paper.
--
-- ZERO attachments is the normal case and must stay valid: nothing here is
-- required by academic_events, the relationship is one-to-many from the event
-- side only, and an event with no rows in this table is complete.
--
-- `storage_key` is generated by the application and is the ONLY thing used to
-- locate the bytes on disk. `original_name` is display text and is never used
-- to build a path, because a filename is user input.
CREATE TABLE IF NOT EXISTS event_attachments (
    id             INTEGER PRIMARY KEY,
    event_id       INTEGER NOT NULL REFERENCES academic_events(id),
    storage_key    TEXT NOT NULL UNIQUE,
    original_name  TEXT NOT NULL,
    content_type   TEXT NOT NULL,
    byte_size      INTEGER NOT NULL,
    checksum       TEXT,
    -- A removal keeps the row and deletes the bytes: the academic record
    -- should still say that material was published and then withdrawn.
    status         TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','REMOVED')),
    uploaded_by    INTEGER NOT NULL REFERENCES users(id),
    created_at     TEXT NOT NULL,
    removed_by     INTEGER REFERENCES users(id),
    removed_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_attachments_event ON event_attachments(event_id, status);

CREATE TABLE IF NOT EXISTS announcements (
    id               INTEGER PRIMARY KEY,
    community_id     INTEGER NOT NULL REFERENCES academic_communities(id),
    title            TEXT NOT NULL,
    body             TEXT NOT NULL,
    original_message TEXT,
    status           TEXT NOT NULL DEFAULT 'PUBLISHED' CHECK (status IN ('PUBLISHED','WITHDRAWN')),
    version          INTEGER NOT NULL DEFAULT 1,
    created_by       INTEGER NOT NULL REFERENCES users(id),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_announcements_community ON announcements(community_id, status);

-- Rep verification ballot (spec 11).
CREATE TABLE IF NOT EXISTS rep_nominations (
    id            INTEGER PRIMARY KEY,
    community_id  INTEGER NOT NULL REFERENCES academic_communities(id),
    user_id       INTEGER NOT NULL REFERENCES users(id),
    nominated_by  INTEGER NOT NULL REFERENCES users(id),
    status        TEXT NOT NULL DEFAULT 'OPEN'
                  CHECK (status IN ('OPEN','PASSED','FAILED','CANCELLED')),
    opened_at     TEXT NOT NULL,
    closes_at     TEXT NOT NULL,
    resolved_at   TEXT,
    yes_votes     INTEGER,
    no_votes      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_nominations_open ON rep_nominations(status, closes_at);
CREATE INDEX IF NOT EXISTS idx_nominations_community ON rep_nominations(community_id, user_id);

CREATE TABLE IF NOT EXISTS rep_verification_votes (
    id             INTEGER PRIMARY KEY,
    nomination_id  INTEGER NOT NULL REFERENCES rep_nominations(id),
    voter_id       INTEGER NOT NULL REFERENCES users(id),
    vote           TEXT NOT NULL CHECK (vote IN ('YES','NO')),
    created_at     TEXT NOT NULL,
    UNIQUE (nomination_id, voter_id)
);

-- Rep removal ballot (spec 12).
CREATE TABLE IF NOT EXISTS rep_removals (
    id              INTEGER PRIMARY KEY,
    community_id    INTEGER NOT NULL REFERENCES academic_communities(id),
    target_user_id  INTEGER NOT NULL REFERENCES users(id),
    initiated_by    INTEGER NOT NULL REFERENCES users(id),
    status          TEXT NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN','PASSED','FAILED')),
    opened_at       TEXT NOT NULL,
    closes_at       TEXT NOT NULL,
    resolved_at     TEXT,
    yes_votes       INTEGER,
    no_votes        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_removals_open ON rep_removals(status, closes_at);
CREATE INDEX IF NOT EXISTS idx_removals_target ON rep_removals(community_id, target_user_id);

CREATE TABLE IF NOT EXISTS rep_removal_votes (
    id          INTEGER PRIMARY KEY,
    removal_id  INTEGER NOT NULL REFERENCES rep_removals(id),
    voter_id    INTEGER NOT NULL REFERENCES users(id),
    vote        TEXT NOT NULL CHECK (vote IN ('YES','NO')),
    created_at  TEXT NOT NULL,
    UNIQUE (removal_id, voter_id)
);

CREATE TABLE IF NOT EXISTS academic_calendars (
    id             INTEGER PRIMARY KEY,
    community_id   INTEGER NOT NULL REFERENCES academic_communities(id),
    uploaded_by    INTEGER NOT NULL REFERENCES users(id),
    raw_text       TEXT NOT NULL,
    session_start  TEXT,
    session_end    TEXT,
    extracted      TEXT,
    created_at     TEXT NOT NULL
);

-- Current record is current state; history preserves transitions (spec 18).
CREATE TABLE IF NOT EXISTS change_history (
    id              INTEGER PRIMARY KEY,
    community_id    INTEGER NOT NULL REFERENCES academic_communities(id),
    entity_type     TEXT NOT NULL,
    entity_id       INTEGER NOT NULL,
    change_type     TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    actor_id        INTEGER REFERENCES users(id),
    source_message  TEXT,
    context         TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_entity ON change_history(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_history_community ON change_history(community_id, created_at);

CREATE TABLE IF NOT EXISTS personal_reminders (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    event_id     INTEGER REFERENCES academic_events(id),
    title        TEXT NOT NULL,
    remind_at    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'PENDING'
                 CHECK (status IN ('PENDING','SENT','CANCELLED')),
    created_at   TEXT NOT NULL,
    sent_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_personal_reminders_due ON personal_reminders(status, remind_at);

-- "Mark Complete" is personal state, never official event mutation (spec 28).
CREATE TABLE IF NOT EXISTS personal_event_completions (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    event_id      INTEGER NOT NULL REFERENCES academic_events(id),
    completed_at  TEXT NOT NULL,
    UNIQUE (user_id, event_id)
);

-- Official reminders are per-event; recipients resolve at fire time so that
-- membership/enrollment changes between scheduling and firing are respected (spec 20).
CREATE TABLE IF NOT EXISTS event_reminders (
    id          INTEGER PRIMARY KEY,
    event_id    INTEGER NOT NULL REFERENCES academic_events(id),
    remind_at   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING','SENT','CANCELLED')),
    created_at  TEXT NOT NULL,
    sent_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_reminders_due ON event_reminders(status, remind_at);
CREATE INDEX IF NOT EXISTS idx_event_reminders_event ON event_reminders(event_id, status);

-- Email outbox. dedupe_key makes worker dispatch idempotent (spec 21).
CREATE TABLE IF NOT EXISTS notifications (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    community_id  INTEGER REFERENCES academic_communities(id),
    subject       TEXT NOT NULL,
    body          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'PENDING'
                  CHECK (status IN ('PENDING','SENT','SIMULATED','FAILED')),
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    dedupe_key    TEXT UNIQUE,
    created_at    TEXT NOT NULL,
    sent_at       TEXT,
    -- ── In-app delivery ───────────────────────────────────────────────────
    -- One row is BOTH the email outbox entry and the in-app notification.
    -- They are not the same lifecycle, so they do not share a column:
    --   status  is DELIVERY  (PENDING -> SENT/SIMULATED/FAILED, by the worker)
    --           SENT means a provider accepted it; SIMULATED means a
    --           development backend only printed it. Both are terminal.
    --   read_at is ATTENTION (NULL until the person opens it)
    -- An email that has been sent is not a notification that has been read,
    -- and collapsing the two would make either one unreadable.
    kind          TEXT,    -- e.g. PERSONAL_REMINDER; NULL for older rows
    link          TEXT,    -- in-app destination, when there is a useful one
    read_at       TEXT,
    -- The bell's own wording. subject/body above are the EMAIL, which must be
    -- understood without opening the app (spec 19); the bell shows a kind
    -- label, a short subject and one sentence. NULL on older rows, which the
    -- bell then shows in their email wording.
    app_subject   TEXT,
    app_body      TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_pending ON notifications(status, id);
-- The bell's query: this user's newest first, unread counted.
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, id DESC);

CREATE TABLE IF NOT EXISTS chat_conversations (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    community_id  INTEGER NOT NULL REFERENCES academic_communities(id),
    title         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_conv_user ON chat_conversations(user_id, updated_at);

CREATE TABLE IF NOT EXISTS chat_messages (
    id               INTEGER PRIMARY KEY,
    conversation_id  INTEGER NOT NULL REFERENCES chat_conversations(id),
    role             TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content          TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_msg_conv ON chat_messages(conversation_id, id);
