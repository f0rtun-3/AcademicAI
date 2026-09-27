"""Authentication endpoints (spec 27)."""
import logging

from flask import Blueprint, current_app, g

from .. import academic_time
from ..errors import ConflictError, ValidationError
from ..security import authz, rate_limit
from ..services import (auth_service, email_service, email_templates,
                        membership_service)
from .helpers import body, ok

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


log = logging.getLogger("academicai.auth")


def _send_verification_code(user, code):
    """Email one verification code, and report honestly what happened.

    Delivery failure must not roll back the account action that triggered it -
    the account exists, and the user can ask for another code. But it must not
    be SILENT either, which is what the old `except Exception: pass` made it.
    The outcome is returned so the response can say whether an email is
    actually on its way, and the failure is logged so it is diagnosable.

    `user["email"]` is the only possible destination. No caller passes an
    address, so a code cannot be aimed at a mailbox other than the account's.
    """
    ttl = current_app.config["OTP_TTL_MINUTES"]
    subject, text, html = email_templates.verification_code_email(code, ttl)
    try:
        result = email_service.send(user["email"], subject, text, html=html)
    except Exception as exc:  # noqa: BLE001 - any provider failure is the same here
        log.warning("verification email failed for user=%s: %s", user["id"], exc)
        return {"email_delivered": False, "email_error": str(exc)[:200]}
    if not result.delivered:
        log.info("verification code for %s was simulated (%s backend)",
                 user["email"], result.backend)
    return {"email_delivered": result.delivered, "email_backend": result.backend}


def _require_verification_enabled():
    """Refuse the OTP endpoints when the deployment does not use them.

    Without this they would not error - they would quietly misbehave. Resend
    would raise "already verified" (confusing, since nobody verified anything)
    and verify-email would report an incorrect code for every code, because no
    code was ever issued. A plain statement of the actual situation is better
    than either.
    """
    if not current_app.config["EMAIL_VERIFICATION_REQUIRED"]:
        raise ConflictError(
            "Email verification is not enabled on this deployment.",
            details={"email_verification_required": False})


def _resolve_unverified_user(data):
    """Whose code is being checked.

    The session is preferred: after registering, the client is signed in, and
    an authenticated request cannot be pointed at another account. Falling back
    to the address in the body keeps the endpoint usable for a client that has
    no session yet - it still proves nothing on its own, because the code was
    only ever sent to that account's own mailbox.
    """
    if getattr(g, "current_user", None) is not None:
        return g.current_user
    email = data.get("email")
    if not email:
        raise ValidationError("Enter the email address you registered with.")
    user = auth_service.find_by_email(email)
    if user is None:
        # Same answer as a wrong code, so this cannot enumerate accounts.
        raise ValidationError("That code is not correct.")
    return user


@bp.post("/register")
def register():
    rate_limit.limit("register", max_hits=5, per_seconds=3600)
    user, code = auth_service.register(body())

    if code is None:
        # Verification is switched off for this deployment. No code was minted
        # and none is sent. next_step is COMPUTED rather than asserted, so the
        # client is routed by the account's real state instead of being told
        # to visit a screen that has nothing to do.
        payload = {
            "user": auth_service.public_user(user),
            "next_step": _next_step(user, None, None),
            "email_verification_required": False,
            "email_delivered": False,
        }
        log.info("account %s created without email verification "
                 "(ACADEMICAI_EMAIL_VERIFICATION_REQUIRED is off)", user["id"])
        return ok(payload, 201)

    delivery = _send_verification_code(user, code)
    payload = {"user": auth_service.public_user(user),
               "next_step": "verify_email",
               "email_verification_required": True, **delivery}
    # The code is returned directly only under TESTING, so the suite does not
    # need a mail server. It is NOT returned in development: a developer reads
    # it from the console backend's output, and a code in an API response is a
    # habit that must not be able to reach production.
    if current_app.config.get("TESTING"):
        payload["verification_code"] = code
    return ok(payload, 201)


@bp.post("/verify-email")
@authz.optional_auth
def verify_email():
    """Check a six-digit code against the account's own live code.

    Two independent brakes on guessing, because six digits is a small space:
    this per-account request limit, and the per-code attempt ceiling enforced
    in auth_service. The first stops a flood; the second means a flood that
    does get through burns the code rather than eventually finding it.
    """
    _require_verification_enabled()
    data = body()
    user = _resolve_unverified_user(data)
    rate_limit.limit("verify_email", max_hits=10, per_seconds=900,
                     key=str(user["id"]))
    verified = auth_service.verify_email(user["id"], data.get("code"))
    return ok({"user": auth_service.public_user(verified),
               "next_step": "community_setup"})


@bp.post("/resend-verification")
@authz.require_auth
def resend_verification():
    _require_verification_enabled()
    rate_limit.limit("resend", max_hits=5, per_seconds=3600, key=str(g.current_user["id"]))
    # The short cooldown lives in auth_service, with the issuing, so that every
    # path that mints a code is covered by it rather than only this route.
    code = auth_service.resend_email_verification(g.current_user["id"])
    delivery = _send_verification_code(g.current_user, code)
    payload = {"status": "sent", "resend_after_seconds":
               current_app.config["OTP_RESEND_COOLDOWN_SECONDS"], **delivery}
    if current_app.config.get("TESTING"):
        payload["verification_code"] = code
    return ok(payload)


@bp.post("/login")
def login():
    data = body()
    rate_limit.limit("login", max_hits=10, per_seconds=900)
    user, token = auth_service.login(data.get("email"), data.get("password"))
    return ok({"token": token, "user": auth_service.public_user(user)})


@bp.post("/logout")
@authz.require_auth
def logout():
    from flask import request
    header = request.headers.get("Authorization", "")
    auth_service.logout(header[7:].strip() if header.startswith("Bearer ") else None)
    return ok({"status": "logged_out"})


@bp.post("/change-email")
@authz.require_auth
def change_email():
    """Change the signed-in account's email address (J·3).

    This route adds NO policy of its own. Every rule already lives in
    auth_service.change_email(), which re-runs institutional-domain validation
    (Gate 1), clears email_verified, invalidates outstanding verification links
    and revokes every session including this one. The caller is therefore
    logged out by its own request and must verify the new address before
    continuing - which is the point, and must not be softened here.

    Rate limited per account: an authenticated endpoint that emails an
    arbitrary address is a spam vector otherwise.
    """
    rate_limit.limit("change_email", max_hits=5, per_seconds=3600,
                     key=str(g.current_user["id"]))
    user, code = auth_service.change_email(g.current_user["id"], body().get("email"))
    delivery = _send_verification_code(user, code)
    payload = {
        **delivery,
        "user": auth_service.public_user(user),
        # Stated so the client can explain what just happened rather than
        # discovering it as an unexplained 401 on the next request.
        "email_verified": False,
        "sessions_revoked": True,
        "next_step": "verify_email",
    }
    if current_app.config.get("TESTING"):
        payload["verification_code"] = code
    return ok(payload)


@bp.post("/forgot-password")
def forgot_password():
    rate_limit.limit("forgot", max_hits=5, per_seconds=3600)
    data = body()
    token = auth_service.request_password_reset(data.get("email"))
    if token:
        # Still a long link token, deliberately: a reset is not a six-digit
        # flow and shortening it would weaken it for no gain.
        try:
            email_service.send(
                data.get("email"), "Reset your AcademicAI password",
                f"Use this code to reset your password:\n\n{token}\n")
        except Exception as exc:  # noqa: BLE001
            log.warning("password reset email failed: %s", exc)
    # Identical response whether or not the account exists (account enumeration).
    payload = {"status": "sent"}
    if current_app.config.get("TESTING") and token:
        payload["reset_token"] = token
    return ok(payload)


@bp.post("/reset-password")
def reset_password():
    rate_limit.limit("reset", max_hits=10, per_seconds=3600)
    data = body()
    auth_service.reset_password(data.get("token"), data.get("password"),
                                data.get("confirm_password"))
    return ok({"status": "password_reset"})


@bp.get("/me")
@authz.require_auth
def me():
    user = g.current_user
    membership = authz.active_membership(user["id"])
    pending = membership_service.pending_request(user["id"])
    return ok({
        "user": auth_service.public_user(user),
        "membership": _membership_payload(membership),
        "pending_membership": _membership_payload(pending),
        "next_step": _next_step(user, membership, pending),
        # The academic clock this student reads (their community's university,
        # or the one they registered with). The interface shows every event
        # and reminder time in this IANA zone, whatever the device is set to.
        "timezone": academic_time.zone_name_for_user(user["id"]),
    })


def _membership_payload(membership):
    if membership is None:
        return None
    return {
        "community_id": membership["community_id"],
        "status": membership["status"],
        "role": membership["role"],
    }


def _next_step(user, membership, pending):
    """Drives onboarding UI so the client never routes to a screen that 403s (spec 9).

    MVP SCOPE: there is no "verify_identity" step. Student ID-card verification
    was removed from the product, so email verification leads straight to
    community setup. The client's STEPS map must not carry a dead state either.
    """
    if not user["email_verified"]:
        return "verify_email"
    if membership is not None:
        return "dashboard"
    if pending is not None:
        return "awaiting_approval"
    return "community_setup"
