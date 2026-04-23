"""Loader for `.docx` files — extracts table rows into typed records.

Isolating loading from extraction means:
  * the rule-based processor never sees the zip/XML layer;
  * an alternative loader (e.g. for docx files that use text rather than tables)
    can be swapped in without touching the processor;
  * loader output is trivially mockable in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docx import Document


@dataclass(frozen=True, slots=True)
class KVRow:
    """A key/value row from a docx table.

    `ref` is a stable provenance marker used as the `Span.ref` of any entity
    sourced from this row.
    """

    label: str
    value: str
    ref: str


def load_kv_rows(path: Path) -> list[KVRow]:
    """Return every 2-cell row across every table in the document.

    Section-header rows (single cell) and malformed rows are dropped; the
    processor should only see clean label/value pairs.
    """
    document = Document(str(path))
    rows: list[KVRow] = []
    for t_idx, table in enumerate(document.tables):
        for r_idx, row in enumerate(table.rows):
            cells = [cell.text.strip() for cell in row.cells]
            # Docx merges may repeat the same cell reference; de-duplicate while
            # preserving order so a visually two-column row isn't seen as four.
            cells = _dedupe_preserve_order(cells)
            if len(cells) != 2:
                continue
            label, value = cells
            if not label or not value:
                continue
            rows.append(
                KVRow(label=label, value=value, ref=f"table:{t_idx}:row:{r_idx}")
            )
    return rows


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
