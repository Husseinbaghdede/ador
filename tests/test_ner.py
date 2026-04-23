"""Tests for the NER processor — uses an injected fake pipeline so no model
weights are downloaded during CI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ador.core.schemas import Entity, EntityName, ExtractorTag
from ador.processors.ner import NerChatProcessor, _dedupe, process

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
SAMPLE = SAMPLES / "FR001400QV82_AVMAFC_30Jun2028.txt"


def fake_pipeline_bank_abc(text: str) -> list[dict[str, Any]]:
    """Stub standing in for a HuggingFace NER pipeline.

    Returns the ORG span a real general-purpose model would typically
    produce on the sample chat.
    """
    start = text.find("BANK ABC")
    return [
        {
            "entity_group": "ORG",
            "score": 0.9876,
            "word": "BANK ABC",
            "start": start,
            "end": start + len("BANK ABC"),
        }
    ]


def empty_pipeline(text: str) -> list[dict[str, Any]]:
    return []


pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="sample chat not present")


def test_extracts_counterparty_from_ner_output() -> None:
    result = process(SAMPLE, pipeline=fake_pipeline_bank_abc)
    cpty = result.by_name(EntityName.COUNTERPARTY)
    assert cpty is not None
    assert cpty.value == "BANK ABC"
    assert cpty.extractor is ExtractorTag.NER
    assert cpty.confidence > 0.9


def test_domain_patterns_cover_entities_ner_cannot_find() -> None:
    result = process(SAMPLE, pipeline=empty_pipeline)
    found = {e.name for e in result.entities}
    # Domain stopgaps must cover these regardless of whether the NER model ran.
    assert EntityName.ISIN in found
    assert EntityName.NOTIONAL in found
    assert EntityName.UNDERLYING in found
    assert EntityName.MATURITY in found
    assert EntityName.BID in found
    assert EntityName.PAYMENT_FREQUENCY in found


def test_extracts_underlying_from_chat() -> None:
    result = process(SAMPLE, pipeline=empty_pipeline)
    underlying = result.by_name(EntityName.UNDERLYING)
    assert underlying is not None
    assert underlying.value == "AVMAFC FLOAT 06/30/28"
    assert underlying.normalized == {
        "ticker": "AVMAFC",
        "coupon_type": "FLOAT",
        "maturity": "06/30/28",
    }


def test_explicit_offer_marker_overrides_bid_default() -> None:
    # Only a true price-side marker ("offer:" / "offer side" / "offered at")
    # flips the label to OFFER. Bare 'offer' stays BID because it is a verb
    # in these chats — verified against the spec's sample mapping.
    tmp = SAMPLE.parent / "_offer_marker_chat.txt"
    tmp.write_text("quote offer: estr+50bps please", encoding="utf-8")
    try:
        result = process(tmp, pipeline=empty_pipeline)
        offer = result.by_name(EntityName.OFFER)
        assert offer is not None
        assert offer.normalized == {"index": "ESTR", "spread_bps": 50.0}
        assert result.by_name(EntityName.BID) is None
    finally:
        tmp.unlink(missing_ok=True)


def test_isin_is_correctly_isolated() -> None:
    result = process(SAMPLE, pipeline=empty_pipeline)
    isin = result.by_name(EntityName.ISIN)
    assert isin is not None and isin.value == "FR001400QV82"


def test_notional_is_normalised_to_amount() -> None:
    result = process(SAMPLE, pipeline=empty_pipeline)
    notional = result.by_name(EntityName.NOTIONAL)
    assert notional is not None
    assert notional.normalized == {"currency": None, "amount": 200_000_000.0}


def test_spread_is_parsed_as_bid_by_default() -> None:
    # The sample chat reads "offer 2Y EVG estr+45bps" where 'offer' is a
    # verb ("I'm offering to do this deal"), not a financial side marker.
    # Per the test spec the expected entity is Bid = estr+45bps.
    result = process(SAMPLE, pipeline=empty_pipeline)
    bid = result.by_name(EntityName.BID)
    assert bid is not None
    assert bid.normalized == {"index": "ESTR", "spread_bps": 45.0}
    assert result.by_name(EntityName.OFFER) is None


def test_maturity_marks_evergreen() -> None:
    result = process(SAMPLE, pipeline=empty_pipeline)
    maturity = result.by_name(EntityName.MATURITY)
    assert maturity is not None
    assert maturity.normalized == {"tenor": "2Y", "evergreen": True}


def test_payment_frequency_handles_common_typo() -> None:
    # The real sample uses the correct spelling; this asserts the typo path
    # also canonicalises to Quarterly so real-world chats are covered.
    tmp = SAMPLE.parent / "_typo_chat.txt"
    tmp.write_text("another 50 mio / Quaterly interest payment", encoding="utf-8")
    try:
        result = process(tmp, pipeline=empty_pipeline)
        freq = result.by_name(EntityName.PAYMENT_FREQUENCY)
        assert freq is not None
        assert freq.normalized == "Quarterly"
    finally:
        tmp.unlink(missing_ok=True)


def test_processor_degrades_gracefully_when_model_fails() -> None:
    def raising_pipeline(_: str) -> list[dict[str, Any]]:
        raise RuntimeError("model unavailable")

    # Inject a pipeline that raises; processor should catch at model-load
    # boundary, not mid-call. Simulate a load failure by overriding the
    # builder path:
    proc = NerChatProcessor(pipeline=None, model_name="definitely-not-a-real-model")
    # Monkey-patch the builder via the module to avoid hitting the network:
    import ador.processors.ner as ner_mod

    original = ner_mod.build_default_pipeline
    ner_mod.build_default_pipeline = lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        result = proc.extract(SAMPLE)
    finally:
        ner_mod.build_default_pipeline = original

    assert any("unavailable" in w.lower() for w in result.warnings)
    # Domain stopgaps still ran.
    assert result.by_name(EntityName.ISIN) is not None


def test_dedupe_collapses_case_insensitive_duplicates() -> None:
    e1 = Entity(name=EntityName.COUNTERPARTY, value="Bank ABC", extractor=ExtractorTag.NER)
    e2 = Entity(name=EntityName.COUNTERPARTY, value=" BANK ABC ", extractor=ExtractorTag.NER)
    assert len(_dedupe([e1, e2])) == 1
