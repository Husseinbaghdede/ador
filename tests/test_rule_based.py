"""Integration test — runs the rule-based parser on the real sample docx."""

from pathlib import Path

import pytest

from ador.core.schemas import DocType, EntityName, ExtractorTag
from ador.processors.rule_based import process

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
SAMPLE = SAMPLES / "ZF4894_ALV_07Aug2026_physical.docx"


pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="sample docx not present")


def test_extracts_all_expected_entities() -> None:
    result = process(SAMPLE)
    assert result.document_type is DocType.DOCX_TERMSHEET
    names = {e.name for e in result.entities}
    expected = {
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
    assert expected <= names, f"missing: {expected - names}"


def test_normalised_values_are_canonical() -> None:
    result = process(SAMPLE)
    by_name = {e.name: e for e in result.entities}

    assert by_name[EntityName.COUNTERPARTY].value == "BANK ABC"
    assert by_name[EntityName.INITIAL_VALUATION_DATE].normalized == "2025-01-31"
    assert by_name[EntityName.VALUATION_DATE].normalized == "2026-07-31"
    assert by_name[EntityName.MATURITY].normalized == "2026-08-07"
    assert by_name[EntityName.NOTIONAL].normalized == {"currency": "EUR", "amount": 1_000_000.0}
    assert by_name[EntityName.COUPON].normalized == 0.0
    assert by_name[EntityName.BARRIER].normalized["level"] == 0.75
    assert by_name[EntityName.UNDERLYING].normalized["name"] == "Allianz SE"
    assert by_name[EntityName.CALENDAR].value.strip() == "TARGET"


def test_every_entity_carries_provenance() -> None:
    result = process(SAMPLE)
    for entity in result.entities:
        assert entity.extractor is ExtractorTag.RULE
        assert entity.source_span is not None and entity.source_span.ref is not None
