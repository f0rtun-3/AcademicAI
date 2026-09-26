"""Anthropic-backed provider (spec 3).

Uses the Messages API with a JSON-schema constrained response so the proposal
shape is guaranteed before it reaches the normaliser. The model proposes only:
the backend still authorises, revalidates and applies every change.
"""
import json
import logging

from flask import current_app

from ..errors import ServiceUnavailableError
from .prompts import (CHAT_SYSTEM_PROMPT, INTERPRETATION_SYSTEM_PROMPT,
                      build_chat_prompt, build_interpretation_prompt)
from .provider import AIProvider
from .schemas import PROPOSAL_JSON_SCHEMA

log = logging.getLogger("academicai.ai")

CHAT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "grounded": {"type": "boolean"},
        "referenced_event_ids": {"type": "array", "items": {"type": "integer"}},
        "suggested_reminder": {
            "type": ["object", "null"],
            "properties": {"title": {"type": "string"}, "remind_at": {"type": "string"}},
            "required": ["title", "remind_at"],
            "additionalProperties": False,
        },
    },
    "required": ["answer", "grounded"],
    "additionalProperties": False,
}


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, client=None):
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:
            raise ServiceUnavailableError(
                "The AI service is not available.") from exc
        api_key = current_app.config.get("ANTHROPIC_API_KEY")
        # An unset key is valid: the SDK also resolves an `ant auth login` profile.
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        return self._client

    def _call(self, system, user_content, schema):
        client = self._get_client()
        try:
            response = client.messages.create(
                model=current_app.config.get("ANTHROPIC_MODEL", "claude-opus-5"),
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": user_content}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except Exception as exc:
            # Never leak provider internals or the message content to the client.
            log.exception("AI provider call failed")
            raise ServiceUnavailableError(
                "The AI service is temporarily unavailable. Please try again.") from exc

        if getattr(response, "stop_reason", None) == "refusal":
            raise ServiceUnavailableError(
                "The AI service declined to process this message.")
        try:
            text = next(block.text for block in response.content if block.type == "text")
            return json.loads(text)
        except (StopIteration, ValueError, AttributeError) as exc:
            log.warning("AI provider returned an unreadable response")
            raise ServiceUnavailableError(
                "The AI service returned an unreadable response.") from exc

    def interpret(self, request):
        return self._call(INTERPRETATION_SYSTEM_PROMPT,
                          build_interpretation_prompt(request),
                          PROPOSAL_JSON_SCHEMA)

    def answer(self, request):
        return self._call(CHAT_SYSTEM_PROMPT, build_chat_prompt(request), CHAT_JSON_SCHEMA)
