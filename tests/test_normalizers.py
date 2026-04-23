"""Unit tests for value normalisers — isolate parsing logic from I/O."""

from ador.processors._normalizers import (
    normalize_label,
    parse_barrier,
    parse_date,
    parse_notional,
    parse_percent,
    parse_underlying,
)


def test_normalize_label_strips_parenthetical_codes() -> None:
    assert normalize_label("Notional Amount (N)") == "notional amount"
    assert normalize_label("Coupon (C)") == "coupon"
    assert normalize_label("  Barrier (B)  ") == "barrier"


def test_parse_date_supports_long_month_name() -> None:
    assert parse_date("31 January 2025") == "2025-01-31"
    assert parse_date("07 August 2026") == "2026-08-07"


def test_parse_date_supports_iso_and_slashes() -> None:
    assert parse_date("2025-01-31") == "2025-01-31"
    assert parse_date("31/01/2025") == "2025-01-31"


def test_parse_date_returns_none_on_garbage() -> None:
    assert parse_date("not a date") is None


def test_parse_notional_with_word_multiplier() -> None:
    result = parse_notional("EUR 1 million")
    assert result == {"currency": "EUR", "amount": 1_000_000.0}


def test_parse_notional_with_short_multiplier_no_ccy() -> None:
    result = parse_notional("200 mio")
    assert result == {"currency": None, "amount": 200_000_000.0}


def test_parse_percent_returns_fraction() -> None:
    assert parse_percent("75.00%") == 0.75
    assert parse_percent("0%") == 0.0


def test_parse_underlying_extracts_identifiers() -> None:
    result = parse_underlying("Allianz SE (ISIN DE0008404005, Reuters: ALVG.DE)")
    assert result == {
        "name": "Allianz SE",
        "isin": "DE0008404005",
        "reuters": "ALVG.DE",
    }


def test_parse_barrier_extracts_level_and_reference() -> None:
    result = parse_barrier("75.00% of Share_initial")
    assert result == {"level": 0.75, "reference": "Share_initial"}
