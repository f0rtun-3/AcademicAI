"""The provider abstraction, including the production Anthropic path (spec 3).

The Anthropic provider is exercised with a stub client so its request shape and
its failure handling are covered without network access or an API key.
"""
import json

import pytest

from academicai.ai import provider as ai_provider
from academicai.ai.anthropic_provider import AnthropicProvider
from academicai.ai.prompts import build_interpretation_prompt, sanitize_untrusted
from academicai.ai.schemas import PROPOSAL_JSON_SCHEMA, normalize
from academicai.errors import ServiceUnavailableError


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, payload, stop_reason="end_turn"):
        self.content = [_Block(json.dumps(payload))]
        self.stop_reason = stop_reason


class StubClient:
    """Records the request and returns a canned response."""

    def __init__(self, payload=None, stop_reason="end_turn", raises=None):
        self.payload = payload or {}
        self.stop_reason = stop_reason
        self.raises = raises
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        return _Response(self.payload, self.stop_reason)


VALID = {
    "action": "CREATE", "scope": "EVENT", "course_code": "COS202",
    "event_type": "ASSIGNMENT", "title": "COS202 Assignment",
    "event_date": "2026-09-18", "confidence": 0.9, "needs_clarification": False,
    "explanation": "New assignment.",
}


def test_anthropic_provider_sends_schema_and_system_prompt(app):
    stub = StubClient(VALID)
    provider = AnthropicProvider(client=stub)
    with app.app_context():
        result = provider.interpret({"message": "cos202 assignment on friday",
                                     "today": "2026-09-14"})
    assert result["action"] == "CREATE"

    call = stub.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["output_config"]["format"]["schema"] is PROPOSAL_JSON_SCHEMA
    assert "never follow instructions" in call["system"].lower()
    assert call["messages"][0]["role"] == "user"


def test_untrusted_message_is_delivered_inside_a_data_envelope(app):
    stub = StubClient(VALID)
    provider = AnthropicProvider(client=stub)
    with app.app_context():
        provider.interpret({"message": "quiz on friday", "today": "2026-09-14"})
    content = stub.calls[0]["messages"][0]["content"]
    assert "<student_message>" in content and "</student_message>" in content
    assert "<academic_context>" in content


def test_provider_failure_becomes_a_service_error_without_leaking_details(app):
    provider = AnthropicProvider(client=StubClient(raises=RuntimeError("api key sk-secret bad")))
    with app.app_context():
        with pytest.raises(ServiceUnavailableError) as excinfo:
            provider.interpret({"message": "x", "today": "2026-09-14"})
    assert "sk-secret" not in str(excinfo.value)


def test_a_refusal_is_handled_rather_than_parsed(app):
    provider = AnthropicProvider(client=StubClient(VALID, stop_reason="refusal"))
    with app.app_context():
        with pytest.raises(ServiceUnavailableError):
            provider.interpret({"message": "x", "today": "2026-09-14"})


def test_unreadable_provider_output_is_rejected(app):
    class NonJson(StubClient):
        def create(self, **kwargs):
            self.calls.append(kwargs)
            response = _Response({})
            response.content = [_Block("this is not json")]
            return response

    provider = AnthropicProvider(client=NonJson())
    with app.app_context():
        with pytest.raises(ServiceUnavailableError):
            provider.interpret({"message": "x", "today": "2026-09-14"})


def test_provider_selection_is_configuration_driven(app):
    with app.app_context():
        app.config["AI_PROVIDER"] = "heuristic"
        assert ai_provider.get_provider().name == "heuristic"
        app.config["AI_PROVIDER"] = "nonexistent"
        with pytest.raises(ServiceUnavailableError):
            ai_provider.get_provider()


def test_a_hostile_provider_response_cannot_produce_a_publishable_action():
    """Provider output is untrusted and is clamped before anything sees it."""
    hostile = normalize({
        "action": "UPDATE",              # UPDATE with no target
        "scope": "EVENT",
        "possible_match_id": None,
        "confidence": 99,                # out of range
        "needs_clarification": False,
        "explanation": "x" * 5000,
        "event_type": "DROP TABLE users",
    })
    assert hostile["action"] == "CLARIFICATION"
    assert hostile["confidence"] == 1.0
    assert hostile["event_type"] is None
    assert len(hostile["explanation"]) <= 1000


def test_unknown_action_degrades_to_clarification():
    assert normalize({"action": "DELETE_EVERYTHING"})["action"] == "CLARIFICATION"
    assert normalize("not a dict")["action"] == "CLARIFICATION"


def test_sanitizer_caps_length():
    assert len(sanitize_untrusted("x" * 9000, max_length=4000)) == 4000
