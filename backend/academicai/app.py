"""Flask application factory.

Layering (spec 3): routes handle HTTP only; services own business rules and
state changes; the database is the source of truth. Routes never embed
authorization logic beyond applying a gate decorator.
"""
import logging
import sqlite3

from flask import Flask, current_app, g, jsonify

from .config import Config, TestConfig
from .db.connection import DatabaseBusy, close_db, connect, init_schema
from .errors import ApiError
from .services import email_service

log = logging.getLogger("academicai.app")


def create_app(config_object=None, **overrides):
    app = Flask(__name__)
    app.config.from_object(config_object or Config)
    app.config.update(overrides)

    _validate_production_config(app)
    _init_database(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    app.teardown_appcontext(close_db)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    return app


def _validate_production_config(app):
    """Refuse to start a production deployment with development defaults (spec 25).

    Failing at startup is the only reliable moment to catch this: a placeholder
    secret in production silently makes every session token forgeable.
    """
    if app.config.get("ENV") != "production" or app.config.get("TESTING"):
        return
    problems = []
    if app.config.get("SECRET_KEY") == Config.DEFAULT_SECRET_KEY:
        problems.append("ACADEMICAI_SECRET_KEY is still the development default")
    if app.config.get("DATABASE_PATH") in (":memory:", None, ""):
        problems.append("ACADEMICAI_DB_PATH must point at a persistent file")
    # A production build must be able to SEND. `console` used to pass this
    # check, which meant a deployment could sit there printing verification
    # codes into a log file while every new student waited for an email that
    # was never going to arrive.
    backend = app.config.get("EMAIL_BACKEND")
    if backend not in email_service.DELIVERING_BACKENDS:
        problems.append(
            f"ACADEMICAI_EMAIL_BACKEND is '{backend}', which does not send mail; "
            f"production needs one of {sorted(email_service.DELIVERING_BACKENDS)}")
    elif backend == "resend" and not app.config.get("RESEND_API_KEY"):
        problems.append("ACADEMICAI_RESEND_API_KEY must be set to send email")
    # The institutional-domain check is the only evidence of affiliation the
    # product has. Its development bypass reaching production is a serious
    # enough misconfiguration to refuse the start rather than log and continue.
    if app.config.get("ALLOW_ANY_EMAIL_DOMAIN"):
        problems.append(
            "ACADEMICAI_ALLOW_ANY_EMAIL_DOMAIN must not be set in production; "
            "it disables institutional email verification")

    # Unverified signups in production are allowed ONLY by a second, explicitly
    # named variable. One flag can be set and forgotten; two, with the second
    # saying nothing except "this deployment is a demo", cannot be arrived at
    # by accident. This is the difference between choosing to run a demo and
    # believing you are running the real thing.
    if not app.config.get("EMAIL_VERIFICATION_REQUIRED"):
        if app.config.get("DEPLOYMENT_MODE") != "demo":
            problems.append(
                "ACADEMICAI_EMAIL_VERIFICATION_REQUIRED is false, so nobody's "
                "ownership of their email address is checked. To run a public "
                "demo on those terms, also set ACADEMICAI_DEPLOYMENT_MODE=demo")
        else:
            # Permitted, never silent. This line is what someone reading the
            # logs of a live deployment needs to see.
            log.warning(
                "DEMO DEPLOYMENT: email verification is DISABLED. Accounts are "
                "created already marked verified and nobody's ownership of "
                "their address is checked.")
    if problems:
        raise RuntimeError(
            "Refusing to start in production: " + "; ".join(problems) + ".")


def _init_database(app):
    path = app.config["DATABASE_PATH"]
    if path == ":memory:":
        # One shared connection for the whole app so every request sees the same
        # in-memory database. Used by tests only.
        conn = connect(":memory:", app.config["SQLITE_BUSY_TIMEOUT_MS"], wal=False)
        init_schema(conn)
        app.config["_SHARED_MEMORY_CONN"] = conn
    else:
        app.config["_SHARED_MEMORY_CONN"] = None
        conn = connect(path, app.config["SQLITE_BUSY_TIMEOUT_MS"], app.config["SQLITE_WAL"])
        try:
            init_schema(conn)
        finally:
            conn.close()


def _register_blueprints(app):
    from .api.auth_routes import bp as auth_bp
    from .api.community_routes import bp as community_bp
    from .api.rep_routes import bp as rep_bp
    from .api.university_routes import bp as university_bp
    from .api.academic_routes import bp as academic_bp
    from .api.event_routes import bp as event_bp
    from .api.ai_routes import bp as ai_bp
    from .api.reminder_routes import bp as reminder_bp
    from .api.chat_routes import bp as chat_bp
    from .api.dashboard_routes import bp as dashboard_bp
    from .api.notification_routes import bp as notification_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(community_bp)
    app.register_blueprint(rep_bp)
    app.register_blueprint(university_bp)
    app.register_blueprint(academic_bp)
    app.register_blueprint(event_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(reminder_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(notification_bp)


def _register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(exc.to_dict()), exc.status

    @app.errorhandler(DatabaseBusy)
    def handle_busy(exc):
        # Infrastructure contention is reported as 503, never as a business 409,
        # so a lock failure cannot masquerade as a stale proposal (spec 32).
        current_app.logger.warning("database busy")
        return jsonify({"error": "database_busy",
                        "message": "The service is busy. Please retry."}), 503

    @app.errorhandler(sqlite3.IntegrityError)
    def handle_integrity(exc):
        current_app.logger.warning("integrity error")
        return jsonify({"error": "conflict",
                        "message": "That operation conflicts with existing data."}), 409

    @app.errorhandler(413)
    def handle_too_large(_exc):
        # Raised by Flask when the body exceeds MAX_CONTENT_LENGTH.
        return jsonify({"error": "payload_too_large",
                        "message": "The uploaded file is too large."}), 413

    @app.errorhandler(404)
    def handle_404(_exc):
        return jsonify({"error": "not_found", "message": "Resource not found."}), 404

    @app.errorhandler(405)
    def handle_405(_exc):
        return jsonify({"error": "method_not_allowed", "message": "Method not allowed."}), 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Never leak internals to the client (spec 25).
        current_app.logger.exception("unhandled error")
        if current_app.config.get("TESTING"):
            raise exc
        return jsonify({"error": "internal_error",
                        "message": "Something went wrong."}), 500


def create_test_app(**overrides):
    return create_app(TestConfig, **overrides)
