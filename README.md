# ADOR — Augmented DOcument Reader

Financial document reader augmented with AI. Proof of Concept for the **CMI Architecture & Innovation** team at Crédit Agricole CIB.

ADOR extracts financial named entities from heterogeneous documents by routing each document to the right technique:

| Document type | Technique | Rationale |
|---------------|-----------|-----------|
| Structured `.docx` term sheet | **Rule-based parser** | Deterministic, zero-cost, auditable, no hallucination |
| Trader chat (`.txt`) | **NER model** + domain patterns | General NER + fine-tuning path for domain entities |
| Verbose `.pdf` term sheet | **LLM + RAG** *(methodology only)* | Narrative, cross-clause reasoning |

Everything emits into one canonical schema (`ExtractionResult`), so downstream consumers are backend-agnostic.

---

## Test assignment mapping

| Work Item | Deliverable | Location |
|-----------|-------------|----------|
| **WI 1** — Architecture | Global Architecture Document | [docs/01_architecture_GAD.md](docs/01_architecture_GAD.md) |
| **WI 2** — Rule-based parser | Python code (docx) | [src/ador/processors/rule_based.py](src/ador/processors/rule_based.py) |
| **WI 3** — NER | Python code (chat) + fine-tuning methodology | [src/ador/processors/ner.py](src/ador/processors/ner.py), [docs/02_ner_methodology_GMD.md](docs/02_ner_methodology_GMD.md) |
| **WI 4** — LLM | Prompting + RAG methodology | [docs/03_llm_methodology_GMD.md](docs/03_llm_methodology_GMD.md) |

---

## Repository layout

```
ador/
├── docs/
│   ├── 01_architecture_GAD.md        WI 1
│   ├── 02_ner_methodology_GMD.md     WI 3 (methodology half)
│   └── 03_llm_methodology_GMD.md     WI 4
├── src/ador/
│   ├── core/
│   │   ├── schemas.py                canonical Entity / ExtractionResult
│   │   ├── registry.py               Processor protocol + registry
│   │   ├── router.py                 doc-type detection + dispatch
│   │   └── bootstrap.py              wires built-in processors
│   ├── ingestion/
│   │   ├── docx_loader.py            docx → KV rows
│   │   └── text_loader.py            chat / txt loader
│   ├── processors/
│   │   ├── _normalizers.py           shared value parsers (dates, money, %, ISIN)
│   │   ├── rule_based.py             WI 2
│   │   └── ner.py                    WI 3
│   ├── api/main.py                   FastAPI app
│   └── cli.py                        typer CLI
├── tests/                            32 unit + integration tests
├── data/samples/                     test fixtures (the three provided files)
├── .github/workflows/ci.yml          lint · typecheck · test matrix
├── pyproject.toml
└── README.md
```

---

## Quickstart

Requires Python ≥ 3.11.

```bash
# 1. Create and activate a virtual env
python -m venv .venv
.venv\Scripts\activate           # Windows
# source .venv/bin/activate      # macOS / Linux

# 2. Install — pick the set of extras you need
pip install -e ".[dev]"          # base + test tooling (rule-based path only)
pip install -e ".[dev,ner]"      # + HuggingFace transformers for the real NER model

# 3. Run the tests — 32 tests, < 20 s, no model downloads
pytest
```

### Demo the end-to-end flow

```bash
# Rule-based path — fast, deterministic, zero network
ador data/samples/ZF4894_ALV_07Aug2026_physical.docx

# NER path — first run downloads dslim/bert-base-NER (~400 MB) from HuggingFace
ador data/samples/FR001400QV82_AVMAFC_30Jun2028.txt

# HTTP API — open http://localhost:8000/docs for the Swagger UI
uvicorn ador.api.main:app --reload
```

> **Note for reviewers:** the first NER run downloads the HuggingFace model (~400 MB). If you'd rather skip it, the test suite already verifies the NER pipeline using an injected fake — no model weights required for `pytest` to pass.

---

## API

| Method | Path          | Purpose |
|--------|---------------|---------|
| GET    | `/health`     | Liveness + version |
| GET    | `/processors` | List registered processors and the doc types they support |
| POST   | `/extract`    | Multipart file upload → canonical `ExtractionResult` JSON |

```bash
curl -F "file=@data/samples/ZF4894_ALV_07Aug2026_physical.docx" http://localhost:8000/extract
```

The `POST /extract` endpoint auto-detects the document type from the file extension and dispatches to the registered processor. Unsupported types → **415**. Unrecoverable processor errors → **422**. Soft failures (e.g. NER model unavailable — the processor falls back to domain patterns) surface in `result.warnings`, not as an HTTP error.

---

## Design thesis

> **Right tool per document type, behind one entity contract.**

Structured → rules. Noisy short text → NER. Verbose prose → LLM. This is the load-bearing decision of the architecture — see [GAD §5.2](docs/01_architecture_GAD.md) and the trade-off table in §14.

New processors plug in by registering against the `Processor` protocol in [core/registry.py](src/ador/core/registry.py). The router, API and CLI do not change.

---

## Test coverage

```
tests/
├── test_core.py           schemas, registry, router
├── test_normalizers.py    pure value-parsing functions
├── test_rule_based.py     WI 2 — integration against the real sample docx
├── test_ner.py            WI 3 — offline (injected fake pipeline)
└── test_api.py            FastAPI TestClient end-to-end
```

32 tests, < 1 s total. The NER tests never download a model — the pipeline is dependency-injected.

---

## What's intentionally not done (PoC boundary)

- **LLM processor implementation** — WI 4 is methodology-only per the test spec. The `Processor` seam is in place; see [docs/03_llm_methodology_GMD.md §10](docs/03_llm_methodology_GMD.md) for the implementation sketch.
- **Classification, summarization, topic modelling, Q&A** — designed-for in the GAD, not implemented.
- **Production-grade AuthN/Z, tracing, full observability** — covered as design in the GAD; concrete wiring deferred.

The architecture is explicit about where these extensions land so none of them require rewrites.
