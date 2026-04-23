"""API tests — use the FastAPI TestClient so HTTP semantics are exercised
end-to-end, without running a server.

Every test builds its own app + registry to stay isolated."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ador.api.main import create_app
from ador.core.registry import ProcessorRegistry

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
SAMPLE_DOCX = SAMPLES / "ZF4894_ALV_07Aug2026_physical.docx"
SAMPLE_CHAT = SAMPLES / "FR001400QV82_AVMAFC_30Jun2028.txt"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(registry=ProcessorRegistry()))


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_processors_lists_builtins(client: TestClient) -> None:
    response = client.get("/processors")
    assert response.status_code == 200
    names = {p["name"] for p in response.json()}
    assert {"rule_based_docx", "ner_chat"} <= names


@pytest.mark.skipif(not SAMPLE_DOCX.exists(), reason="sample docx not present")
def test_extract_docx_returns_canonical_entities(client: TestClient) -> None:
    with SAMPLE_DOCX.open("rb") as fh:
        response = client.post(
            "/extract",
            files={
                "file": (
                    SAMPLE_DOCX.name,
                    fh,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document_type"] == "docx_termsheet"
    entity_names = {e["name"] for e in body["entities"]}
    # The 9 fields required by the test spec for docx inputs.
    assert {
        "counterparty",
        "initial_valuation_date",
        "notional",
        "valuation_date",
        "maturity",
        "underlying",
        "coupon",
        "barrier",
        "calendar",
    } <= entity_names
    # Every entity must carry provenance + extractor tag for audit.
    for entity in body["entities"]:
        assert entity["extractor"] in {"rule", "ner", "llm"}
        assert entity["source_span"] is not None


@pytest.mark.skipif(not SAMPLE_CHAT.exists(), reason="sample chat not present")
def test_extract_chat_routes_to_ner(client: TestClient) -> None:
    with SAMPLE_CHAT.open("rb") as fh:
        response = client.post(
            "/extract",
            files={"file": (SAMPLE_CHAT.name, fh, "text/plain")},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document_type"] == "chat"
    # Domain stopgaps must at least surface the ISIN even if the HF model
    # isn't available in the test environment.
    names = {e["name"] for e in body["entities"]}
    assert "isin" in names


def test_extract_rejects_unsupported_type(client: TestClient) -> None:
    response = client.post(
        "/extract",
        files={"file": ("mystery.xyz", b"nope", "application/octet-stream")},
    )
    assert response.status_code == 415
    assert "Unsupported" in response.json()["detail"]
