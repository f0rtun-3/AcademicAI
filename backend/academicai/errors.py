"""Application error types.

Each maps to one HTTP status. Messages are safe to return to clients:
no sensitive student data, no stack details, no SQL (spec 25).
"""


class ApiError(Exception):
    status = 400
    code = "error"

    def __init__(self, message, status=None, code=None, details=None):
        super().__init__(message)
        self.message = message
        if status is not None:
            self.status = status
        if code is not None:
            self.code = code
        self.details = details or {}

    def to_dict(self):
        payload = {"error": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class ValidationError(ApiError):
    status = 400
    code = "validation_error"


class AuthenticationError(ApiError):
    status = 401
    code = "authentication_required"


class AuthorizationError(ApiError):
    status = 403
    code = "forbidden"


class NotFoundError(ApiError):
    status = 404
    code = "not_found"


class ConflictError(ApiError):
    """409. Used for stale proposals and duplicate-state conflicts (spec 17)."""
    status = 409
    code = "conflict"


class StaleProposalError(ConflictError):
    code = "stale_proposal"


class RateLimitError(ApiError):
    status = 429
    code = "rate_limited"


class ServiceUnavailableError(ApiError):
    status = 503
    code = "service_unavailable"
