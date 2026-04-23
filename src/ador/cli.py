"""Command-line interface for ADOR."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from ador.core.bootstrap import register_builtin_processors
from ador.core.router import route

app = typer.Typer(add_completion=False, help="ADOR — Augmented DOcument Reader")


@app.command()
def extract(
    document: Path = typer.Argument(..., exists=True, readable=True, resolve_path=True),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Write JSON result here instead of stdout."
    ),
    indent: int = typer.Option(2, help="JSON indent level."),
) -> None:
    """Extract entities from a single document, routing by document type."""
    register_builtin_processors()
    result = route(document)
    payload = result.model_dump(mode="json")
    rendered = json.dumps(payload, indent=indent, ensure_ascii=False)
    if output is None:
        typer.echo(rendered)
    else:
        output.write_text(rendered, encoding="utf-8")
        typer.echo(f"Wrote {len(result.entities)} entities to {output}")


if __name__ == "__main__":
    app()
