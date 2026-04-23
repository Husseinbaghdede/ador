"""FastAPI application exposing ADOR's entity-extraction capability.

Design notes:
  * The app is created by a factory (`create_app`) so tests can build isolated
    instances with their own registries.
  * Uploaded files are staged to a temp path so processors that need a
    filesystem path (docx, pdf) work unchanged; the temp file is unlinked in a
    finally block, never left behind on error.
  * Error surface is tight: 415 for unknown type, 422 for processor failure,
    200 for success. The `warnings` field of the result carries soft failures
    (e.g. NER model unavailable) — the caller decides what to do with them.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile

from ador import __version__
from ador.core.bootstrap import register_builtin_processors
from ador.core.registry import ProcessorRegistry, default_registry
from ador.core.router import detect_doc_type, route
from ador.core.schemas import DocType, ExtractionResult


def create_app(registry: ProcessorRegistry | None = None) -> FastAPI:
    """Build and return the FastAPI app.

    A custom registry can be injected for tests or for multi-tenant
    deployments where each tenant has a different processor configuration.
    """
    app = FastAPI(
        title="ADOR",
        version=__version__,
        description=(
            "Augmented DOcument Reader — routes financial documents to "
            "rule-based, NER or LLM processors and returns canonical entities."
        ),
    )

    reg = registry or default_registry
    # Register built-ins on the active registry. Idempotent on processor name.
    register_builtin_processors(reg)

    def get_registry() -> ProcessorRegistry:
        return reg

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/processors", tags=["meta"])
    def processors(
        registry: ProcessorRegistry = Depends(get_registry),
    ) -> list[dict[str, object]]:
        return [
            {
                "name": p.name,
                "supports": sorted(dt.value for dt in p.supports()),
            }
            for p in registry.all()
        ]

    @app.post("/extract", response_model=ExtractionResult, tags=["extraction"])
    async def extract(
        file: UploadFile = File(..., description="Document to process"),
        registry: ProcessorRegistry = Depends(get_registry),
    ) -> ExtractionResult:
        filename = file.filename or ""
        suffix = Path(filename).suffix.lower()

        # Stage to disk so format-specific loaders (python-docx, pypdf) work
        # against a real path. tempfile cleanup is done in the finally.
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = Path(tmp.name)

        try:
            doc_type = detect_doc_type(tmp_path)
            if doc_type is DocType.UNKNOWN:
                raise HTTPException(
                    status_code=415,
                    detail=f"Unsupported document type: {suffix!r}",
                )
            try:
                return route(tmp_path, registry=registry)
            except LookupError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            tmp_path.unlink(missing_ok=True)

    return app


# Module-level app for `uvicorn ador.api.main:app`.
app = create_app()
