# ADOR — Global Architecture Document (GAD)

> **Work Item:** WI 1 — Architecture
> **Product:** Augmented DOcument Reader (ADOR)
> **Owner:** CMI Architecture & Innovation, Crédit Agricole CIB
> **Status:** Draft v0.1 — Proof of Concept

---

## 1. What ADOR does

ADOR ingests financial documents — trader chats, structured term sheets, PDF term sheets — and extracts financial entities: counterparty, notional, ISIN, underlying, maturity, barrier, coupon, and others.

It is consumed two ways:
- **Programmatically** by trade capture, booking, and compliance systems via REST API
- **Interactively** by front office and middle office users via a web UI

The PoC implements NER (entity extraction). The architecture is designed to also support summarization, topic modelling, and Q&A using the same routing and entity contract — those features are out of scope for this iteration.

---

## 2. The core design decision — routing by document type

The central architectural choice is: **do not use one technique for everything**. Each document type has a different structure, and the right extraction tool changes with it.

| Document type | Structure | Technique | Why |
|---------------|-----------|-----------|-----|
| `.docx` term sheet | Key:value tables, deterministic layout | **Rule-based parser** | Table cells map directly to fields. Zero inference cost, no hallucination, fully auditable. |
| Trader chat (`.txt`) | Short, noisy, financial shorthand | **Fine-tuned NER model** | Regex breaks on variations; LLM is overkill for 4-line messages; a fine-tuned NER is fast, cheap, and domain-accurate. |
| Verbose PDF term sheet | Legal prose, variable layout, cross-clause references | **LLM + RAG** | Values are buried in sentences, not tables. Only a language model can resolve "75% of the Initial Share Price defined in clause 3". |

All three processors emit into **the same canonical schema** (`ExtractionResult`). Downstream systems never know which processor ran — they always get the same typed JSON.

---

## 3. Component architecture

```
  Document (docx / txt / pdf)
          │
          ▼
  ┌───────────────────┐
  │  Ingestion layer  │  ← loads to text/blocks, format-aware
  └────────┬──────────┘
           │
           ▼
  ┌───────────────────┐
  │  Router           │  ← detects doc_type, confidentiality tier
  └────────┬──────────┘
           │
           ▼
  ┌────────────────────────────────────────┐
  │  Processor registry (Strategy pattern) │
  │  ┌────────────┐ ┌──────┐ ┌──────────┐  │
  │  │ Rule-based │ │ NER  │ │ LLM+RAG  │  │
  │  └────────────┘ └──────┘ └──────────┘  │
  └─────────────────┬──────────────────────┘
                    │
                    ▼
         ┌──────────────────┐
         │ Entity normalizer │  ← Pydantic schema, typed values
         └────────┬──────────┘
                  │
                  ▼
         ExtractionResult (JSON)
```

Each processor implements one interface: `extract(document: Path) -> ExtractionResult`. Adding a new document type (XML confirmation, HTML contract) means writing a new processor — nothing else changes.

---

## 4. Canonical entity schema

Every processor emits into one Pydantic schema. This is the contract that makes the system pluggable.

```python
class Entity(BaseModel):
    name: EntityName        # COUNTERPARTY, ISIN, NOTIONAL, MATURITY, ...
    value: str              # raw surface form from the document
    normalized: Any | None  # typed value: Decimal, date, dict, ...
    confidence: float       # 0..1
    source_span: Span       # character offsets or table cell — for audit
    extractor: ExtractorTag # "rule" | "ner" | "llm"

class ExtractionResult(BaseModel):
    document_type: DocType
    entities: list[Entity]
    warnings: list[str]     # degradation notices, validation failures
```

The `extractor` tag and `source_span` exist for auditability: every extracted value can be traced back to exactly where it came from in the source document.

---

## 5. Confidentiality-aware model routing

ADOR handles MNPI and client-identifying data. The architecture is tier-aware: before any content reaches a model, the router classifies the document and blocks egress if required.

| Tier | Document type | Allowed models |
|------|--------------|----------------|
| C1 Public | Marketing, public templates | Hosted LLM (Claude, GPT-4) |
| C2 Internal | Desanitised internal docs | Hosted in private VPC |
| C3 Restricted | Real client term sheets, chats | On-prem models only |
| C4 MNPI | In-progress deal documents | On-prem + mandatory human review |

C3/C4 documents are the majority of real workload. The LLM pipeline uses an on-prem Llama-3-70B for these. The model object in the chain swaps cleanly by tier — no pipeline code changes.

---

## 6. Sync vs. async processing

**Synchronous** — small docs, interactive use: `request → router → processor → response`. Target: < 2s (rule), < 5s (NER), < 15s (LLM).

**Asynchronous** — large docs, batch, LLM-heavy pipelines: `queue → worker → processor → webhook`. Client gets a `job_id` and polls or subscribes to a completion event.

---

## 7. Key design decisions

| Decision | Chosen | Why |
|----------|--------|-----|
| Extraction strategy | Per-doc-type routing | Cost, latency, auditability — a term sheet table does not need an LLM |
| Entity contract | Unified Pydantic schema | Downstream consumers are processor-agnostic |
| Processor pattern | Strategy + registry | New doc types drop in without touching the router |
| Model hosting | Tiered (on-prem / VPC / hosted) | Regulatory requirement — C3/C4 data cannot leave the bank |
| LLM coupling | Thin adapter (swap provider by tier) | Avoid vendor lock-in across the model tier spectrum |

---

## 8. Technology stack

| Concern | Choice |
|---------|--------|
| Language | Python 3.11+ |
| API | FastAPI + Pydantic v2 |
| Doc parsing | `python-docx`, `pdfplumber` |
| NER | HuggingFace `transformers` |
| LLM orchestration | LangChain (RAG, retrieval, prompt chains) |
| Vector store | FAISS (PoC) → `pgvector` (production) |
| Embeddings | `multilingual-e5-base` (on-prem), `text-embedding-3-large` (C1/C2) |
| Packaging | `pyproject.toml`, `ruff`, `mypy`, `pytest` |
