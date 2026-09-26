"""Opaque token generation and storage.

Tokens are random 256-bit values shown to the user once. Only a SHA-256 hash is
stored, so a database read cannot be replayed as a session or reset token.
"""
import hashlib
import hmac
import secrets


def generate_token():
    return secrets.token_urlsafe(32)


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(a, b):
    return hmac.compare_digest(a or "", b or "")


# ── One-time codes ─────────────────────────────────────────────────────────
#
# A verification code is a DIFFERENT kind of secret from a session token and
# must not be stored the same way.
#
# `hash_token` is a bare SHA-256, which is correct for a 256-bit token: there
# is nothing to enumerate. A six-digit code has only a million possible values,
# so a bare digest of one can be reversed by hashing all million — about a
# millisecond of work for anyone who reads the database. The stored value would
# be plaintext in all but name.
#
# So a code is stored as an HMAC keyed with the application secret, over a
# per-row random salt and the account id. Three consequences, all wanted:
#
#   * a database read alone is useless — the attacker also needs SECRET_KEY
#   * the same code issued to two accounts stores two different digests, so a
#     digest never reveals that two people hold the same code
#   * the salt keeps the digest unique per row, which the table's UNIQUE
#     constraint on token_hash requires

def generate_code(digits=6):
    """A uniformly random decimal code, zero-padded, from the OS CSPRNG.

    `secrets.randbelow` is used rather than `random`: the latter is a Mersenne
    Twister whose output is predictable from previous draws.
    """
    return f"{secrets.randbelow(10 ** digits):0{digits}d}"


def generate_salt():
    return secrets.token_hex(16)


def hash_code(code, salt, user_id, secret):
    """Keyed digest of a one-time code. See the note above for why HMAC."""
    message = f"{salt}:{user_id}:{code}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def codes_equal(a, b):
    """Constant-time comparison, so a wrong guess cannot be narrowed by timing."""
    return hmac.compare_digest(a or "", b or "")
