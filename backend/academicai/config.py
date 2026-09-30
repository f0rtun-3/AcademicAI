"""Application configuration. Secrets come from environment variables (spec 25)."""
import os
import sys
from pathlib import Path

# The project root: backend/academicai/config.py -> ../../
ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path=None):
    """Read key=value pairs from the project's .env into the environment.

    .env.example has always told the reader to "copy to .env and fill in", but
    nothing read the file, so a pasted API key sat there doing nothing and the
    only symptom was mail that never arrived. This closes that gap.

    A REAL ENVIRONMENT VARIABLE ALWAYS WINS. .env supplies defaults for local
    development; it must never override what a deployment actually exported,
    or a stale local file would silently reconfigure production.

    Hand-parsed rather than pulled from python-dotenv: the project has no
    third-party runtime dependencies beyond Flask, and this is a dozen lines.
    """
    path = Path(path) if path else ROOT / ".env"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}                      # no .env is the normal case, not an error

    loaded = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        # Strip one matching pair of surrounding quotes, so a value with
        # spaces - "AcademicAI <onboarding@resend.dev>" - survives intact.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


# Must run before the Config class body below, which reads os.environ as it is
# evaluated at import time.
#
# NEVER under pytest. The suite has to be hermetic: if it read the developer's
# .env, a local ACADEMICAI_EMAIL_BACKEND=resend would point tests at a real
# provider, and a real secret key would mask the test that checks production
# refuses the packaged default. Whoever runs the suite must get the same
# result regardless of what is on their machine.
if "pytest" not in sys.modules:
    load_dotenv()


def _bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class Config:
    # DATABASE ENGINE. SQLite is the default, for local development and tests;
    # production must run on PostgreSQL, and refuses to start on SQLite (see
    # app._validate_production_config). The PostgreSQL backend is
    # db/postgres.py; the application's SQL is the same for both.
    DATABASE_BACKEND = os.environ.get("ACADEMICAI_DATABASE_BACKEND", "sqlite").strip().lower()
    # postgresql://user:password@host:5432/dbname - a secret, like the key below.
    DATABASE_URL = os.environ.get("ACADEMICAI_DATABASE_URL")
    DB_POOL_MIN = int(os.environ.get("ACADEMICAI_DB_POOL_MIN", "1"))
    DB_POOL_MAX = int(os.environ.get("ACADEMICAI_DB_POOL_MAX", "10"))

    # Database path is configurable so deployment can point it at a persistent
    # volume rather than an ephemeral filesystem (spec 32).
    DATABASE_PATH = os.environ.get("ACADEMICAI_DB_PATH", "instance/academicai.db")
    # How long a writer waits for the write lock before DatabaseBusy (503).
    # SQLite's busy_timeout; on PostgreSQL, the session's lock_timeout.
    SQLITE_BUSY_TIMEOUT_MS = int(os.environ.get("ACADEMICAI_BUSY_TIMEOUT_MS", "5000"))
    SQLITE_WAL = _bool("ACADEMICAI_SQLITE_WAL", True)

    ENV = os.environ.get("ACADEMICAI_ENV", "development")
    DEFAULT_SECRET_KEY = "dev-insecure-secret-change-me"
    SECRET_KEY = os.environ.get("ACADEMICAI_SECRET_KEY", DEFAULT_SECRET_KEY)
    SESSION_TTL_HOURS = int(os.environ.get("ACADEMICAI_SESSION_TTL_HOURS", "24"))
    RESET_TOKEN_TTL_HOURS = int(os.environ.get("ACADEMICAI_RESET_TOKEN_TTL_HOURS", "2"))

    # Ballot rules (spec 11, 12). Values are policy, not magic numbers.
    BALLOT_DURATION_HOURS = int(os.environ.get("ACADEMICAI_BALLOT_HOURS", "24"))
    BALLOT_MIN_VOTES = int(os.environ.get("ACADEMICAI_BALLOT_MIN_VOTES", "3"))
    MAX_REPS_PER_COMMUNITY = int(os.environ.get("ACADEMICAI_MAX_REPS", "3"))
    FAILED_CANDIDATE_COOLDOWN_DAYS = int(os.environ.get("ACADEMICAI_CANDIDATE_COOLDOWN_DAYS", "7"))
    REMOVAL_RETRY_COOLDOWN_DAYS = int(os.environ.get("ACADEMICAI_REMOVAL_COOLDOWN_DAYS", "7"))
    # A community may PREPARE for its first election at this size, but a ballot
    # can only be OPENED when there are BALLOT_MIN_VOTES eligible voters besides
    # the candidate - a candidate may not vote for themselves, so a ballot opened
    # below that threshold could never reach the minimum vote count (spec 8, 11).
    MIN_ELECTION_PREPARATION = int(os.environ.get("ACADEMICAI_MIN_ELECTORATE", "3"))

    # Official reminder policy (spec 20): REMINDER_HOUR o'clock on the academic
    # day REMINDER_LEAD_DAYS before the event, on the UNIVERSITY'S clock
    # (universities.timezone) - never server time, never UTC. There is no
    # per-user timezone; a student reads their university's clock.
    REMINDER_LEAD_DAYS = int(os.environ.get("ACADEMICAI_REMINDER_LEAD_DAYS", "1"))
    REMINDER_HOUR = int(os.environ.get("ACADEMICAI_REMINDER_HOUR", "8"))

    PASSWORD_HASH_ITERATIONS = int(os.environ.get("ACADEMICAI_PBKDF2_ITERATIONS", "260000"))
    MAX_MESSAGE_LENGTH = int(os.environ.get("ACADEMICAI_MAX_MESSAGE_LENGTH", "4000"))

    # Request ceiling, so an oversized body is refused before it is buffered.
    # This is the OUTER limit; supporting material has its own, smaller cap
    # below, checked while the stream is read.
    MAX_CONTENT_LENGTH = int(os.environ.get("ACADEMICAI_MAX_CONTENT_LENGTH",
                                            str(12 * 1024 * 1024)))

    # Supporting material for an assignment or project: the ORIGINAL brief,
    # when a lecturer gave one as a file. Optional everywhere it appears.
    #
    # The directory is configurable for the same reason DATABASE_PATH is: on a
    # deployment with an ephemeral filesystem it has to point at a volume. It
    # is never inside the static root, and nothing under it is ever served by
    # path - every read goes through an authorised route.
    UPLOAD_DIR = os.environ.get("ACADEMICAI_UPLOAD_DIR", "instance/uploads")
    MAX_ATTACHMENT_BYTES = int(os.environ.get("ACADEMICAI_MAX_ATTACHMENT_BYTES",
                                              str(10 * 1024 * 1024)))
    MAX_ATTACHMENTS_PER_EVENT = int(
        os.environ.get("ACADEMICAI_MAX_ATTACHMENTS_PER_EVENT", "5"))
    AI_PROVIDER = os.environ.get("ACADEMICAI_AI_PROVIDER", "heuristic")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL = os.environ.get("ACADEMICAI_ANTHROPIC_MODEL", "claude-opus-5")

    # MVP SCOPE: student ID-card verification has been REMOVED from the
    # product, so there is deliberately no IDENTITY_PROVIDER,
    # IDENTITY_VISION_PROVIDER, IDENTITY_VISION_FIXTURE or TESSERACT_CMD here.
    # Leaving any of them would offer a switch that appears to turn identity
    # scanning back on while no code implements it. Email verification against
    # the approved institutional-domain registry is the account gate; see
    # services/email_domain_service.py.
    # EMAIL DELIVERY
    # --------------
    # "memory" and "console" do not send anything. They are development and
    # test backends and they SAY SO: a message handled by either is recorded as
    # simulated, never as sent. "resend" is the only backend that puts mail on
    # the wire (services/email_service.py).
    EMAIL_BACKEND = os.environ.get("ACADEMICAI_EMAIL_BACKEND", "console")
    EMAIL_FROM = os.environ.get("ACADEMICAI_EMAIL_FROM",
                                "AcademicAI <onboarding@resend.dev>")
    RESEND_API_KEY = os.environ.get("ACADEMICAI_RESEND_API_KEY")
    RESEND_API_URL = os.environ.get("ACADEMICAI_RESEND_API_URL",
                                    "https://api.resend.com/emails")
    EMAIL_TIMEOUT_SECONDS = int(os.environ.get("ACADEMICAI_EMAIL_TIMEOUT", "15"))

    # EMAIL VERIFICATION CODE (OTP)
    # -----------------------------
    # Six digits is 10^6 possibilities, which is only safe because all three of
    # these hold at once: a code lives for minutes not hours, a single code
    # tolerates a handful of wrong guesses before it is destroyed, and the
    # endpoint is rate limited per account. Raising the TTL or the attempt
    # ceiling weakens the other two, so they are policy, not preference.
    OTP_LENGTH = 6
    OTP_TTL_MINUTES = int(os.environ.get("ACADEMICAI_OTP_TTL_MINUTES", "10"))
    OTP_MAX_ATTEMPTS = int(os.environ.get("ACADEMICAI_OTP_MAX_ATTEMPTS", "5"))
    OTP_RESEND_COOLDOWN_SECONDS = int(
        os.environ.get("ACADEMICAI_OTP_RESEND_COOLDOWN_SECONDS", "60"))

    # DEVELOPMENT ESCAPE HATCH - institutional domain check.
    #
    # Registration normally requires the address to sit on a domain approved
    # for the selected university. That is the ONLY evidence of affiliation the
    # product has, so it is never relaxed in production: setting this there
    # REFUSES THE START (see app._validate_production_config), and the check
    # itself ignores the flag whenever ENV is production, so a misread
    # environment cannot open the gate either.
    #
    # It exists because a transactional email provider in test mode will only
    # deliver to the account owner's own address, which is rarely an
    # institutional one - so end-to-end delivery cannot otherwise be exercised.
    ALLOW_ANY_EMAIL_DOMAIN = _bool("ACADEMICAI_ALLOW_ANY_EMAIL_DOMAIN", False)

    # ── EMAIL VERIFICATION: ON OR OFF ─────────────────────────────────────
    #
    # True (the default) is the real product: register -> six-digit code by
    # email -> verify -> access. The OTP implementation is untouched by this
    # switch; the switch only decides whether that flow RUNS.
    #
    # False creates accounts already marked verified, generates no code and
    # sends no email. It exists for one situation: a transactional email
    # provider in test mode delivers only to the account owner, so a public
    # demo cannot mail its students at all, and every registration would strand
    # somebody on a verification screen they can never pass.
    #
    # WHAT IT COSTS. Nothing else is relaxed - the institutional-domain rule,
    # duplicate detection, password hashing and every authorisation check are
    # exactly as before. What is lost is precisely this: proof that the person
    # registering can read mail at the address they typed. Anyone who knows the
    # shape of a valid student address can register as anyone.
    EMAIL_VERIFICATION_REQUIRED = _bool("ACADEMICAI_EMAIL_VERIFICATION_REQUIRED", True)

    # The acknowledgement that makes the line above deployable.
    #
    # Turning verification off in production REFUSES THE START unless this
    # says "demo". The point is that nobody can reach a production deployment
    # with unverified signups by setting one flag and forgetting - it takes a
    # second, differently-named variable whose only purpose is to say "yes, I
    # know this deployment does not verify email ownership".
    DEPLOYMENT_MODE = os.environ.get("ACADEMICAI_DEPLOYMENT_MODE", "standard").strip().lower()

    RATE_LIMIT_ENABLED = _bool("ACADEMICAI_RATE_LIMIT", True)
    TESTING = False


class TestConfig(Config):
    DATABASE_BACKEND = "sqlite"
    DATABASE_PATH = ":memory:"
    TESTING = True
    SECRET_KEY = "test-secret"
    AI_PROVIDER = "heuristic"
    EMAIL_BACKEND = "memory"
    # The suite exercises the REAL flow; tests that want it off
    # turn it off themselves, so the default cannot drift.
    EMAIL_VERIFICATION_REQUIRED = True
    RATE_LIMIT_ENABLED = False
    # Cheap KDF for tests only. Production keeps the expensive default.
    PASSWORD_HASH_ITERATIONS = 1000
