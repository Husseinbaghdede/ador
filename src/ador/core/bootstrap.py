"""Explicit wiring of built-in processors into a registry.

Import-time side-effects are avoided deliberately: callers (CLI, API, tests)
decide when to register. This keeps unit tests fast and makes it obvious
which processors are active in a given runtime.
"""

from __future__ import annotations

from ador.core.registry import ProcessorRegistry, default_registry


def register_builtin_processors(registry: ProcessorRegistry | None = None) -> ProcessorRegistry:
    """Register every built-in processor on `registry` (or the default)."""
    reg = registry or default_registry
    # Import lazily so optional ML / LLM dependencies aren't required just to
    # run the rule-based path.
    from ador.processors.rule_based import RuleBasedDocxProcessor

    reg.register(RuleBasedDocxProcessor())

    # The NER processor itself has no hard dependency on `transformers` — the
    # model is only loaded at call time, and the processor degrades to its
    # domain-pattern stopgaps with a warning if the model is unavailable.
    from ador.processors.ner import NerChatProcessor

    reg.register(NerChatProcessor())
    return reg
