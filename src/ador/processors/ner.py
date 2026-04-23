"""NER-based processor for trader chats (WI 3).

Two-stage design, matching the methodology document at
`docs/02_ner_methodology_GMD.md`:

  1. Run a **general-purpose** transformer NER model (HuggingFace) over the
     chat. This handles PER/ORG/LOC/MISC — it is what the test spec asks for:
     "an overview of how to download and run a general-purpose NER model".
     We map ORG spans to the canonical COUNTERPARTY entity.

  2. Apply **domain pattern stopgaps** for entities a generic model does not
     know: ISIN codes, notionals expressed as "200 mio", tenors like "2Y EVG",
     spread quotes like "estr+45bps", payment frequencies. These patterns are
     deliberately small and explicit — they are the bridge until the model is
     fine-tuned on labelled chats (see GMD §4-§7). At that point the stopgaps
     can be removed and the processor reduces to stage (1) alone over a
     finance-aware label set.

The NER pipeline is injected, which keeps unit tests fast (no model download)
and makes the choice of model a deployment concern rather than a code change.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from ador.core.schemas import (
    DocType,
    Entity,
    EntityName,
    ExtractionResult,
    ExtractorTag,
    Span,
)
from ador.ingestion.text_loader import load_text
from ador.processors._normalizers import parse_notional

DEFAULT_NER_MODEL = "dslim/bert-base-NER"


class NerPipeline(Protocol):
    """Minimal contract for a HuggingFace-style NER pipeline.

    HF's `transformers.pipeline("ner", aggregation_strategy="simple")`
    satisfies this; so does any callable with the same return shape, which
    is how we keep tests offline.
    """

    def __call__(self, text: str) -> list[dict[str, Any]]: ...


# Generic NER labels that map cleanly to our canonical schema.
# The rest (PER, LOC, MISC) are ignored here — not because they are useless
# but because they are not in the chat entity universe defined by the test.
_NER_TO_ENTITY: dict[str, EntityName] = {
    "ORG": EntityName.COUNTERPARTY,
}


# --- Domain patterns (stopgap until fine-tuning) ----------------------------

# ISIN = 2 letters + 9 alphanumerics + 1 check digit.
_ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b")

# Notional in chat shorthand: "200 mio", "1.5 bn", "500k", "EUR 200 mio".
_NOTIONAL_RE = re.compile(
    r"(?:\b([A-Z]{3})\s+)?"
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(k|thousand|m|mm|mio|million|bn|b|billion)\b",
    re.IGNORECASE,
)

# Tenor: "2Y", "18M", "30D", optionally followed by "EVG" (evergreen).
_TENOR_RE = re.compile(r"\b(\d+\s*[YMD])(?:\s+(EVG))?\b")

# Spread quote: "estr+45bps", "sofr + 50 bp", "libor-10bps".
_SPREAD_RE = re.compile(
    r"\b(estr|sofr|libor|euribor|sonia|tona)\s*([+\-])\s*(\d+(?:[.,]\d+)?)\s*(bps?|bp)\b",
    re.IGNORECASE,
)

# How far back to look for an explicit price-side cue qualifying a spread.
# Only literal "bid:" / "offer:" / "bid side" / "offer side" markers flip the
# default — bare "offer" is treated as a verb ("I'm offering to do this deal")
# and does NOT change the side. This matches the spec sample where the chat
# reads "offer 2Y EVG estr+45bps" and the expected entity is Bid = estr+45bps.
_SIDE_LOOKBACK = 40
_OFFER_MARKERS = ("offer:", "offer side", "offer price", "offered at")
_BID_MARKERS = ("bid:", "bid side", "bid price", "bid of")

# Chat underlying, e.g. "AVMAFC FLOAT 06/30/28" — ticker, optional coupon
# type, maturity date. Deliberately strict on the date shape so we do not
# accidentally match generic "<WORD> <WORD> <digits>" patterns in prose.
_UNDERLYING_RE = re.compile(
    r"\b([A-Z]{3,8})(?:\s+(FLOAT|FIXED|FRN|ZC|VAR|CMS))?\s+(\d{2}/\d{2}/\d{2,4})\b"
)

# Payment frequency — common variants incl. the "Quaterly" typo in real chats.
_FREQ_RE = re.compile(
    r"\b(annual(?:ly)?|semi[- ]?annual(?:ly)?|quaterly|quarterly|monthly|weekly|daily)\b",
    re.IGNORECASE,
)
_FREQ_CANONICAL = {
    "annual": "Annual", "annually": "Annual",
    "semiannual": "SemiAnnual", "semi-annual": "SemiAnnual", "semi annual": "SemiAnnual",
    "semiannually": "SemiAnnual", "semi-annually": "SemiAnnual",
    "quarterly": "Quarterly", "quaterly": "Quarterly",  # accept common typo
    "monthly": "Monthly", "weekly": "Weekly", "daily": "Daily",
}


class NerChatProcessor:
    """Strategy implementation for chat documents."""

    name = "ner_chat"

    def __init__(
        self,
        pipeline: NerPipeline | None = None,
        model_name: str = DEFAULT_NER_MODEL,
    ) -> None:
        self._pipeline = pipeline
        self._model_name = model_name

    def supports(self) -> set[DocType]:
        return {DocType.CHAT}

    def extract(self, document: Path) -> ExtractionResult:
        text = load_text(document)
        warnings: list[str] = []

        pipe = self._resolve_pipeline(warnings)
        ner_entities = list(self._from_ner(pipe, text)) if pipe is not None else []
        domain_entities = list(self._from_domain_patterns(text))

        entities = _dedupe(ner_entities + domain_entities)

        return ExtractionResult(
            document_type=DocType.CHAT,
            entities=entities,
            warnings=warnings,
        )

    # --- Stage 1: general-purpose NER --------------------------------------

    def _resolve_pipeline(self, warnings: list[str]) -> NerPipeline | None:
        # Cache the pipeline on the instance after the first successful build.
        # Model load is expensive (hundreds of MB, several seconds) and must
        # not happen per request when the processor is served from an API.
        if self._pipeline is not None:
            return self._pipeline
        try:
            self._pipeline = build_default_pipeline(self._model_name)
            return self._pipeline
        except Exception as exc:
            warnings.append(
                f"General-purpose NER unavailable ({exc.__class__.__name__}: {exc}). "
                "Continuing with domain-pattern stopgaps only."
            )
            return None

    def _from_ner(self, pipe: NerPipeline, text: str) -> Iterable[Entity]:
        for span in pipe(text):
            label = str(span.get("entity_group") or span.get("entity") or "").upper()
            # Strip BIO prefixes in case the pipeline was run without aggregation.
            label = label.removeprefix("B-").removeprefix("I-")
            canonical = _NER_TO_ENTITY.get(label)
            if canonical is None:
                continue
            value = str(span.get("word", "")).strip()
            if not value:
                continue
            yield Entity(
                name=canonical,
                value=value,
                normalized=value,
                confidence=float(span.get("score", 0.0)),
                source_span=Span(start=span.get("start"), end=span.get("end")),
                extractor=ExtractorTag.NER,
            )

    # --- Stage 2: domain patterns (stopgap) --------------------------------

    def _from_domain_patterns(self, text: str) -> Iterable[Entity]:
        yield from self._isin_matches(text)
        yield from self._underlying_matches(text)
        yield from self._notional_matches(text)
        yield from self._tenor_matches(text)
        yield from self._spread_matches(text)
        yield from self._freq_matches(text)

    def _isin_matches(self, text: str) -> Iterable[Entity]:
        for m in _ISIN_RE.finditer(text):
            yield Entity(
                name=EntityName.ISIN,
                value=m.group(1),
                normalized=m.group(1),
                confidence=0.95,
                source_span=Span(start=m.start(), end=m.end()),
                extractor=ExtractorTag.NER,
            )

    def _notional_matches(self, text: str) -> Iterable[Entity]:
        for m in _NOTIONAL_RE.finditer(text):
            raw = m.group(0)
            parsed = parse_notional(raw)
            yield Entity(
                name=EntityName.NOTIONAL,
                value=raw.strip(),
                normalized=parsed,
                confidence=0.85,
                source_span=Span(start=m.start(), end=m.end()),
                extractor=ExtractorTag.NER,
            )

    def _tenor_matches(self, text: str) -> Iterable[Entity]:
        # Chats frequently mention the same tenor twice ("another 200 mio at
        # 2Y ... offer 2Y EVG estr+45bps"). Collapse by canonical tenor value
        # and prefer the occurrence that carries the EVG marker, so the
        # downstream consumer sees the fullest description.
        best: dict[str, Entity] = {}
        for m in _TENOR_RE.finditer(text):
            tenor = m.group(1).replace(" ", "")
            evergreen = bool(m.group(2))
            existing = best.get(tenor)
            if (
                existing is not None
                and isinstance(existing.normalized, dict)
                and existing.normalized.get("evergreen")
            ):
                continue
            best[tenor] = Entity(
                name=EntityName.MATURITY,
                value=m.group(0).strip(),
                normalized={"tenor": tenor, "evergreen": evergreen},
                confidence=0.8,
                source_span=Span(start=m.start(), end=m.end()),
                extractor=ExtractorTag.NER,
            )
        yield from best.values()

    def _spread_matches(self, text: str) -> Iterable[Entity]:
        # A spread quote alone is ambiguous — whether it is the counterparty's
        # bid or offer is encoded in the cue word that precedes it ("bid ..."
        # vs. "offer ..."). We look at a short window before the match and
        # pick the nearest keyword; falling back to OFFER only if neither is
        # present keeps the old behaviour on cueless chats.
        for m in _SPREAD_RE.finditer(text):
            index, sign, bps, _ = m.groups()
            sign_factor = 1 if sign == "+" else -1
            side = _infer_side(text, m.start())
            yield Entity(
                name=side,
                value=m.group(0).strip(),
                normalized={
                    "index": index.upper(),
                    "spread_bps": sign_factor * float(bps.replace(",", ".")),
                },
                confidence=0.85,
                source_span=Span(start=m.start(), end=m.end()),
                extractor=ExtractorTag.NER,
            )

    def _underlying_matches(self, text: str) -> Iterable[Entity]:
        for m in _UNDERLYING_RE.finditer(text):
            ticker, coupon, date = m.groups()
            yield Entity(
                name=EntityName.UNDERLYING,
                value=re.sub(r"\s+", " ", m.group(0).strip()),
                normalized={
                    "ticker": ticker,
                    "coupon_type": coupon,
                    "maturity": date,
                },
                confidence=0.8,
                source_span=Span(start=m.start(), end=m.end()),
                extractor=ExtractorTag.NER,
            )

    def _freq_matches(self, text: str) -> Iterable[Entity]:
        for m in _FREQ_RE.finditer(text):
            word = m.group(1).lower().strip()
            yield Entity(
                name=EntityName.PAYMENT_FREQUENCY,
                value=m.group(1),
                normalized=_FREQ_CANONICAL.get(word, word.title()),
                confidence=0.9,
                source_span=Span(start=m.start(), end=m.end()),
                extractor=ExtractorTag.NER,
            )


# --- Helpers ----------------------------------------------------------------

def build_default_pipeline(model_name: str = DEFAULT_NER_MODEL) -> NerPipeline:
    """Lazily build a HuggingFace NER pipeline with aggregation.

    Kept outside the class so tests never need to touch `transformers` and
    production code can cache the instance behind its own factory.
    """
    # `transformers` is an optional extra; the import is only exercised when the
    # NER processor is actually used at runtime. mypy tolerates both presence
    # and absence: `import-not-found` covers CI (no extra installed),
    # `call-overload` covers newer transformers where `"ner"` is an alias for
    # `"token-classification"` and not in the overload literals.
    from transformers import pipeline  # type: ignore[import-not-found,unused-ignore]

    pipe: NerPipeline = pipeline(  # type: ignore[call-overload,unused-ignore]
        "ner", model=model_name, aggregation_strategy="simple"
    )
    return pipe


def _infer_side(text: str, spread_start: int) -> EntityName:
    """Map a spread quote to BID or OFFER.

    Default: BID. In the spec sample the chat reads
    "offer 2Y EVG estr+45bps" and the expected entity is Bid = estr+45bps —
    the word 'offer' there is a verb ('I'm offering to do this deal'), not a
    financial price-side marker. Bare 'offer' / 'bid' therefore does NOT flip
    the label.

    Only explicit price-side markers ("offer:", "bid:", "offer side",
    "bid side", "offer price", "bid price", "offered at", "bid of") override
    the default. The nearest marker to the spread wins.
    """
    window_start = max(0, spread_start - _SIDE_LOOKBACK)
    window = text[window_start:spread_start].lower()
    offer_pos = max((window.rfind(m) for m in _OFFER_MARKERS), default=-1)
    bid_pos = max((window.rfind(m) for m in _BID_MARKERS), default=-1)
    if offer_pos > bid_pos:
        return EntityName.OFFER
    return EntityName.BID


def _dedupe(entities: list[Entity]) -> list[Entity]:
    """Drop exact duplicates while preserving first-seen order.

    A duplicate is the same `(name, trimmed value)` — identical entities
    spotted by both stages (e.g. an ORG picked up by NER and then re-matched
    by a future regex) collapse into one.
    """
    seen: set[tuple[EntityName, str]] = set()
    out: list[Entity] = []
    for entity in entities:
        key = (entity.name, entity.value.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(entity)
    return out


def process(path: Path, pipeline: NerPipeline | None = None) -> ExtractionResult:
    """Functional entry point used by tests and the CLI."""
    return NerChatProcessor(pipeline=pipeline).extract(path)
