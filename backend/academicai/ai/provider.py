"""AI provider abstraction (spec 3).

The LLM sits behind this interface so the rest of the system never depends on a
specific model or vendor. Two implementations ship:

  heuristic  - deterministic, offline, no API key. The default for development
               and the entire test suite, so interpretation rules are pinned by
               tests rather than by model behaviour.
  anthropic  - a real LLM via the Anthropic Messages API, for production.

A provider only ever PROPOSES. It never touches the database and never decides
authority (spec 3).
"""
from ..errors import ServiceUnavailableError


class AIProvider:
    name = "base"

    def interpret(self, request):  # pragma: no cover - interface
        """Return a raw proposal dict for an academic message."""
        raise NotImplementedError

    def answer(self, request):  # pragma: no cover - interface
        """Return a grounded answer dict for an AI Chat question."""
        raise NotImplementedError


_registry = {}
_override = None


def register(name, factory):
    _registry[name] = factory


def set_provider(provider):
    """Test/deployment seam."""
    global _override
    _override = provider


def get_provider():
    if _override is not None:
        return _override
    from flask import current_app
    name = current_app.config.get("AI_PROVIDER", "heuristic")
    factory = _registry.get(name)
    if factory is None:
        raise ServiceUnavailableError(f"AI provider '{name}' is not available.")
    return factory()


def _load_builtin():
    from .heuristic import HeuristicProvider

    register("heuristic", HeuristicProvider)

    def _anthropic():
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()

    register("anthropic", _anthropic)


_load_builtin()
