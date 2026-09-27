# AcademicAI

An intelligent academic information system. It takes fragmented, unstructured
academic communication, works out what it means, who it applies to and what has
changed, and turns it into a reliable, personalized academic record.

The canonical product specification is [`ACADEMICAI_CONTEXT.md`](ACADEMICAI_CONTEXT.md).
This file describes the implementation.

## The rule that shapes the architecture

> The AI proposes. The backend authorizes. The database is the source of truth.

The AI never writes to the database and never decides authority. It returns a
proposal; a verified rep reviews it; the backend re-validates authentication,
rep authority, community membership and the current database version before
anything changes.

## Layout

```
backend/
  academicai/
    app.py                  Flask application factory, error handlers
    config.py               Configuration; secrets come from the environment
    clock.py                Single source of time; owns UTC instants (offset required)
    academic_time.py        University wall-clock <-> UTC instant, in the university's zone
    errors.py               Error types, each mapping to one HTTP status
    db/
      schema.sql            The only SQLite-specific file
      connection.py         Connections, WAL, busy_timeout, BEGIN IMMEDIATE
      reference_data.py     Seeded university email-domain registry
    security/
      authz.py              The three authorization gates
      passwords.py          PBKDF2 hashing
      tokens.py             Opaque tokens, stored only as hashes
      rate_limit.py         Fixed-window limiting
    services/               All business rules and state changes
      email_domain_service.py  Institutional email-domain validation
    ai/
      provider.py           Provider abstraction
      heuristic.py          Deterministic interpreter (default)
      anthropic_provider.py Claude-backed interpreter (production)
      prompts.py            Prompt construction + untrusted-input handling
      nlp.py                Typo-tolerant text and date parsing
      chat_heuristic.py     Grounded answering for AI Chat
    api/                    HTTP routes only; no business logic
    worker/                 Background jobs, one transaction each
  tests/                    Backend test suite
frontend/
  src/
    styles.css              The design system: tokens, components, responsive
    components/
      ui.jsx                Chips, boards, rows, tally, notices, fields,
                            password input, modal
      States.jsx            Loading, empty, error, unauthorized; error-copy rule
      Layout.jsx            The app shell: desktop rail, top bar, phone tab bar
      Brand.jsx             The wordmark and mark (same figure as the favicon)
      ThemeToggle.jsx       Light / dark / system, persisted per browser
      PublicNav.jsx         Public navigation and its mobile sheet
      PublicFooter.jsx      Public footer
      ProductPreview.jsx    Hero/auth product figure, built from real primitives
      AuthLayout.jsx        Shared two-column shell for login / sign-up / reset
      StepList.jsx          Onboarding progress (a reading, never a control)
      onboarding.js         The step ids, shared with the routing gate
      RepElections.jsx      Elections and rep removal
      CommunityMembership.jsx  Transfer and leave
      PersonalReminders.jsx Personal reminders
    lib/
      attention.js          The "Needs attention" projection (holds no state)
    pages/                  One file per screen; Landing.jsx is the public site
    api/client.js           The only place that talks to the API
    auth/AuthContext.jsx    Session and onboarding state
  tests/                    UI test suite
```

### Public and authenticated

`/` is the public landing page and is served to **everyone**, signed in or not.
It is not redirected away from: the landing page is the link people share, and
whoever opens it should see the product. When a session exists the navigation
offers "Open AcademicAI" instead of "Log in", so nobody is asked to sign in
twice. An unknown URL sends an anonymous visitor to `/` and a signed-in user to
`/dashboard`.

Login, sign-up and password reset share `AuthLayout` — the product on the left,
the form on the right, with the brand column removed below 960px so the first
input stays above the fold. Onboarding steps (verify email, community setup,
awaiting approval) keep the narrower `.gate` composition instead, because they
are steps inside a flow rather than a front door.

The desktop application shell puts the four destinations in a left rail at
1024px and up; between 640 and 1023px it keeps the original top tabs, and below
640px the title bar, bottom tab bar and single floating action are unchanged.
The rail is a layout change only — it holds the same four destinations at every
size, and a role still changes what is *inside* the shell, never the shell.

## The interface

The UI follows an approved visual specification. Three rules in it are
load-bearing rather than cosmetic, and each has tests:

- **A chip is a reading of state, never the state itself.** The database holds
  41 status values across 14 independent columns; the interface renders a
  subset of them. `components/ui.jsx` maps a value to a tone, and colour never
  carries meaning alone — every chip pairs a hue with a word and a dot, and
  terminal states drop the dot so "done" reads differently from "still
  happening".
- **Personal completion is not a status.** `personal_event_completions` is
  owner-scoped private state, so it renders as a slate marker in the metadata
  line that names its own scope — never a chip, never the status column, never
  a semantic colour. It cannot suppress official state or a notification, and
  it appears on no roster or management surface.
- **Nothing in the client is a permission.** `can_vote`, `cooldown_until`,
  `can_start_election`, `members_needed` and role flags decide what is *shown*.
  Every write submits and lets the backend decide, and a refusal renders as the
  backend's own sentence.

Two consequences worth knowing before editing a screen:

- **No frontend constant expresses a business rule.** The election threshold is
  interpolated from `community.election`; changing `ACADEMICAI_BALLOT_MIN_VOTES`
  must change the copy with no frontend edit. Where a value the UI would need is
  not in any response — `MAX_REPS_PER_COMMUNITY`, for instance — the UI states
  the count without a denominator rather than inventing one.
- **`lib/attention.js` holds nothing.** The dashboard's *Needs attention* band
  is a pure function of `academic_events` plus `change_history`, recomputed per
  render: no cache, no dismissal, no read state. Event detail wins any
  disagreement, and a refetch is the fix.

### Error copy

Business-rule refusals — `400`, `403`, `404`, `409`, `422` — render the
backend's `message` verbatim. The backend is the only authority on which rule
was enforced, so the client never paraphrases, softens or pre-empts one.
Transport and system failures — network, timeout, `429`, `5xx` — get UI framing
that always states whether anything was written, and keeps the backend's own
sentence where it wrote one. A failed read never says a change "may not have
been saved", because it cannot have.

### NEEDS_REVIEW

There is no review queue, and with student ID-card verification out of MVP
scope nothing produces a `NEEDS_REVIEW` identity any more. The copy rule stands
for anything that might: no screen, email or label may say "under review", "our
team", "awaiting approval" or imply an estimated wait. Adding one is a
specification violation, not a copy preference.

(`PENDING_APPROVAL` membership is a different thing entirely — a named human
rep decides it, and the UI says so.)

### Terminology

The user-facing word is **Matric Number** (**Matric No.** in narrow columns),
everywhere: sign-up, profile, validation and confirmation copy. The wire field
and column are still `student_id_number`; the boundary is simply that no user
ever sees the internal name.

It is **profile data only.** The student types it, the format is validated, and
nothing checks it against anything — there is no ID card to compare it to. No
screen may present it as verified.

## Running it

```bash
make install          # venv + pip + npm  (once)
make dev              # API + UI together -> http://localhost:5173
```

`make dev` is the normal way to run this project. It starts the Flask API and
the Vite dev server, points them at `instance/demo.db` with the console email
backend, waits until both answer, prints the demo sign-ins, streams both logs
labelled `[api]`/`[vite]`, and stops both on Ctrl-C. Add `--fresh` to use
`instance/academicai.db` instead of the demo data.

**Do not use a static file server** — VS Code Live Server, `python -m
http.server` or similar. `index.html` loads `/src/main.jsx`, and a static
server hands the browser raw JSX (`Content-Type: text/jsx`) which no browser
will execute, so the page renders blank. A static server also has no `/api`
proxy and no SPA fallback, so every API call 404s and refreshing any route
404s. Vite compiles the JSX, proxies `/api` to Flask, and serves `index.html`
for unknown paths.

The pieces individually, if you need them apart:

```bash
make api              # API only, on http://127.0.0.1:5000 (uses python -u)
make worker           # background worker (separate process)
cd frontend && npm run dev   # UI only, on http://127.0.0.1:5173
./scripts/dev_code.sh # read verification codes from the console email backend
```

Nothing else needs installing: there is no ID-card verification, so no OCR
engine, vision model or API key is involved in onboarding.

If you start the API yourself, use `python -u` (as `make api` and `make dev`
both do): with the `console` email backend the verification code is printed to
stdout, and Python block-buffers that away when it is redirected.

Copy `.env.example` to `.env` and set `ACADEMICAI_SECRET_KEY` and
`ACADEMICAI_DB_PATH` before deploying.

## Rep elections

A rep election resolves by these rules, none of which may be relaxed
independently:

| Rule | Value |
|---|---|
| Voting window | 24 hours |
| Minimum **actual** votes | 3 |
| Candidate voting for themselves | not allowed |
| Result | YES must strictly exceed NO |
| Tie | fails |
| Fewer than 3 actual votes | fails |
| Non-voters | never counted as NO |
| Failed candidate cooldown | 7 days |
| Maximum verified reps per community | 3 |

**A community needs at least 4 eligible members before an election can start.**
This follows from two of the rules above: the candidate cannot vote, and the
ballot needs 3 actual votes, so 3 eligible voters must exist *besides* the
candidate. A community reaches election *preparation* at 3 verified students,
but opening a ballot at that size would guarantee a 24-hour wait followed by an
unavoidable failure, so it is refused up front with an explanation.

`GET /api/community` returns an `election` object (`eligible_members`,
`required_members`, `can_start_election`, `members_needed`) so the UI states the
requirement before anyone tries to stand.

### What the client is told, and what it is not

`GET /api/community` returns an `election` object from
`community_service.election_readiness()`: `eligible_members`,
`required_members`, `preparation_threshold`, `in_preparation`,
`can_start_election`, `members_needed`, and — for the viewer only —
`cooldown_until`.

Every field is informational. `nominate()` re-derives all of it inside its own
transaction and refuses on its own findings, so a stale, missing or tampered
value can only mis-draw a screen. `cooldown_until` is self-only and omitted
entirely when no viewer is supplied: when a named classmate last failed a
ballot is not the caller's business. `candidate_cooldown_until()` is
deliberately a separate function from the enforcing `_assert_no_cooldown()`, so
a display helper can never become load-bearing — a test patches it to lie and
asserts the ballot is still refused.

## Institutional email domains (Gate 1)

Registration requires an email address on a domain **approved for the selected
university**. A verified email is not on its own evidence that someone belongs
to the university they picked, so two separate things are checked:

1. the email's domain is an approved institutional/student domain for that
   university — checked at registration, before any account is created;
2. the registrant controls that address — established by the existing
   email-link verification, unchanged.

Together these establish **control of an email account on an approved
institution domain**. That is an affiliation signal, not authoritative proof of
current enrolment or of identity.

Since student ID-card verification is out of MVP scope, this is now the ONLY
account-level check — there is nothing behind it. Treat that as the product's
main assurance limit, not as identity verification under another name.

### Supported universities

The registry is **deliberately limited to universities whose student email
domain has actually been confirmed**:

| University | Approved domain | Type |
|---|---|---|
| Babcock University | `student.babcock.edu.ng` | student |
| University of Ibadan | `stu.ui.edu.ng` | student |
| University of Lagos | `unilag.edu.ng` | institutional |
| Covenant University | `stu.cu.edu.ng` | student |

No other university is supported. AcademicAI does not claim support for any
institution whose domain has not been confirmed — registration for one is
refused, with the supported list returned in the error.

### Adding a university

Add a row to `university_email_domains` (and to
`db/reference_data.py` if it should be seeded on a fresh database). Nothing in
authentication, authorization, or onboarding changes. A university may hold
several domains; the schema does not assume one. Setting `active = 0`
withdraws a domain while keeping the historical row.

### How the comparison works

The domain is the exact string after the single `@`, lowercased and trimmed,
compared for **equality** against the registry. Consequences worth stating:

- There is **no `.edu.ng` rule**. One university's `.edu.ng` domain says
  nothing about another's, so `babcock.edu.ng` (the bare domain) is not
  accepted for Babcock — only `student.babcock.edu.ng` is.
- There is **no suffix or substring matching**, so
  `student.babcock.edu.ng.attacker.com` does not match, and neither does a
  subdomain such as `mail.student.babcock.edu.ng`.
- Comparison is case-insensitive: `FORTUNE@STUDENT.BABCOCK.EDU.NG` is accepted.
- Domains are unique registry-wide, so one domain can never be claimed by two
  institutions. Using Covenant's domain while selecting Babcock is refused.

### The backend decides

Approved domains are database state. `GET /api/universities` exposes the
registry read-only so the sign-up form can show which universities are
supported and what each expects — but the form is **guidance only**. The client
cannot supply, extend, or influence the registry, and a request that skips or
contradicts the hint is still validated server-side. The sign-up form
deliberately submits a mismatched address rather than blocking it locally, and
a test asserts that the backend is what refuses it.

Re-checked wherever the university could change:

- **Registration** — before the account exists and before any email is sent.
- **Transfers** — a transfer can change university, so the rule is re-applied
  against the account's email. A Babcock address cannot transfer into a
  Covenant community.
- **Email change** — `auth_service.change_email()` re-validates the domain,
  clears `email_verified`, spends outstanding verification links, and revokes
  sessions. A verified institutional email can never be traded for a personal
  address while keeping `email_verified = 1`. It is exposed as
  `POST /api/auth/change-email` (authenticated, rate limited per account). The
  route adds no policy of its own — the rules stay in the service — so the
  caller is logged out by its own request and must verify the new address
  before continuing. That is the rule working, not a defect.

### The four gates stay separate

| Gate | Checks | Evidence |
|---|---|---|
| 1. Institutional email | selected university + approved domain + verified email | control of an approved institution email account |
| 2. Community membership | university + department + level + academic session | eligibility for one exact community |
| 3. Rep authority | a resolved verification ballot | authority to publish official information |

There used to be a student ID-card gate between 1 and 2. It is **gone** — see
[Student ID-card verification is out of scope](#student-id-card-verification-is-out-of-scope-for-this-mvp).

Passing Gate 1 unlocks onboarding and nothing else. Tests assert that a valid
domain plus a verified email still cannot reach community data, publishing, or
rep authority, and that an account which stops being email-verified loses
access on its very next request.

## Student ID-card verification is OUT OF SCOPE for this MVP

**AcademicAI does not verify who a student is.** There is no ID-card upload, no
image scanning, no OCR, no Tesseract, no vision model and no external
identity-verification API. This is a deliberate scope reduction, not an
unfinished feature or a temporary outage.

Do not describe the product as verifying identity. It does not.

### What the account gate actually establishes

One thing: **the person controls an email address on an approved institutional
domain for the university they selected.** That is real evidence of
affiliation — a stranger cannot register as a Babcock student without a
`@student.babcock.edu.ng` address — and it is all of it.

It does **not** establish that they are the person named on the account, that
the Matric Number they typed is theirs, or that they are enrolled at all.

### What was removed

| Removed | Was |
|---|---|
| `POST /api/auth/identity` | the ID-card submission endpoint |
| `ai/identity_vision.py` | provider abstraction over Claude vision / fixture / fake |
| `ai/local_ocr.py`, `ai/ocr_text.py` | Tesseract OCR and the field parser |
| `services/identity_service.py` | the gate, evidence lifecycle and decision policy |
| `services/identity_matching.py` | name / number / institution comparison |
| `services/temp_storage.py` | private short-lived storage for card photos |
| `security/image_validation.py` | byte-signature validation of uploads |
| `pages/VerifyIdentity.jsx` | the upload screen and the `verify_identity` step |
| `authz.require_identity_verified` | the decorator form of the gate |
| every `ACADEMICAI_IDENTITY_*` and `ACADEMICAI_TESSERACT_CMD` variable | provider configuration |

There is deliberately **no configuration that can switch any of it back on.**
Leaving a provider setting behind would advertise a capability with no
implementation, and leaving the Anthropic vision provider reachable from the
identity flow is exactly the accident this removal is meant to prevent.

### What replaces it in onboarding

Nothing. The step is gone rather than substituted:

```
register  ->  verify email  ->  community setup  ->  join  ->  (approval)  ->  dashboard
```

`GET /api/auth/me` returns `next_step`, and `verify_identity` is no longer one
of its values. The client never routes to an ID screen because no such state
exists.

### Nobody was auto-marked verified

The lazy way to remove an identity gate is to stamp every account `VERIFIED`.
That would be a false security claim, so it was not done:

- `users.identity_status` is **legacy and unread**. It stays at its
  `'UNVERIFIED'` default, nothing writes it, and no gate consults it.
- `identity_verifications` is **legacy and unwritten**. Historical rows are
  preserved; no route exposes them, and a test asserts that.
- Accounts left `REJECTED` by the removed check are **not** stuck — that status
  no longer gates anything, which a test also asserts.

No migration was required or performed. The schema migrator only adds columns,
so dropping these would mean rebuilding tables on live databases for no
functional gain; both are annotated as legacy in `db/schema.sql`.

### Authorization did not get weaker anywhere else

Every place that required a verified identity now requires a **verified
email**, which is what the identity gate implied in practice (submitting a card
required a verified email first). One subtlety mattered: `require_member`
previously checked identity but *not* email, so it is now built on
`require_email_verified` rather than `require_auth` — deleting the identity
check alone would have quietly loosened it.

Unchanged: the election rules (24h ballot, three actual votes, YES>NO, tie
fails, max three reps, 7-day cooldowns, candidate cannot self-vote, four
eligible members to open an election), publishing authority, course
management, transfers, removal voting, and community isolation. A verified
email lets a student *ask* to join a community; an existing community still
approves or rejects them, and the role granted is `STUDENT`.

### If identity verification is ever reinstated

It belongs behind a provider abstraction again, and `authoritative` should stay
`false` unless the provider genuinely checks a student registry. Reading a card
answers *"what does this card say?"*, never *"is this card genuine?"*. Until
then, no copy anywhere may claim otherwise.

## The AI provider

`ACADEMICAI_AI_PROVIDER` selects the interpreter:

- **`heuristic`** (default) — deterministic, offline, no API key. Every
  interpretation rule in the spec is encoded here and pinned by tests, so the
  product's behaviour does not drift with a model release.
- **`anthropic`** — the Claude Messages API with a JSON-schema constrained
  response. Set `ANTHROPIC_API_KEY`.

Both return the same proposal contract, which is normalised and clamped before
the rest of the system sees it. Anything unrecognised degrades to
`CLARIFICATION` rather than being guessed at.

## Security

- Email verification, community membership and rep authority are separate
  gates and are never collapsed into one helper. Student ID-card verification
  is out of MVP scope, and `users.identity_status` is legacy and unread.
- Every gate reads live database state per request, so a revoked or transferred
  rep loses authority immediately. No authority is carried in the session token.
- Community isolation is enforced on every read and write. An id from another
  community answers 404, never 403, so it cannot confirm a record exists.
- Pasted messages are untrusted: sanitised, length-capped, delivered inside a
  data envelope, and schema-constrained on the way back. A successful injection
  still cannot grant authority or write to the database.
- Student ID document content is never persisted.
- Passwords are PBKDF2-SHA256; session and reset tokens are stored as SHA-256
  hashes only.
- The app refuses to start with `ACADEMICAI_ENV=production` if the secret key is
  still the development default, the database is in-memory, or the email backend
  is the test backend.

**Not applicable, rather than missing:**

- **CSRF** — authentication is a bearer token in an `Authorization` header.
  There is no cookie-based auth anywhere, so there is no ambient authority for a
  cross-site request to ride on. Adding CSRF tokens would protect nothing. If
  cookie auth is ever introduced, CSRF protection must be added with it.
File uploads: **there are none.** The only upload endpoint was the student
ID-card photo, and it was removed with that feature, so the application accepts
no file from any client. A general request-body cap
(`ACADEMICAI_MAX_CONTENT_LENGTH`) remains as cheap protection.

## Concurrency

- Every read-then-write runs under `BEGIN IMMEDIATE`.
- Mutable records carry a version. Publishing against a stale version returns
  `409 stale_proposal` and requires re-analysis.
- Ballot closing is a conditional `UPDATE ... WHERE status = 'OPEN'`, so running
  the worker twice cannot promote a candidate twice.
- Notification rows carry a unique dedupe key, so re-running a job cannot send a
  message twice.
- A SQLite lock failure surfaces as `503 database_busy`, never as a business
  `409` — the two are tested to stay distinct.

## Tests

```bash
make test-backend     # pytest
make test-frontend    # vitest
```

No test requires an API key, a network connection, or any external binary.

`tests/test_onboarding_flow.py` pins the MVP sequence and asserts the removed
ID-card feature stays removed — no endpoint, no importable module, no
configuration switch, and no account silently stamped verified.
`tests/test_account_gate_boundaries.py` replaces the old identity-boundary
suite: every boundary it protected is now checked against the email gate,
including that a member who loses email verification loses access on the very
next request and that a candidate who loses it mid-ballot is not promoted.

The backend suite covers unit, service, API, authentication, authorization,
account-gate boundaries, AI interpretation, publishing, notifications, reminders,
chat, session lifecycle, integration, worker, concurrency (real threads against
a file-backed database), and security cases including IDOR probes and SQL
injection attempts. Every worked example in the specification's AI section is a
test, typos included.

Community isolation is tested across all three axes that can differ: same
university/different department, same department/different level, and same
level/different academic session.

## Course removal

Removing a course is **refused** while any of its official records still exist:
a scheduled academic event, or an active timetable entry. The response is a 409
naming what still depends on it, and the rep must cancel or reschedule those
first.

This is a recorded product decision, not an accident. Course-scoped
notifications are targeted through ACTIVE enrolments, and removing a course
drops every one of them. A record left attached would keep existing while
reaching nobody, so a rep would see a successful deadline change that no
student ever received. Blocking makes the intent explicit and destroys nothing.
Cancelled events and cancelled timetable entries do not block removal.

## Session archival is a backend lifecycle action

`POST /api/community/archive` is **intentionally not exposed in the UI** for the
MVP. There is no archive button on the rep dashboard, and a community is **never
archived automatically** because the academic calendar's session-end date has
passed.

Archiving is irreversible and community-wide: it demotes every verified rep,
revokes their sessions, stops pending notifications, and cancels outstanding
reminders. A one-click control for that does not belong in the product until a
session-management workflow has been designed around it.

For the MVP it is an operator/backend action. The service, its authorization,
its transaction boundary, rep demotion, session revocation, notification
stopping and all of its tests remain fully intact and are exercised by the test
suite — only the user-facing entry point is withheld. A dedicated
session-management workflow may be designed later.

## Time and timezones

Every university has a required IANA timezone, `universities.timezone` (the
seeded Nigerian universities are `Africa/Lagos`). It is the university's
academic clock. Every event date and time, "today", and reminder time in its
communities is read on that clock, whatever the server or the student's device
is set to.

- **Instants** (reminder firing times, `created_at`) are stored in UTC with an
  explicit offset. A timestamp without an offset is refused, never assumed to
  be UTC.
- **Academic wall-clock values** (`event_date`/`event_time`, `remind_at_local`)
  have no offset on purpose. The backend reads them in the university's zone
  (`academic_time.py`, with Python's `zoneinfo`, so daylight saving is handled
  by the zone's own rules).
- **Official reminders** fire at 08:00 (`ACADEMICAI_REMINDER_HOUR`) on the
  academic day before the event, on the university's clock. An event published
  after that moment gets no official reminder.
- **Personal reminders** are sent as `remind_at_local`. Responses include
  `remind_at` (UTC), `remind_at_local` and `timezone`.
- **Start-up refuses** to run while any university lacks a valid zone.

`ACADEMICAI_CONTEXT.md` section 20 has the full rule, including daylight-saving
edge cases and the migration.

## Personal reminder states

Personal reminders use `PENDING | SENT | CANCELLED`. There is deliberately **no
`COMPLETED` state**.

"Cancel reminder" and finishing the underlying academic work are separate
concepts, and they already have separate mechanisms: cancelling a reminder
stops the nudge, while marking an official event complete is per-student state
recorded in `personal_event_completions` and reached from the calendar. A
dedicated `COMPLETED` reminder state may be reconsidered during UI/UX and
product refinement; it would require a schema change, so it is not being
introduced now.

## Known MVP limitations

These are deliberate and documented rather than hidden:

- **The email-domain registry covers four universities only.** It is
  intentionally small: a university is added once its student domain has been
  confirmed, never by relaxing the matching rule.
- **A valid institutional domain is not proof of enrolment.** It shows control
  of an address on an approved domain. Alumni, deferred students, and staff on
  a shared institutional domain (UNILAG's `unilag.edu.ng` is shared) would all
  pass Gate 1.
- **There is no identity verification at all.** Student ID-card scanning was
  removed from the MVP. The product knows that someone controls an approved
  institutional email address and nothing more: not that they are the person
  named on the account, not that the Matric Number they typed is theirs, and
  not that they are enrolled. Anyone with a valid address on an approved domain
  can register, and a community's own members are the only check on who joins
  it. This is the single largest assurance gap in the product and it is
  deliberate.
- **Best-effort erasure, not secure wipe.** The temporary file is overwritten
  before unlinking, but on a journalling or copy-on-write filesystem that does
  not guarantee the old blocks are unrecoverable. It is defence against casual
  recovery, not forensic erasure.
- **No real-browser E2E.** UI tests run in jsdom via vitest. End-to-end flows
  are covered at the API level plus an HTTP smoke test. Playwright has not been
  run.
- **PostgreSQL is untested.** The dialect boundary is isolated to
  `db/schema.sql` and application SQL is standard, but nothing has been executed
  against PostgreSQL. Treat the migration as unvalidated work, not a
  configuration switch.
- **Rate limiting is in-process.** A multi-process deployment needs a shared
  store. Call sites will not change.
- **No per-user timezones.** A student reads their university's academic clock
  (`universities.timezone`). Official reminders fire at 08:00 on that clock, one
  day before the deadline, by design.
- **Email delivery backends are `console` and `memory` only.** Wiring a real
  SMTP or transactional-email provider is outstanding; the outbox, retry and
  status machinery around it is complete and tested.
- **Rep elections need 4 eligible members**, not 3. See the election section.
