# ADOR — Study Guide

> Everything you need to discuss this project confidently: the business problem, the financial vocabulary, the architecture decisions, and the likely questions a panel will ask. Read top-to-bottom.

---

## Part 1 — The business problem

**Who asked for this?** CACIB (Crédit Agricole CIB, the corporate & investment bank of Crédit Agricole). Inside CACIB, the **CMI Architecture & Innovation** team — they design new systems for the bank. You've been asked to design + prototype an AI tool for them.

**What is CMI's pain today?** When a trader wants to do a deal, information flows through several documents:

1. A **trader chat** (*"I'll revert regarding BANK ABC to try to do another 200 mio at 2Y …"*) — short, abbreviated, live negotiation.
2. A **term sheet** — the structured summary of the deal's economics. Some are clean tables (our docx); some are verbose legal prose (our pdf).
3. A **confirmation**, then a **contract**, then a **booking** in the trading system.

Today most of the extraction between these is **manual typing**. A human reads the term sheet, types the notional into a booking screen. This is:
- slow (bottleneck on trade capture),
- error-prone (typos on notional = P&L risk),
- unaudited (no record of what was read where).

**What ADOR fixes.** ADOR stands for **Augmented DOcument Reader**. It reads any of those documents and extracts the structured information automatically — faster, more consistent, with an audit trail pointing to the exact spot the number came from.

---

## Part 2 — The product vision (and what you built)

ADOR is designed to do **five things** eventually:

1. **Classify** a document (is it a term sheet? a chat? a KYC form?)
2. **Summarize** it
3. **Topic modelling** — discover the main topics in a document or corpus
4. **NER** — extract named entities (the numbers, dates, counterparties)
5. **Q&A** — answer natural-language questions about the document

**For this 3-hour PoC you only had to build NER.** The other four are designed-for in the architecture (so the system can grow into them) but not implemented.

---

## Part 3 — Financial vocabulary crash course

You will be asked questions that assume you know these. Learn them.

| Term | What it means (in plain English) |
|------|----------------------------------|
| **Term sheet** | The summary document of a deal. Before the full legal contract is written, both parties agree on the *terms* in a term sheet. |
| **Counterparty** | The other party in a deal. If CACIB sells a product to Bank ABC, then Bank ABC is CACIB's counterparty. |
| **Party A / Party B** | Legal naming in term sheets. Usually Party A = client, Party B = the bank (CACIB itself here). So "Party A" maps to our `COUNTERPARTY` entity. |
| **Notional** | The reference amount of a deal. "200 mio" means "the contract references 200 million [of currency]". It's not necessarily money that changes hands — it's the size of the deal. |
| **ISIN** | *International Securities Identification Number*. A 12-character code that uniquely identifies a security worldwide. Example: `FR001400QV82`. Format: 2-letter country + 9 alphanumeric + 1 check digit. |
| **Underlying** | The asset the product is based on. If you sell an equity-linked note "on Allianz SE", Allianz SE is the underlying. |
| **Maturity / Termination Date** | When the deal ends. "2Y" means 2-year maturity. |
| **Tenor** | Synonym for maturity (in shorthand: "2Y", "18M", "30D"). |
| **Evergreen (EVG)** | The deal auto-renews unless cancelled. "2Y EVG" = 2-year but auto-rolling. |
| **Coupon** | Periodic payment. "Coupon = 5%" means the buyer receives 5% of notional periodically. |
| **Barrier** | A trigger level. "Barrier 75% of Share_initial" means: if the underlying ever falls below 75% of its starting price, something changes (protection is lost, for example). |
| **Bid / Offer** | Prices at which you can sell (bid) or buy (offer). In our chat "offer 2Y EVG estr+45bps" = "I'm offering the client a 2-year evergreen deal at ESTR + 45 basis points". |
| **Basis points (bps)** | 1/100 of 1%. So 45bps = 0.45%. Used because interest rate moves are small. |
| **ESTR** | *Euro Short-Term Rate*. The benchmark overnight interest rate for the euro area. "estr+45bps" = ESTR + 0.45%. |
| **SOFR / LIBOR / EURIBOR / SONIA** | Same idea, different currencies/markets. |
| **Payment frequency** | How often coupons pay. Quarterly, monthly, etc. |
| **Initial Valuation Date** | The date on which the underlying's price is first observed (the reference starting point). |
| **Valuation Date** | The date on which the final observation happens to determine payoff. |
| **Calendar / Business Day convention** | Which holiday calendar governs dates. "TARGET" = the Eurozone interbank calendar. |
| **ISDA** | *International Swaps and Derivatives Association*. Governing framework for most derivative contracts. "ISDA Documentation: Option" means this deal is documented under ISDA with an Option template. |

---

## Part 4 — The core design insight (say this in the discussion)

> **"One size doesn't fit all. We route each document to the cheapest technique that can reliably solve it, behind one common entity contract."**

Why this matters:

| Document | Challenge | Right tool | Why |
|----------|-----------|------------|-----|
| Structured docx | Already in a table, key:value layout | **Rule-based parser** | Deterministic, free, auditable, zero hallucination risk. Using an LLM here would be *wasteful and riskier*. |
| Trader chat | Short, noisy, abbreviated | **Fine-tuned NER model** | Regex too brittle for paraphrase; LLM is overkill for 4 lines; a small trained NER is fast + cheap + accurate. |
| Verbose PDF | Legal prose, cross-clause references | **LLM + RAG** | Needs narrative understanding. Rules/NER can't resolve "Barrier = 75% of Initial Price" where Initial Price is defined three pages earlier. |

Analogy to use in the room:
- Rule-based = reading a printed form.
- NER = a human who learned to read this kind of shorthand.
- LLM = a junior analyst who reads the whole contract to understand it.

You wouldn't hire the analyst to fill in a checkbox form. You wouldn't give a checkbox form to a lawyer.

---

## Part 5 — Walk through each Work Item

### WI 1 — Global Architecture Document (GAD)

**What it is:** A written design document describing how ADOR fits into the bank's IT landscape. Not code. Document at [01_architecture_GAD.md](01_architecture_GAD.md).

**Key sections to remember:**

1. **Context diagram (§4).** Shows ADOR sitting between inputs (users, chat platforms, email, trade capture) and the CMI information system.
2. **Functional architecture (§5).** The 5 features. The "routing" diagram (§5.2) is the **core thesis** — learn this table.
3. **Component architecture (§6).** Ingestion → Classifier/Router → Processor registry → Normalizer → Persistence. Cross-cutting: auth, audit, logging, tracing.
4. **Sync vs async (§7).** Interactive use = synchronous. Bulk jobs or LLM-heavy work = asynchronous via a queue. The client chooses.
5. **Communication channels (§8).** UI upload, REST API, event bus (Kafka), email gateway. All land on the same backend.
6. **Confidentiality tiers (§9.1).** C1 public → C4 MNPI. **This is the question that will separate senior from junior candidates.** Know it:

   | Tier | Data | Allowed model |
   |------|------|---------------|
   | C1 | Public | Hosted frontier LLM ok |
   | C2 | Internal | LLM in CMI VPC |
   | C3 | Client term sheets | On-prem only — no egress |
   | C4 | Deal-in-progress, MNPI | On-prem + 4-eyes audit |

   The classifier decides the tier **before** any content hits a model. Enforcement is in code and at the network.

7. **Observability, NFRs, stack, trade-offs (§11–14).**

---

### WI 2 — Rule-based docx parser

**Target file:** `ZF4894_ALV_07Aug2026_physical.docx` — a two-column table term sheet.

**Flow of the code:**

```
docx file
   │
   ▼
docx_loader.load_kv_rows()      ← reads every <tbl><tr><tc> in the document
   │                              returns list of KVRow(label, value, ref)
   │                              ref = "table:0:row:6" for provenance
   ▼
rule_based.RuleBasedDocxProcessor.extract()
   │
   ├── for each row:
   │      normalize_label("Notional Amount (N)") → "notional amount"
   │      lookup in LABEL_MAP → (EntityName.NOTIONAL, parse_notional)
   │      parse_notional("EUR 1 million") → {"currency":"EUR","amount":1e6}
   │      build Entity(name, value, normalized, source_span, extractor=RULE)
   │
   ▼
ExtractionResult(entities=[...], warnings=[...])
```

**Why it's clean:**
- `LABEL_MAP` is **declarative** — adding a new template means adding one row, not writing code.
- Normalizers (`parse_date`, `parse_notional`, `parse_percent`, ...) are **pure functions**, unit-tested in isolation.
- Every entity carries `source_span` (e.g. `table:0:row:6`) so reviewers can click-through to the source cell.
- Zero hallucination risk: if the label isn't in `LABEL_MAP`, the row is ignored.

**What the panel might ask:**
- *"What happens with a new template?"* → Add entries to `LABEL_MAP`. If the label itself is totally new, so is the entity — that's a schema question for the business.
- *"Why not LLM?"* → Deterministic, free, auditable. We already got 9/9 entities with zero warnings. Using an LLM here adds cost and hallucination risk for no gain.
- *"What if the docx has no tables?"* → Swap the loader. The processor doesn't care — the contract is `list[KVRow]`.

---

### WI 3 — NER model + fine-tuning methodology

**Target file:** `FR001400QV82_AVMAFC_30Jun2028.txt` — a trader chat message.

**Two-stage design:**

**Stage 1: general-purpose NER.** Load a pretrained model like `dslim/bert-base-NER`. It's been trained on a generic English corpus (news articles) and knows four classes: **PER** (people), **ORG** (organisations), **LOC** (locations), **MISC**. Run it on the chat → it tags `BANK ABC` as `ORG`. We map `ORG → COUNTERPARTY`.

```
text  →  HuggingFace pipeline  →  [{entity_group:"ORG", word:"BANK ABC", ...}]
                                           │
                                           ▼
                        map to canonical entity → Entity(COUNTERPARTY, "BANK ABC")
```

**Stage 2: domain patterns (stopgap).** The general model doesn't know what an ISIN looks like. It doesn't know "200 mio" is a notional. It will never guess "2Y EVG" is a tenor. We don't have time in a 3-hour PoC to fine-tune a model. So we include **explicit regex patterns** for the domain entities — clearly labelled as "bridge until fine-tuning".

**Fine-tuning methodology (the GMD, [02_ner_methodology_GMD.md](02_ner_methodology_GMD.md)).** This is the "methodology document" deliverable — it explains how to *replace* the regex stopgaps with a model that natively knows these finance entities.

Key ideas in the GMD:
1. **Custom label schema** — add BIO tags for our entities: `B-NOTIONAL`, `I-NOTIONAL`, `B-ISIN`, etc.
2. **Data sources** — (a) hand-label chats, (b) silver labels from joining chats to their booked trades (the booking knows the correct notional; tag the chat span that matches).
3. **Annotation strategy** — two annotators, inter-annotator agreement ≥ 0.85, active learning loop.
4. **Training recipe** — HuggingFace `Trainer`, DeBERTa-v3-base, 5 epochs, 3e-5 LR. Or LoRA adapters for fast iteration.
5. **Evaluation** — per-entity F1 with `seqeval`, stratified splits, regression set of tricky cases.
6. **Deployment** — same `NerPipeline` Protocol as the stub, so swapping the fine-tuned model is a config change, not a code change.
7. **Continual learning** — UI review queue feeds corrections back into training data.

**What the panel might ask:**
- *"Why not just use an LLM to extract from the chat?"* → Cost, latency, hallucination. An NER pipeline runs in milliseconds; an LLM call is seconds + dollars. For short, repetitive text a fine-tuned NER wins on every axis.
- *"How much labelled data do you need?"* → ~500 gold + 2k silver for PoC; 2k gold + 10k silver for pilot. Silver labels from bookings are key.
- *"What's your label schema?"* → BIO over the 8 entities in the test spec (COUNTERPARTY, NOTIONAL, ISIN, UNDERLYING, MATURITY, BID, OFFER, PAYMENT_FREQUENCY).
- *"What's hardest?"* → UNDERLYING. It's multi-word, typo-prone, sometimes in multiple languages.

---

### WI 4 — LLM entity extraction methodology

**Target file:** `BankABC_TermSheet_Template.pdf` — verbose legal prose. (Notice the file is a **template** — it's full of `XX` placeholders. That's deliberate.)

**No code deliverable**, only a methodology document: [03_llm_methodology_GMD.md](03_llm_methodology_GMD.md).

**Pipeline shape:**

```
PDF  →  1. Parse & layout    (unstructured / Textract / OCR fallback)
        │
        ▼
        2. Chunk by defined-term blocks (800-token fallback)
           carry metadata: page, section, byte offsets
        │
        ▼
        3. Retrieve  (RAG — if doc doesn't fit in context window)
           hybrid BM25 + dense embeddings
           rerank with cross-encoder
           per-entity query expansion
           always include "defined-term" chunks
        │
        ▼
        4. Prompt LLM via TOOL USE (JSON schema derived from our Entity)
           force grounded quotes: each entity must cite its supporting sentence
           refuse to guess: placeholders → `missing`, not made-up values
        │
        ▼
        5. Validate in layers:
           - schema validation
           - grounding (quote must be substring of source chunk)
           - type normalisation (dates, %, ISIN)
           - cross-field sanity (dates in order; barrier in 0..1)
           - self-consistency (sample k=3 for high-stakes fields)
        │
        ▼
        6. Emit into canonical ExtractionResult (same schema as rule-based & NER)
```

**Key ideas to mention:**

1. **Tool use, not free-form JSON.** Force the LLM to call a function with a typed schema. You get guarantees, not prayers.
2. **Grounding.** Every entity must include a quote from the source. If the quote doesn't substring-match the source chunk, we drop it. This kills the most dangerous failure mode (a confident hallucination).
3. **RAG only when needed.** If the doc fits in the context window, don't RAG — retrieval introduces its own failure mode. RAG is not a default; it's an escalation.
4. **Confidentiality routing.** Real client term sheets are C3 — they go to an **on-prem** model (Llama-3-70B, Mistral-Large). Never to a hosted LLM. This ties directly back to the GAD.
5. **Evaluation.** Gold set of ~200 hand-annotated PDFs, per-entity F1 (exact + normalised match), hallucination rate <1%, calibration.
6. **LLM-as-judge carefully.** Use another LLM to grade paraphrase equivalence, but never to grade extraction end-to-end — LLM judges are lenient on plausible hallucinations.

**What the panel might ask:**
- *"Why tool use instead of parsing JSON from the response?"* → Schema-guaranteed output; the model can't return something malformed. Retries on validation failure come free.
- *"How do you prevent hallucinations?"* → Six layers (schema → grounding → normalisation → cross-field → self-consistency → refusal-to-guess). Grounding is the most important: if there's no supporting quote, no entity.
- *"Will you send client data to OpenAI?"* → No. Confidentiality tier routing (see GAD §9.1). C3/C4 goes to on-prem models. Hard network gate, not just code.
- *"When RAG, when not?"* → Decision tree: short doc → no RAG. Long doc → RAG. Corpus-level Q&A → RAG. Don't RAG by default; retrieval is a risk surface.

---

## Part 6 — How the pieces fit together (architecture tour)

Everything hangs off **three contracts**:

### 1. `EntityName` + `Entity` + `ExtractionResult`  ([core/schemas.py](../src/ador/core/schemas.py))

This is the **canonical output**. Every processor emits this shape. Downstream consumers (API, DB, trade capture system) only ever read this. If we add a new processor tomorrow, consumers don't change.

```python
class Entity:
    name: EntityName           # COUNTERPARTY, NOTIONAL, ISIN, …
    value: str                 # raw surface form
    normalized: Any            # typed/canonical: date ISO, {currency, amount}, …
    confidence: float          # 0..1
    source_span: Span          # offsets or "table:0:row:6" for audit
    extractor: ExtractorTag    # rule | ner | llm (who produced it)
```

### 2. `Processor` Protocol  ([core/registry.py](../src/ador/core/registry.py))

```python
class Processor(Protocol):
    name: str
    def supports(self) -> set[DocType]: ...
    def extract(self, document: Path) -> ExtractionResult: ...
```

This is the **Strategy pattern**. Every extractor implements this three-line contract:
- `RuleBasedDocxProcessor` for WI 2
- `NerChatProcessor` for WI 3
- (future) `LlmPdfProcessor` for WI 4

The registry maps `DocType → Processor`. The router picks the processor by doc type. Adding a new one = registering it. No other file changes.

### 3. The router  ([core/router.py](../src/ador/core/router.py))

```python
detect_doc_type(path)  →  DocType.DOCX_TERMSHEET / CHAT / PDF_TERMSHEET
         │
registry.for_type(doc_type)  →  the right Processor
         │
processor.extract(path)  →  ExtractionResult
```

In the PoC, detection is by file extension. In production, this is replaced by a **learned classifier** (a small transformer or sklearn model that also computes the confidentiality tier, see GAD §5.1). Interface stays the same — so the classifier swaps in without rewrites.

---

## Part 7 — Code tour (what lives where, in one page)

```
src/ador/
├── core/
│   ├── schemas.py         the Entity contract. Learn this file first.
│   ├── registry.py        Processor protocol + registry (Strategy pattern)
│   ├── router.py          doc-type detection + dispatch
│   └── bootstrap.py       wires built-in processors into the default registry
├── ingestion/
│   ├── docx_loader.py     docx → KVRow(label, value, ref)
│   └── text_loader.py     txt → str
├── processors/
│   ├── _normalizers.py    pure: parse_date, parse_notional, parse_percent, …
│   ├── rule_based.py      WI 2: LABEL_MAP + extract()
│   └── ner.py             WI 3: stage-1 HF pipeline + stage-2 domain patterns
├── api/main.py            FastAPI: /health, /processors, POST /extract
└── cli.py                 typer CLI

docs/
├── 01_architecture_GAD.md       WI 1 (read this whole doc)
├── 02_ner_methodology_GMD.md    WI 3 methodology half
├── 03_llm_methodology_GMD.md    WI 4 (whole deliverable)
└── STUDY_GUIDE.md               this file

tests/
├── test_core.py           schemas/registry/router smoke
├── test_normalizers.py    date/money/percent parsers
├── test_rule_based.py     WI 2 against the real docx
├── test_ner.py            WI 3 with injected fake NER pipeline
└── test_api.py            FastAPI TestClient end-to-end
```

---

## Part 8 — The questions you will be asked (with answers)

**Q1. "Walk me through your design."**
> Start with the core insight: route by doc type to the cheapest reliable technique, behind one entity contract. Three techniques (rules/NER/LLM) for three doc shapes (structured/short-noisy/verbose-prose). One canonical `ExtractionResult`. Pluggable via a `Processor` protocol. The router picks by doc type — in PoC by extension, in production via a learned classifier that also computes confidentiality tier.

**Q2. "Why not use an LLM for everything?"**
> Cost, latency, determinism, auditability, confidentiality. For structured docx we already have deterministic ground truth in the table layout — an LLM adds hallucination risk and cost. For chats, a fine-tuned NER runs in milliseconds for fractions of a cent. LLMs earn their keep only on the verbose prose where narrative understanding is the bottleneck.

**Q3. "What about hallucinations?"**
> For rules → impossible (deterministic). For NER → bounded by the model's span, can't invent content. For LLM → the risk is real, so the methodology has six defensive layers (schema validation, source grounding via required quotes, type normalisation, cross-field sanity, self-consistency sampling for high-stakes fields, and an explicit "refuse to guess" rule in the system prompt). Grounding is the strongest lever: if the LLM can't quote the source, we drop the entity.

**Q4. "How do you handle confidentiality?"**
> GAD §9.1 defines four tiers. The classifier computes the tier before content is routed. C1/C2 may use hosted or VPC-private LLMs. C3 (client term sheets) and C4 (MNPI) are on-prem only. Enforcement is in code AND at the network layer — no data egress path exists for restricted tiers. Audit log records tier, model version, retrieved chunks.

**Q5. "How would you fine-tune the NER model?"**
> HuggingFace `Trainer` on DeBERTa-v3-base, BIO label schema over our 8 chat entities. Data: ~2k hand-labelled chats (Prodigy + two annotators, κ ≥ 0.85) plus ~10k silver-labelled from joining chats to booked trades (the booking carries the canonical values). Active learning loop to cut annotation cost by ~60%. Per-entity F1 gating (targets like 0.95 for counterparty, 0.98 for ISIN thanks to its syntactic regularity).

**Q6. "Why RAG for PDFs? Why not just feed the whole doc?"**
> Depends on length. Term sheets in the 10–20 page range usually fit modern context windows — no RAG needed, eliminates retrieval errors as a failure mode. RAG is an escalation for longer docs or corpus-level work. When we do RAG: hybrid BM25 + dense, cross-encoder rerank, per-entity query expansion, always include the "defined-term" chunks so cross-clause references resolve.

**Q7. "Sync vs async — when?"**
> Small interactive calls → sync, budget p95 < 5s. Large docs, batches, LLM-heavy work → async via queue + webhook. The client chooses with a header. Backpressure handled by queue depth; workers scale horizontally on queue lag.

**Q8. "What's your observability story?"**
> Structured JSON logs with request_id, doc_hash, tier, processor, duration, model version. OpenTelemetry traces across ingestion → router → processor → storage. Per-processor metrics (QPS, latency histogram, entity-count distribution, LLM token spend). Drift monitoring on entity distribution week-over-week. Human review queue samples 1% of outputs for ground-truth feedback.

**Q9. "What did you deliberately skip?"**
> (1) The LLM processor is methodology-only per the test spec — the architectural seam is in place, implementation is a one-file drop-in. (2) The other four features (classification, summarization, topic, Q&A) are designed-for in the GAD but not built — they land on the same routing + entity contract. (3) Auth/authz, full tracing, regulatory archive — described as design, concrete wiring deferred.

**Q10. "What's the weakest part?"**
> Be honest. Suggest: *"The domain stopgaps in the NER processor aren't production-grade — they're regexes. I've written them up as a bridge until fine-tuning, and the methodology document details exactly how to replace them. The second weakest is PDF layout parsing — I'd want to validate on more documents before committing to a specific parser (unstructured vs. Textract)."*

**Q11. "What would you do with 3 more hours?"**
> Implement the LLM processor skeleton against the stub in GMD §10, wire Anthropic's SDK for a real call, add a confidentiality gate at the API boundary, and write an end-to-end test that runs all three processors against the three sample files.

**Q12. "What would you do with 3 more days?"**
> (1) Fine-tune the NER model on a small annotated set using the GMD recipe. (2) Replace filename-based doc detection with a small classifier. (3) Add the classification feature (doc_type + tier) — it's the only feature other than NER on the critical path to any of the others. (4) Observability: structured logs, OTel traces, basic Grafana dashboard.

---

## Part 9 — Things to say that make you sound senior

- *"We route by doc type behind one entity contract."* (the thesis)
- *"The architectural seam is in place — implementation is a one-file drop-in."* (for anything deferred)
- *"I'd rather return 'unknown' than a plausible wrong answer."* (on hallucination)
- *"Grounding is the strongest lever."* (on LLM safety)
- *"Silver labels from bookings unlock data volume without annotation cost."* (on fine-tuning)
- *"RAG is an escalation, not a default."* (on LLM design)
- *"The classifier computes the tier before content touches a model."* (on confidentiality)
- *"Deterministic where we can, learned where we must."* (overall philosophy)

---

## Part 10 — 60-second pitch

*"ADOR extracts structured entities from financial documents. The key insight is that different document types need different techniques — a structured term sheet doesn't need an LLM, a verbose PDF absolutely does, and a trader chat sits in between. So we route by document type: docx goes to a rule-based parser, chat goes to a fine-tuned NER model, PDF goes to an LLM-with-RAG pipeline. All three emit into one canonical schema, so downstream consumers — trade capture, compliance, the UI — never care which backend produced the answer. The processors plug into a registry via a three-method Protocol, so adding a new document type is registration, not a rewrite. Security-wise, confidentiality tiers are computed before content is routed, and restricted-tier data never reaches hosted LLMs — enforced in code and at the network. The PoC ships with WI 1 (the architecture doc), WI 2 (rule-based parser, 9/9 entities extracted), WI 3 (NER runner + fine-tuning methodology), WI 4 (LLM methodology), plus a FastAPI layer and 30 tests."*

That's the whole thing.
