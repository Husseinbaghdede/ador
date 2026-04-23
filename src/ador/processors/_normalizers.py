"""Value normalizers — pure functions shared across processors.

Normalizers return JSON-serialisable Python values (str, int, float, dict,
ISO-formatted date strings). They never raise on malformed input; they return
`None` so the processor can surface a warning instead of failing the whole
extraction.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

# --- Labels -----------------------------------------------------------------

_PAREN_CODE = re.compile(r"\s*\([^)]*\)\s*")
_WS = re.compile(r"\s+")


def normalize_label(raw: str) -> str:
    """Canonicalise a termsheet label for lookup.

    Removes parenthetical codes (e.g. "Notional Amount (N)" → "notional amount"),
    collapses whitespace, lower-cases. Reversible mappings are not required —
    the canonical label is only used as a dictionary key.
    """
    stripped = _PAREN_CODE.sub(" ", raw)
    return _WS.sub(" ", stripped).strip().lower()


# --- Dates ------------------------------------------------------------------

_DATE_FORMATS: tuple[str, ...] = (
    "%d %B %Y",       # 31 January 2025
    "%d %b %Y",       # 31 Jan 2025
    "%Y-%m-%d",       # 2025-01-31
    "%d/%m/%Y",       # 31/01/2025
    "%d-%m-%Y",       # 31-01-2025
    "%d.%m.%Y",       # 31.01.2025
)


def parse_date(raw: str) -> str | None:
    """Parse a human-readable date and return an ISO-8601 string, or None."""
    text = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# --- Money / notional -------------------------------------------------------

_CCY = re.compile(r"\b([A-Z]{3})\b")
_AMOUNT = re.compile(r"([\d]+(?:[.,]\d+)?)")
_MULTIPLIERS: dict[str, int] = {
    "k": 1_000, "thousand": 1_000,
    "m": 1_000_000, "mm": 1_000_000, "mio": 1_000_000, "million": 1_000_000,
    "bn": 1_000_000_000, "b": 1_000_000_000, "billion": 1_000_000_000,
}
_MULTIPLIER_RE = re.compile(
    r"\b(" + "|".join(sorted(_MULTIPLIERS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def parse_notional(raw: str) -> dict[str, Any] | None:
    """Parse a notional string like "EUR 1 million" or "200 mio"."""
    text = raw.strip()
    ccy_match = _CCY.search(text)
    amount_match = _AMOUNT.search(text)
    if amount_match is None:
        return None
    try:
        amount = Decimal(amount_match.group(1).replace(",", ""))
    except InvalidOperation:
        return None
    mult_match = _MULTIPLIER_RE.search(text)
    multiplier = _MULTIPLIERS[mult_match.group(1).lower()] if mult_match else 1
    return {
        "currency": ccy_match.group(1) if ccy_match else None,
        "amount": float(amount * multiplier),
    }


# --- Percentages ------------------------------------------------------------

_PERCENT = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*%")


def parse_percent(raw: str) -> float | None:
    """Return a percentage as a decimal fraction ("75.00%" → 0.75)."""
    match = _PERCENT.search(raw)
    if match is None:
        return None
    try:
        return float(Decimal(match.group(1).replace(",", "."))) / 100.0
    except InvalidOperation:
        return None


# --- Underlying -------------------------------------------------------------

_ISIN = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b")
_REUTERS = re.compile(r"Reuters\s*:\s*([^\s,)]+)", re.IGNORECASE)


def parse_underlying(raw: str) -> dict[str, Any] | None:
    """Split an underlying description into name + identifiers."""
    text = raw.strip()
    isin = _ISIN.search(text)
    reuters = _REUTERS.search(text)
    # Name = everything before the first opening parenthesis, if any.
    name = text.split("(", 1)[0].strip() or None
    if not any([name, isin, reuters]):
        return None
    return {
        "name": name,
        "isin": isin.group(1) if isin else None,
        "reuters": reuters.group(1) if reuters else None,
    }


# --- Barrier ----------------------------------------------------------------

def parse_barrier(raw: str) -> dict[str, Any] | None:
    """Barrier is usually "<pct>% of <reference>"."""
    pct = parse_percent(raw)
    reference: str | None = None
    if " of " in raw.lower():
        reference = raw.split(" of ", 1)[-1].strip() or None
    if pct is None and reference is None:
        return None
    return {"level": pct, "reference": reference}


# --- Passthrough ------------------------------------------------------------

def passthrough(raw: str) -> str:
    """Trimmed string — used when no deeper normalisation is sensible."""
    return raw.strip()


__all__ = [
    "normalize_label",
    "parse_barrier",
    "parse_date",
    "parse_notional",
    "parse_percent",
    "parse_underlying",
    "passthrough",
]
