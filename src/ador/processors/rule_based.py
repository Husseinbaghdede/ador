"""Rule-based processor for structured `.docx` term sheets (WI 2).

The processor is deterministic, stateless, and cheap: no models, no network,
no training data. It relies on the fact that internal term sheets follow a
stable 2-column key/value layout, so a declarative label map is sufficient.

Extending to a new template means adding one row to `LABEL_MAP` — not writing
new code.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ador.core.schemas import (
    DocType,
    Entity,
    EntityName,
    ExtractionResult,
    ExtractorTag,
    Span,
)
from ador.ingestion.docx_loader import load_kv_rows
from ador.processors._normalizers import (
    normalize_label,
    parse_barrier,
    parse_date,
    parse_notional,
    parse_percent,
    parse_underlying,
    passthrough,
)

Normalizer = Callable[[str], Any]


# Declarative label → (canonical entity, value normaliser) mapping.
# Multiple raw labels can map to the same canonical entity — this is how the
# parser handles synonymous fields ("Termination Date" == "Maturity").
LABEL_MAP: dict[str, tuple[EntityName, Normalizer]] = {
    # Counterparty
    "party a":                  (EntityName.COUNTERPARTY, passthrough),
    "counterparty":             (EntityName.COUNTERPARTY, passthrough),
    # Dates
    "initial valuation date":   (EntityName.INITIAL_VALUATION_DATE, parse_date),
    "valuation date":           (EntityName.VALUATION_DATE, parse_date),
    "termination date":         (EntityName.MATURITY, parse_date),
    "maturity":                 (EntityName.MATURITY, parse_date),
    "maturity date":            (EntityName.MATURITY, parse_date),
    # Notional
    "notional amount":          (EntityName.NOTIONAL, parse_notional),
    "notional":                 (EntityName.NOTIONAL, parse_notional),
    # Economics
    "underlying":               (EntityName.UNDERLYING, parse_underlying),
    "coupon":                   (EntityName.COUPON, parse_percent),
    "barrier":                  (EntityName.BARRIER, parse_barrier),
    # Calendar / business day
    "business day":             (EntityName.CALENDAR, passthrough),
    "calendar":                 (EntityName.CALENDAR, passthrough),
}


class RuleBasedDocxProcessor:
    """Strategy implementation of `Processor` for `.docx` term sheets."""

    name = "rule_based_docx"

    def supports(self) -> set[DocType]:
        return {DocType.DOCX_TERMSHEET}

    def extract(self, document: Path) -> ExtractionResult:
        rows = load_kv_rows(document)
        entities: list[Entity] = []
        warnings: list[str] = []
        seen: set[EntityName] = set()

        for row in rows:
            mapped = LABEL_MAP.get(normalize_label(row.label))
            if mapped is None:
                continue
            canonical, normalizer = mapped
            # Prefer the first occurrence of each entity — later duplicates
            # would otherwise overwrite the canonical value silently.
            if canonical in seen:
                continue
            seen.add(canonical)

            normalized = normalizer(row.value)
            if normalized is None:
                warnings.append(
                    f"Could not normalise value for {canonical.value!r} "
                    f"(raw={row.value!r})"
                )
            entities.append(
                Entity(
                    name=canonical,
                    value=row.value,
                    normalized=normalized,
                    confidence=1.0,
                    source_span=Span(ref=row.ref),
                    extractor=ExtractorTag.RULE,
                )
            )

        missing = _expected_for_docx() - {e.name for e in entities}
        for name in sorted(missing, key=lambda n: n.value):
            warnings.append(f"Expected entity {name.value!r} not found in document")

        return ExtractionResult(
            document_type=DocType.DOCX_TERMSHEET,
            entities=entities,
            warnings=warnings,
        )


def _expected_for_docx() -> set[EntityName]:
    """The 9 entities the test spec lists for docx inputs."""
    return {
        EntityName.COUNTERPARTY,
        EntityName.INITIAL_VALUATION_DATE,
        EntityName.NOTIONAL,
        EntityName.VALUATION_DATE,
        EntityName.MATURITY,
        EntityName.UNDERLYING,
        EntityName.COUPON,
        EntityName.BARRIER,
        EntityName.CALENDAR,
    }


def process(path: Path) -> ExtractionResult:
    """Functional entry point — handy for ad-hoc use and tests."""
    return RuleBasedDocxProcessor().extract(path)
