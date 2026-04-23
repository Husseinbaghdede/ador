"""Processor registry — Strategy pattern for entity extractors.

A processor is any callable that takes a loaded document and returns an
`ExtractionResult`. Processors register themselves for one or more `DocType`s;
the router (see `router.py`) picks the appropriate processor at runtime.

This is the seam that lets WI 2 (rule-based), WI 3 (NER) and WI 4 (LLM) drop
in independently without touching the API layer or the router.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from ador.core.schemas import DocType, ExtractionResult


@runtime_checkable
class Processor(Protocol):
    """Contract every extractor must satisfy."""

    name: str

    def supports(self) -> set[DocType]: ...

    def extract(self, document: Path) -> ExtractionResult: ...


class ProcessorRegistry:
    """Maps DocType → Processor.

    A single processor may support multiple doc types. Registration is
    idempotent on `name` so the same processor can be re-registered (e.g.
    after a hot-reload in development).
    """

    def __init__(self) -> None:
        self._by_name: dict[str, Processor] = {}
        self._by_type: dict[DocType, Processor] = {}

    def register(self, processor: Processor) -> None:
        self._by_name[processor.name] = processor
        for doc_type in processor.supports():
            self._by_type[doc_type] = processor

    def for_type(self, doc_type: DocType) -> Processor:
        try:
            return self._by_type[doc_type]
        except KeyError as exc:
            raise LookupError(
                f"No processor registered for document type {doc_type.value!r}"
            ) from exc

    def by_name(self, name: str) -> Processor:
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise LookupError(f"No processor registered with name {name!r}") from exc

    def all(self) -> list[Processor]:
        return list(self._by_name.values())


# Module-level default registry used by the API and CLI. Tests can build
# their own instances for isolation.
default_registry = ProcessorRegistry()


def register(processor_factory: Callable[[], Processor]) -> Callable[[], Processor]:
    """Decorator for processor factories that want to self-register on import."""
    default_registry.register(processor_factory())
    return processor_factory
