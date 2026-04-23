"""Loader for plain-text documents (chat exports, logs, emails-as-text)."""

from __future__ import annotations

from pathlib import Path


def load_text(path: Path) -> str:
    """Read a text document as UTF-8, replacing unreadable bytes.

    `errors="replace"` is deliberate: chat exports often include stray bytes
    from copy/paste or legacy encodings, and we prefer a parseable string
    with a few replacement characters over a hard failure.
    """
    return path.read_text(encoding="utf-8", errors="replace")
