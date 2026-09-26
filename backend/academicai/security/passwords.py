"""Password hashing (spec 25). PBKDF2-SHA256 with a per-password salt.

The iteration count is configurable so the test suite can use a cheap factor
without changing the production default, which stays deliberately expensive.
"""
import re

from werkzeug.security import check_password_hash, generate_password_hash

from ..errors import ValidationError

MIN_LENGTH = 8
DEFAULT_ITERATIONS = 260000


def _iterations():
    try:
        from flask import current_app
        return int(current_app.config.get("PASSWORD_HASH_ITERATIONS", DEFAULT_ITERATIONS))
    except Exception:
        return DEFAULT_ITERATIONS


def validate_password(password, confirm=None):
    if not isinstance(password, str) or len(password) < MIN_LENGTH:
        raise ValidationError(f"Password must be at least {MIN_LENGTH} characters.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValidationError("Password must contain at least one letter and one number.")
    if confirm is not None and password != confirm:
        raise ValidationError("Passwords do not match.")
    return password


def hash_password(password):
    return generate_password_hash(password, method=f"pbkdf2:sha256:{_iterations()}")


def verify_password(password_hash, password):
    if not password_hash or not isinstance(password, str):
        return False
    return check_password_hash(password_hash, password)
