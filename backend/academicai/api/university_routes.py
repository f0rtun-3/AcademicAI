"""Public university registry (spec: institutional email domains).

Read-only. The registry is backend state; this endpoint exists so the sign-up
form can show which universities are supported and what domain each expects,
without the client holding its own copy that could drift from the rule the
backend actually enforces.
"""
from flask import Blueprint

from ..security import rate_limit
from ..services import email_domain_service
from .helpers import ok

bp = Blueprint("universities", __name__, url_prefix="/api/universities")


@bp.get("")
def list_universities():
    # Public: needed before an account exists. Rate limited all the same.
    rate_limit.limit("universities", max_hits=60, per_seconds=300)
    return ok({"universities": email_domain_service.supported_universities()})
