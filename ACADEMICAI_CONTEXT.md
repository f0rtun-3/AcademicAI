# AcademicAI — Master Project Context & Handoff

**Purpose:** This document is the canonical product/architecture handoff for working on AcademicAI with Claude Code.

**Important:** Read this document before making changes. Then inspect the existing repository and tests. The codebase is authoritative for what is already implemented; this document is authoritative for the intended product behavior and business rules. Do not rewrite working systems simply to match a different implementation style.

---

# 1. Product

## Name
AcademicAI — AI Academic Assistant

## Core idea

AcademicAI converts fragmented, unstructured academic communication into structured, personalized, actionable academic information.

Core framing:

> AcademicAI is an intelligent academic information system that takes fragmented, unstructured academic communication, determines what it means, who it applies to, what has changed, and turns it into a reliable, personalized academic record.

Three pillars:

1. **Understand** — extract meaning from messy academic messages.
2. **Personalize** — determine who the information applies to.
3. **Maintain** — maintain current state and detect/update changes instead of duplicating records.

WhatsApp is an input source, not the product. MVP uses copy/paste of messages; direct WhatsApp integration is V2.

---

# 2. Core Workflow

Student or verified rep receives an academic message.

→ Copies/pastes message into AcademicAI.

→ AI interprets the message.

→ Backend supplies relevant existing academic records.

→ AI proposes a structured action.

Possible actions:

- CREATE
- UPDATE
- DUPLICATE
- CLARIFICATION
- CANCEL

For official information:

→ Verified Rep reviews proposal.

→ Rep can Edit, Discard, or Confirm & Publish.

→ Backend revalidates authorization and current database state.

→ Database changes transactionally.

→ Change history records old/new state.

→ Existing reminders are cancelled/rescheduled as necessary.

→ Affected students receive email notifications.

The AI proposes. The backend authorizes. The database is the source of truth.

---

# 3. Technology / Architecture

Current intended stack:

- Frontend: React, JavaScript or TypeScript
- Backend: Python + Flask
- Database: SQLite for MVP/development, database layer designed for PostgreSQL production
- AI: LLM behind a provider/service abstraction
- Git/GitHub
- Background worker for notifications/reminders/ballots

Architecture:

React
→ Flask API
→ Authentication
→ Authorization
→ Business Logic / Services
→ Database
→ AI / Notification / Worker services

Rules:

- Frontend is presentation/UX.
- Flask/backend owns security, authorization, validation, and state changes.
- Database is the source of truth.
- AI interprets and reasons over authorized data.
- AI never directly mutates the database.
- AI never determines authority.
- Confidence never grants authority.
- Business-critical authorization must be backend-enforced.

---

# 4. Academic Community Identity

A community is uniquely identified by:

**University + Department + Level + Academic Session**

Examples:

- Babcock University + Software Engineering + 200 + 2026/2027
- Babcock University + Software Engineering + 300 + 2026/2027
- Babcock University + Computer Science + 300 + 2026/2027

The combination is unique.

Students from different communities must be isolated from one another.

---

# 5. Roles

MVP roles:

1. Student
2. Rep Candidate
3. Verified Rep

No Platform Admin is required for MVP.

## Student

Can:

- View official academic information.
- View courses.
- View timetable.
- View announcements.
- View assignments, quizzes, tests, presentations, exams.
- View deadlines and deadline changes.
- View venue changes.
- View cancellations/reschedules.
- View recent changes.
- Ask AcademicAI.
- Paste WhatsApp messages for personal interpretation.
- Create personal reminders.
- Mark personal tasks complete.
- Vote in rep verification/removal where eligible.
- Join/leave communities.
- Request membership in another community after transfer.

Cannot directly create or modify official community academic information.

## Verified Rep

Maximum: **3 verified reps per community**.

All reps have equal permissions.

Rep authority is tied to a specific community, not to individual courses.

Can:

- Add/edit/remove courses.
- Manage official timetable.
- Publish/edit official announcements.
- Create assignments.
- Create quizzes.
- Create tests.
- Create presentations.
- Create exams.
- Change deadlines.
- Change venues.
- Cancel/reschedule classes/events.
- Upload/update academic calendar.
- Manage official academic information.
- Nominate candidates.
- Approve/reject membership requests in an ACTIVE community.
- Initiate removal of another verified rep in the same community.

Cannot:

- Manage another community.
- Access unnecessary private student data.
- Grant platform-admin authority.
- Bypass backend authorization.
- Directly mutate the database through AI.

---

# 6. Account Verification vs Membership vs Rep Authority

These are separate concepts and must never be conflated.

## MVP SCOPE DECISION: student ID-card verification is OUT OF SCOPE

**Student ID-card scanning / OCR identity verification is not part of the
current MVP.** There is no ID-card upload, no image scanning, no OCR and no
vision provider. This is a deliberate scope reduction.

Nothing replaces it in the flow — the step is removed, not substituted.

The product therefore does NOT establish who a student is. It must never be
described as verifying identity. The states VERIFIED / REJECTED /
NEEDS_REVIEW no longer exist as an identity outcome; `users.identity_status`
remains in the schema as a legacy, unread column so that live databases did
not need a risky migration.

If ID-card verification is reinstated, it belongs behind a provider
abstraction, and it must not be presented as authoritative unless it actually
checks a student registry.

## Account verification (the remaining gate)

Answers:

> Does this person control an email address on an approved institutional
> domain for the university they selected?

That is an affiliation signal. It is NOT proof of identity or of enrolment,
and the documentation must not imply otherwise.

Stored separately from community membership.

The student must:

1. Register (institutional domain enforced against the approved registry).
2. Verify email.

Account verification is not community membership.

## Community membership

Answers:

> Is this student authorized to belong to this exact academic community?

Membership is community-specific.

## Rep verification

Answers:

> Is this member authorized to manage this community?

A student can be:

- email verified but not a community member;
- a community member but only a STUDENT;
- a verified rep with authority only in that community.

---

# 7. Registration / Onboarding

Registration fields:

- Full name
- Student email
- Password
- Confirm password
- University
- Department
- Level
- Academic session

Flow:

Register
→ email verification
→ community determination/setup
→ membership
→ dashboard

(There is no identity-verification step: student ID-card verification is out
of MVP scope. See section 6.)

If a community exists:

> Your academic community is ready.

If it does not:

> Your academic community hasn’t been set up yet.

Options:

- Yes, I’m a Course Rep
- I’m a Student

---

# 8. Pending Community Bootstrap

A newly created community starts as `PENDING`.

There is no verified rep yet.

To prevent a deadlock:

- Eligible students who have completed email verification can join a PENDING community automatically.
- Students who have not verified their email cannot join.
- This automatic membership exists only to bootstrap the first rep election.
- Minimum eligible electorate for first rep election: **3 verified/eligible students**.
- Once the first rep is successfully verified, the community becomes `ACTIVE`.

After activation, normal membership approval rules apply.

---

# 9. ACTIVE Community Membership

For an ACTIVE community:

**Email verified**
→ **Membership request**
→ **Verified Rep approval**
→ **Community member**

A student awaiting approval must not be treated as an active member by the frontend or backend.

The UI must show a clear awaiting-approval state rather than routing the user to a dashboard that will return 403 errors.

Approval gives:

`membership_status = ACTIVE`

Approval does NOT make the student a rep.

The role remains:

`STUDENT`

---

# 10. Transfers

Transfers were initially missing and have now been implemented.

A transfer means the student's community changes.

Examples:

- Software Engineering 200 → Software Engineering 300
- Computer Science 300 → Software Engineering 300

Rules:

- Existing email verification remains valid across a transfer.
- Account verification does not automatically grant membership in the destination community.
- Student submits a membership request to the destination community.
- If destination community is ACTIVE, destination verified rep approves/rejects.
- The student's old membership remains ACTIVE until the destination request is approved.
- If destination request is rejected, student remains in old community and is not stranded.
- On successful destination approval:
  - old membership ends;
  - old role is reduced to STUDENT;
  - old course enrollments are removed;
  - stale notifications stop;
  - if student was a rep in old community, rep authority is revoked and token/session epoch is invalidated as appropriate.

Community membership is always community-specific.

---

# 11. Rep Verification

Maximum: **3 verified reps per community**.

Eligibility:

- verified student;
- member of exact community;
- satisfies the community's eligibility rules.

Candidate cannot vote for themselves.

One vote per eligible voter per candidate.

Voting duration:

**24 hours**

Minimum actual votes:

**3**

Non-voters do not count as NO.

Results:

- YES > NO with at least 3 votes → PASS
- YES = NO → FAIL
- YES < NO → FAIL
- fewer than 3 votes → FAIL

A failed candidate has a **7-day cooldown** before retrying.

Nomination never grants authority.

Rep authority begins only after successful ballot resolution.

When the first rep is verified, the PENDING community becomes ACTIVE.

Rep authority does not automatically carry to a new academic session.

---

# 12. Rep Removal

Final product rule:

Any verified rep may initiate removal of another verified rep in the same community.

The target cannot vote on their own removal.

Eligible voters:

**All verified, approved students who are active members of that exact community, excluding the target.**

This is intentionally broader than the rep bench.

Voting:

- 24 hours
- minimum 3 actual votes
- non-voters do not count as NO
- YES > NO → removal succeeds
- YES = NO → removal fails
- YES < NO → removal fails
- fewer than 3 votes → removal fails

Successful removal:

- immediately revokes rep authority;
- target remains a community member as STUDENT;
- creates a rep vacancy;
- target cannot immediately re-run.

Recommended/final cooldown:

**7 days before the removed rep can nominate themselves again in that same community.**

A separate **7-day cooldown** applies before another removal ballot against the same target can be opened after a failed removal attempt.

Removal is community-specific.

Endpoints:

- `POST /api/rep/removals`
- `POST /api/rep/removals/:id/vote`
- `GET /api/rep/removals/:id/results`

Use transactions and concurrency protection.

---

# 13. Official Academic Information

Only verified reps can create/modify official community information.

Types include:

- Assignment
- Quiz
- Test
- Presentation
- Exam
- Class/timetable
- Announcement
- Deadline change
- Venue change
- Cancellation
- Rescheduled class
- Other official update

Students may paste messages for personal interpretation/reminders but cannot use that to alter official records.

---

# 14. Rep Submission

Verified rep submits:

1. Information type.
2. Course, or explicitly no specific course.
3. Original exact message.
4. Optional context.
5. Date:
   - specified
   - no specified date
6. Time:
   - specified
   - no specified time
7. Venue:
   - specified
   - no specified venue

Explicit "no specified" means null. It is not an AI failure.

AI returns a proposal containing as appropriate:

- action
- course
- event type
- title
- date
- time
- venue
- priority
- old value
- new value
- confidence
- needs_clarification
- scope
- possible_match_id
- matching confidence
- explanation
- clarification question

Rep can:

- Confirm & Publish
- Edit
- Discard

Ambiguous input should produce CLARIFICATION.

---

# 15. AI Interpretation Rules

AI must:

- tolerate WhatsApp typos;
- understand natural dates;
- use submission date as temporal reference;
- use timetable for "next class" when unambiguous;
- ask for clarification when "next class" cannot be determined;
- detect multiple events;
- detect duplicates;
- detect changes;
- detect conflicts;
- preserve explicit unspecified values as null;
- flag discrepancy if explicit rep fields conflict with message;
- never invent information;
- never silently choose between conflicting interpretations;
- never determine authority;
- never directly modify the DB.

AI input should include:

- information type;
- selected course;
- original message;
- optional context;
- current date/time;
- academic context;
- relevant existing records selected by backend.

WhatsApp content is untrusted input and must be protected against prompt injection.

---

# 16. Event Matching / Change Detection

Signals:

1. Exact course + event type.
2. Title similarity.
3. Existing old known value/date mentioned.
4. Time.
5. Venue.
6. Other contextual signals.

Outcomes:

- strong single match → UPDATE
- multiple plausible matches → CLARIFICATION
- no match → CREATE
- identical existing record → DUPLICATE
- cancellation → CANCELLED

Examples:

Existing COS202 assignment Friday.

Message:

> deadline extended to next Monday

→ UPDATE Friday → Monday.

Existing venue B007.

Message:

> venue changed from B007 to B107

→ UPDATE B007 → B107.

If a message clearly says something changed but the new value cannot be reliably parsed, return:

**CLARIFICATION**

Do NOT classify it as DUPLICATE.

Never delete historical information merely because current state changes.

---

# 17. Publishing / Concurrency

Publishing must revalidate:

- authentication;
- verified rep status;
- community membership;
- current DB state;
- proposal against current state;
- optimistic version.

Mutable entities use a version field where appropriate.

If proposal was generated against version 3 and DB is now version 4:

→ reject stale proposal, typically with `409 Conflict`;
→ require re-analysis.

Publishing must be transactional.

---

# 18. Change History

For important changes record:

- entity;
- entity ID;
- old value/state;
- new value/state;
- actor;
- timestamp;
- source/original message;
- relevant context.

Current record represents current state.

Change history preserves historical transitions.

---

# 19. Notifications

MVP notification channel:

**Email only.**

No push, SMS, or WhatsApp notifications in MVP.

Official published information can trigger notifications for:

- announcements
- assignments
- quizzes
- tests
- presentations
- exams
- timetable changes
- deadline changes
- venue changes
- cancellations
- reschedules
- other relevant official updates

Recipient resolution happens at publish time.

Course-specific recipients are the intersection of:

**active community members × active course enrollments**

This prevents stale enrollment rows or former members from receiving notifications.

Late joiners can see current academic records but do not receive stale "new assignment" notifications published before they joined.

For changes:

1. update event;
2. record change history;
3. cancel obsolete future reminders;
4. schedule replacement reminders;
5. notify affected students.

Email status:

- PENDING
- SENT
- FAILED

Failed notifications should support retry behavior according to the existing worker/outbox design.

Emails should contain enough information to understand the change without opening the app.

---

# 20. Reminders

MVP default reminder:

**1 day before deadline**

Current MVP firing time:

**08:00 server time**

Do not introduce per-user timezone infrastructure yet; this is acceptable for the MVP.

Architecture should avoid making future timezone support unnecessarily difficult.

When a deadline changes:

- cancel old reminder;
- schedule new reminder.

When an event is cancelled:

- cancel future reminders.

Personal reminders are separate from official academic records.

---

# 21. Background Worker

Current worker architecture has one loop with separate jobs/transactions.

Worker responsibilities include:

- notification/outbox dispatch;
- reminder processing;
- expired rep verification ballots;
- other asynchronous lifecycle work as appropriate.

Separate transactions should prevent a failure in one job from rolling back successful work in another.

Ballot closing must be idempotent.

Running the same job twice must not:

- promote a candidate twice;
- create duplicate state transitions;
- reopen/duplicate ballots;
- duplicate notifications.

Concurrency must be handled safely.

---

# 22. AI Chat

AI Chat is the next major feature after the core lifecycle work is stable.

Student asks a question.

→ Flask authenticates user.

→ Backend identifies exact community.

→ Backend selects only authorized academic data.

→ Database supplies current truth.

→ AI generates a grounded answer.

Examples:

- What assignments do I have this week?
- What classes do I have tomorrow?
- What is my next deadline?
- What changed recently?
- What is happening in COS202?
- Where is my next class?
- What do I need to finish before Friday?
- When was the COS202 deadline changed?
- What should I focus on this week?

AI can summarize, explain, plan, and create personal reminders.

AI must not hallucinate.

If the data does not contain the answer, say so.

If the student asks to modify official academic information, explain that only verified reps can do so.

Conversation history is stored separately from official academic data.

---

# 23. Academic Calendar / Session Lifecycle

Verified reps can upload the academic calendar.

AI can extract:

- session start/end;
- semester/term dates;
- academic periods.

At session end:

- old community is archived;
- new-session setup begins;
- students confirm university, department, level, session;
- new community membership is established.

Do NOT automatically increment level.

Do NOT blindly copy courses/timetable.

New reps must be established for the new session.

Rep authority does not automatically carry over to the new session.

Graduated students retain account/history but should not receive new community notifications.

---

# 24. Courses / Enrollments

Course enrollment exists because course-scoped notifications require knowing exactly which students are affected.

Important rule:

Do not assume every community member is enrolled in every course.

Course-specific notification targeting should use active course enrollments.

---

# 25. Security / Privacy

Required:

- secure password hashing;
- secure sessions/tokens;
- expiry/logout;
- email verification;
- temporary ID deletion;
- community isolation;
- backend rep authorization;
- rate limiting;
- AI data isolation;
- prompt-injection protection;
- no arbitrary DB access via AI;
- audit trail;
- data minimization;
- no sensitive data in errors/logs;
- CSRF protection if cookie authentication is used;
- secure token handling otherwise;
- SQL injection prevention;
- environment variables for secrets;
- file-upload restrictions;
- ID files not public;
- HTTPS in production;
- backups;
- concurrency protection;
- stale proposal protection;
- revoked reps lose authority;
- expired authentication is rejected.

Never log sensitive student ID information unnecessarily.

## File uploads (supporting material)

The only user-supplied bytes the product stores. `services/attachment_storage.py`
is the single place that writes them, and the rules live there:

- **Allow-list of formats**, not a deny-list: PDF, Word, PowerPoint, plain
  text, and photos (PNG, JPEG, WebP, HEIC).
- **The declared content type is a claim, not evidence.** Every upload is
  sniffed and the leading bytes must match what was declared, which is what
  stops a script being stored as a PDF.
- **Size is enforced while streaming**, not from `Content-Length`, which a
  client controls. A partial file is deleted before the error propagates.
- **Generated storage keys.** The filename is user input; it is kept for
  display and never used to build a path. Nothing is stored under a name a
  person chose.
- **Nothing is executable**: files are written 0o600 outside any static root,
  and no URL maps to the upload directory.
- **Every read goes through an authorised route** that resolves the file
  through its event, so community scoping applies and a guessed id is a 404.
  Responses carry `Content-Disposition: attachment`, `X-Content-Type-Options:
  nosniff` and `Cache-Control: private, no-store`.

---

# 26. Database

Existing/expected core structures include:

- users
- universities
- academic_communities
- community_members
- courses
- course_enrollments
- timetable_entries
- academic_events
- event_attachments
- announcements
- rep_nominations
- rep_verification_votes
- rep_removals
- rep_removal_votes
- academic_calendars
- change_history
- personal_reminders
- notifications
- chat_conversations
- chat_messages

Additional authentication/verification/outbox/worker structures may exist or be added where justified.

Do not add tables merely for abstraction aesthetics.

## Supporting material on an academic event

`academic_events` carries two optional fields for assignment/project work:

- `description` — the typed instructions. NULL is normal: an event created
  from a one-line WhatsApp message has none.
- `event_type` includes `PROJECT` alongside `ASSIGNMENT`.

`event_attachments` holds the ORIGINAL brief, when the lecturer gave one as a
file. The relationship is one-to-many from the event side only, and **zero
attachments is a valid, complete, normal state**. Nothing in `academic_events`
references this table, and no publishing path consults it.

- `storage_key` — generated by the application, the only thing used to locate
  bytes on disk. Never derived from user input and never sent to a client.
- `original_name` — display text only. Never used to build a path.
- `status` — a removal keeps the row (`REMOVED`) and deletes the bytes, so the
  record can still say material was published and later withdrawn.

Adding `PROJECT` required rebuilding `academic_events`, because SQLite cannot
alter a CHECK constraint. See `db/connection.py::_widen_event_type_check`: it
is guarded, idempotent, transactional, and verifies row count and foreign keys
before committing.

---

# 27. API

Core conceptual endpoints:

## Auth

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `POST /api/auth/verify-email`
- `POST /api/auth/forgot-password`
- `POST /api/auth/reset-password`
- `GET /api/auth/me`

## Community

- `GET /api/community`
- `POST /api/community/join`
- `POST /api/community/leave`
- `GET /api/community/members`
- `GET /api/community/courses`
- `GET /api/community/timetable`
- `GET /api/community/announcements`
- `GET /api/community/changes`

## Events

- `GET /api/events`
- `GET /api/events/:id`
- `POST /api/events`
- `PUT /api/events/:id`
- `POST /api/events/:id/cancel`
- `POST /api/events/:id/attachments` — rep only; multipart, one file
- `GET /api/events/:id/attachments/:attachment_id` — member only; streams the
  file with `Content-Disposition: attachment`, `nosniff` and `no-store`
- `DELETE /api/events/:id/attachments/:attachment_id` — rep only

## AI

- `POST /api/ai/analyze-message`
- `POST /api/ai/publish`

## Chat

- `POST /api/chat`
- `GET /api/chat/history`

## Rep

- `POST /api/rep/nominate`
- `GET /api/rep/candidates`
- `POST /api/rep/candidates/:id/vote`
- `GET /api/rep/candidates/:id/results`
- `POST /api/rep/removals`
- `POST /api/rep/removals/:id/vote`
- `GET /api/rep/removals/:id/results`

## Reminders

- `POST /api/reminders`
- `GET /api/reminders`
- `PUT /api/reminders/:id`
- `DELETE /api/reminders/:id`

Actual existing routes take precedence where already implemented.

---

# 28. Frontend

## Auth screens

- Sign Up
- Login
- Email verification
- Email verification (student ID-card verification is out of MVP scope)

## Community setup

If community exists:

> Your academic community is ready.

If not:

> Your academic community hasn’t been set up yet.

Options:

- Yes, I’m a Course Rep
- I’m a Student

## Student Dashboard

Show:

- greeting;
- university;
- department;
- level;
- academic session;
- upcoming academic items;
- recent changes;
- quick actions;
- Add Message;
- Ask AcademicAI.

## Add Message

For students:

→ personal interpretation/reminders.

For verified reps:

→ official academic-information workflow.

## AI analysis

Display:

- proposed action;
- course;
- event type;
- previous value;
- new value;
- confidence;
- matching/existing record;
- clarification if needed.

Rep actions:

- Confirm & Publish
- Edit
- Discard

## Calendar

Show:

- classes;
- assignments;
- quizzes;
- tests;
- presentations;
- exams.

Event detail:

- title;
- type;
- course;
- date;
- time;
- venue;
- priority;
- original message;
- status.

"Mark Complete" is personal state, not official event mutation.

## Community page

Show:

- community identity;
- courses;
- timetable;
- announcements;
- recent changes;
- verified reps.

## Rep dashboard

Show:

- community overview;
- student count;
- rep count;
- Add Academic Information;
- Manage Courses;
- Manage Timetable;
- Announcements;
- Rep Management;
- Academic Calendar;
- membership requests.

## AI Chat

Show:

- conversation;
- grounded answers;
- useful prompts;
- personal reminder creation.

All screens need sensible:

- loading;
- empty;
- error;
- unauthorized;
- no-data;
- success;
- awaiting approval states.

---

# 29. MVP

Must include:

- authentication;
- onboarding;
- email verification;
- email verification;
- communities;
- membership;
- transfer flow;
- rep candidate/verification;
- rep removal;
- courses;
- course enrollments;
- timetable;
- academic events;
- announcements;
- deadline/venue changes;
- cancellations/reschedules;
- AI message interpretation;
- personal message processing;
- dashboard;
- calendar;
- email notifications;
- personal reminders;
- academic calendar;
- change history;
- AI Chat;
- security;
- testing.

---

# 30. V2 / Explicitly Not MVP

Do not add these unless explicitly requested:

- direct WhatsApp integration;
- mobile app;
- push notifications;
- SMS;
- LMS integrations;
- payments;
- social networking;
- forums/chatrooms;
- study groups;
- course-material marketplace;
- scholarships/jobs;
- generic AI tutoring;
- CGPA calculator;
- lecturer accounts;
- Google/Outlook Calendar integrations;
- institution-wide automated integrations.

---

# 31. Testing Requirements

Testing must exist at:

- unit;
- service/business logic;
- API;
- authentication;
- authorization;
- AI;
- integration;
- worker;
- concurrency;
- E2E;
- browser/UI;
- security.

Important AI cases:

1. `WE have cos 202 assignmentto be submittted on friday`
   → COS202 assignment Friday.

2. `We have 212 presentation, to beb presented next two weeks`
   → presentation, exact date ambiguous → CLARIFICATION.

3. `We’re having a quiz nexgt class on th202`
   → quiz; use timetable if possible; otherwise clarification.

4. `Guys the venue fo adventist heritage has ben changed from b007 to b107`
   → venue change B007 → B107, existing record matched, no duplicate.

5. `we now have philosophy every wednesddays insted ofevery thursdays.`
   → timetable Thursday → Wednesday.

6. `The deadline for the cos202 assignment has been extended to next week monday.`
   → existing Friday assignment UPDATE → Monday.

Also test:

- create;
- update;
- duplicate;
- ambiguous;
- conflict;
- cancellation;
- malformed/typo-heavy input;
- explicit unspecified date/time/venue;
- discrepancy between rep fields and message;
- stale proposal;
- cross-community isolation;
- authorization;
- revoked rep;
- transferred rep;
- notification targeting;
- reminder rescheduling;
- ballot resolution;
- rep removal;
- membership approval;
- transfer rejection;
- transfer approval.

---

# 32. Deployment / Database

SQLite is acceptable for development/MVP but is a file and has concurrency limitations.

Deployment must avoid losing the DB because of an ephemeral filesystem.

Existing deployment design should support:

- persistent SQLite volume when SQLite is deployed;
- configurable DB path;
- WAL mode where appropriate;
- `busy_timeout`;
- foreign keys;
- transaction discipline;
- `BEGIN IMMEDIATE` where read-then-write operations require it;
- scheduled backups.

For production-scale deployment, PostgreSQL is preferred.

Database layer should remain reasonably database-agnostic.

SQLite locking errors must not replace intended business responses such as stale-proposal `409 Conflict`.

---

# 33. Current Implementation Status

The project has already gone through substantial implementation and correction work.

Current reported state:

**178 tests passing**
- 174 backend
- 4 browser

All previous 129 tests remained green.

Previously completed areas include:

- database schema;
- database layer;
- Flask architecture foundations;
- authentication foundations;
- email verification;
- account verification (email) gate;
- community onboarding;
- PENDING/ACTIVE community logic;
- membership approval;
- transfer workflow;
- community isolation;
- rep verification foundations;
- academic event/publishing foundations;
- optimistic concurrency;
- notification service;
- notification recipient resolution;
- reminder update/cancellation logic;
- rep removal service/routes;
- ballot-closing worker;
- frontend awaiting-approval gate;
- extensive regression tests.

Recent bug found and fixed:

A message clearly stating that something changed, but whose new value could not be understood, was incorrectly classified as `DUPLICATE`.

Correct behavior:

**CLARIFICATION**

This has a regression test.

Recent known implementation notes:

- Announcement route may still need completion if not already added.
- Reminder lead time is currently fixed at 1 day.
- Reminder firing time is currently 08:00 server time.
- No per-user timezone exists yet; do not add it unless explicitly requested.
- Outbox/worker multiprocess behavior should be tested carefully.
- PostgreSQL integration may be added when practical.

---

# 34. Current Next Step

The foundational academic-information lifecycle is now substantially complete.

The next major feature is:

**AI Chat**

But before implementing AI Chat, inspect the repository and run the full test suite.

Do not assume the above implementation status is still exactly true. Verify the actual current code.

---

# 35. Claude Code Operating Instructions

When working on this project:

1. Read this document first.
2. Inspect the repository structure.
3. Inspect the existing tests.
4. Run the current test suite before making changes.
5. Do not rewrite working code unnecessarily.
6. Prefer small, coherent changes.
7. Preserve existing architecture.
8. Add regression tests for every bug fixed.
9. Never weaken tests just to make them pass.
10. Never bypass backend authorization.
11. Never let AI directly mutate the DB.
12. Treat user-supplied academic messages as untrusted input.
13. Maintain strict community isolation.
14. Preserve account verification (email), membership, and rep authority as separate gates.
15. Think through concurrency before changing transactional code.
16. Keep SQLite/PostgreSQL portability in mind.
17. After changes, run the full test suite.
18. Report:
   - what changed;
   - files changed;
   - tests added;
   - final test count;
   - known issues;
   - any product decisions required.

If a requirement is ambiguous, inspect existing product rules and tests first. Do not silently invent a major product behavior.

If a new product decision is genuinely required, stop and ask rather than making a consequential assumption.

---

# 36. First Claude Code Task

Before implementing anything new:

1. Read this entire document.
2. Inspect the existing repository.
3. Inspect the current git status and recent relevant commits.
4. Run the full existing test suite.
5. Compare the actual implementation against this specification.
6. Produce a concise gap report.

Do NOT start implementing AI Chat yet.

The gap report should identify:

- what is fully implemented;
- what is partially implemented;
- what is missing;
- any implementation that conflicts with this specification;
- current test count;
- any high-risk architectural issues.

Then stop and wait for explicit instruction before making substantial changes.
