"""Document-type detection + routing to the right processor.

In the PoC, detection is extension-based with a light content sniff. In
production this is replaced by the classifier component described in GAD §5.1.
The interface stays the same so the classifier can be swapped in without
touching callers.
"""

from __future__ import annotations

from pathlib import Path

from ador.core.registry import ProcessorRegistry, default_registry
from ador.core.schemas import DocType, ExtractionResult


def detect_doc_type(path: Path) -> DocType:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return DocType.DOCX_TERMSHEET
    if suffix == ".pdf":
        return DocType.PDF_TERMSHEET
    if suffix in {".txt", ".log", ".msg"}:
        return DocType.CHAT
    return DocType.UNKNOWN


def route(path: Path, registry: ProcessorRegistry | None = None) -> ExtractionResult:
    """Detect doc type and dispatch to the matching processor."""
    reg = registry or default_registry
    doc_type = detect_doc_type(path)
    if doc_type is DocType.UNKNOWN:
        raise ValueError(f"Unsupported document type for {path.name!r}")
    processor = reg.for_type(doc_type)
    return processor.extract(path)
