"""Smoke tests for core contracts — ensures the scaffolding is sound."""

from pathlib import Path

import pytest

from ador.core.registry import ProcessorRegistry
from ador.core.router import detect_doc_type, route
from ador.core.schemas import (
    DocType,
    Entity,
    EntityName,
    ExtractionResult,
    ExtractorTag,
)


def test_doc_type_detection() -> None:
    assert detect_doc_type(Path("x.docx")) is DocType.DOCX_TERMSHEET
    assert detect_doc_type(Path("x.pdf")) is DocType.PDF_TERMSHEET
    assert detect_doc_type(Path("x.txt")) is DocType.CHAT
    assert detect_doc_type(Path("x.unknown")) is DocType.UNKNOWN


def test_extraction_result_lookup() -> None:
    result = ExtractionResult(
        document_type=DocType.CHAT,
        entities=[
            Entity(
                name=EntityName.COUNTERPARTY,
                value="BANK ABC",
                extractor=ExtractorTag.NER,
            )
        ],
    )
    hit = result.by_name(EntityName.COUNTERPARTY)
    assert hit is not None and hit.value == "BANK ABC"
    assert result.by_name(EntityName.ISIN) is None


def test_registry_errors_when_no_processor() -> None:
    registry = ProcessorRegistry()
    with pytest.raises(LookupError):
        registry.for_type(DocType.CHAT)


def test_router_rejects_unknown_type(tmp_path: Path) -> None:
    unknown = tmp_path / "mystery.xyz"
    unknown.write_text("nope")
    with pytest.raises(ValueError):
        route(unknown, registry=ProcessorRegistry())
