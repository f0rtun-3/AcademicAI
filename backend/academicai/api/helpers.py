"""Shared helpers for route modules."""
from flask import jsonify, request

from ..errors import ValidationError


def body():
    """Parsed JSON object body. Rejects anything that is not a JSON object."""
    data = request.get_json(silent=True)
    if data is None:
        raise ValidationError("A JSON request body is required.")
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")
    return data


def ok(payload=None, status=200):
    return jsonify(payload if payload is not None else {}), status


def rows_to_list(rows, projector):
    return [projector(r) for r in rows]


def int_arg(name, default=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} must be an integer.")
    if maximum is not None and value > maximum:
        return maximum
    return value
