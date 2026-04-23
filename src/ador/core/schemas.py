"""Canonical entity schema — the contract every processor emits into.

Keeping one schema across rule-based, NER and LLM extractors is what makes the
system pluggable: downstream consumers never care which processor produced the
result, and new processors can be added without touching callers.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class DocType(str, Enum):
    """Document type detected by the router; drives processor selection."""

    CHAT = "chat"
    DOCX_TERMSHEET = "docx_termsheet"
    PDF_TERMSHEET = "pdf_termsheet"
    UNKNOWN = "unknown"


class ExtractorTag(str, Enum):
    """Which backend produced an entity — kept on every Entity for auditability."""

    RULE = "rule"
    NER = "ner"
    LLM = "llm"


class EntityName(str, Enum):
    """Canonical entity vocabulary.

    Union of the fields listed in the test spec for chat and docx inputs.
    Additional entities can be added without breaking downstream consumers
    because values are strings.
    """

    COUNTERPARTY = "counterparty"
    NOTIONAL = "notional"
    ISIN = "isin"
    UNDERLYING = "underlying"
    MATURITY = "maturity"
    BID = "bid"
    OFFER = "offer"
    PAYMENT_FREQUENCY = "payment_frequency"

    INITIAL_VALUATION_DATE = "initial_valuation_date"
    VALUATION_DATE = "valuation_date"
    COUPON = "coupon"
    BARRIER = "barrier"
    CALENDAR = "calendar"


class Span(BaseModel):
    """Provenance marker so an entity can be traced back to its source.

    For text: character offsets. For tables: a cell reference (table:row:col).
    """

    model_config = ConfigDict(frozen=True)

    start: int | None = None
    end: int | None = None
    ref: str | None = None


class Entity(BaseModel):
    """A single extracted entity."""

    model_config = ConfigDict(frozen=True)

    name: EntityName
    value: str = Field(..., description="Raw surface form as it appears in the document")
    normalized: Any | None = Field(
        default=None,
        description="Typed/canonicalised value (Decimal, date, cleaned ISIN, ...)",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_span: Span | None = None
    extractor: ExtractorTag


class ExtractionResult(BaseModel):
    """Top-level output of the NER feature for one document."""

    document_id: UUID = Field(default_factory=uuid4)
    document_type: DocType
    entities: list[Entity] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    processed_at: datetime = Field(default_factory=datetime.utcnow)

    def by_name(self, name: EntityName) -> Entity | None:
        """Convenience lookup for the first entity with a given name."""
        return next((e for e in self.entities if e.name == name), None)
