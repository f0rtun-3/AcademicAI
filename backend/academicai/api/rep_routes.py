"""Rep verification and removal endpoints (spec 27)."""
from flask import Blueprint, g

from ..errors import ValidationError
from ..security import authz
from ..services import removal_service, rep_service
from .helpers import body, ok

bp = Blueprint("rep", __name__, url_prefix="/api/rep")


@bp.post("/nominate")
@authz.require_member
def nominate():
    data = body()
    candidate_id = data.get("candidate_id", g.current_user["id"])
    if not isinstance(candidate_id, int):
        raise ValidationError("candidate_id must be an integer.")
    nomination = rep_service.nominate(g.current_user["id"], g.community_id, candidate_id)
    return ok({"nomination": rep_service.results(g.current_user["id"], nomination["id"])}, 201)


@bp.get("/candidates")
@authz.require_member
def candidates():
    rows = rep_service.list_candidates(g.community_id)
    return ok({"candidates": [rep_service.ballot_view(g.current_user["id"], r)
                              for r in rows]})


@bp.post("/candidates/<int:nomination_id>/vote")
@authz.require_member
def vote(nomination_id):
    counts = rep_service.cast_vote(g.current_user["id"], nomination_id,
                                   (body().get("vote") or "").upper())
    return ok({"tally": counts}, 201)


@bp.get("/candidates/<int:nomination_id>/results")
@authz.require_member
def candidate_results(nomination_id):
    return ok({"results": rep_service.results(g.current_user["id"], nomination_id)})


@bp.post("/removals")
@authz.require_rep
def open_removal():
    target_id = body().get("target_user_id")
    if not isinstance(target_id, int):
        raise ValidationError("target_user_id must be an integer.")
    removal = removal_service.open_removal(g.current_user["id"], g.community_id, target_id)
    return ok({"removal": removal_service.results(g.current_user["id"], removal["id"])}, 201)


@bp.get("/removals")
@authz.require_member
def list_removals():
    rows = removal_service.list_removals(g.community_id)
    return ok({"removals": [removal_service.removal_view(g.current_user["id"], r)
                            for r in rows]})


@bp.post("/removals/<int:removal_id>/vote")
@authz.require_member
def removal_vote(removal_id):
    counts = removal_service.cast_vote(g.current_user["id"], removal_id,
                                       (body().get("vote") or "").upper())
    return ok({"tally": counts}, 201)


@bp.get("/removals/<int:removal_id>/results")
@authz.require_member
def removal_results(removal_id):
    return ok({"results": removal_service.results(g.current_user["id"], removal_id)})
