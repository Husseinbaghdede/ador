# LLM Entity Extraction — Global Methodology Document (GMD)

> **Work Item:** WI 4 — LLM
> **Status:** Methodology only. Implementation slots into `processors/llm.py` behind the existing `Processor` interface.

---

## 1. Why an LLM for PDF term sheets

The docx term sheet has a clean table — a rule reads it directly. The trader chat is short and noisy — a NER model handles it. The PDF term sheet is a different problem.

Consider how the barrier level appears in the sample term sheet:

> *"...the Barrier Level shall be set at seventy-five percent (75%) of the Initial Share Price, being the Official Closing Price of the Underlying Share on the Exchange on the Initial Valuation Date..."*

Three reasons rules and NER both fail here:

1. **No label** — there is no `Barrier: 75%` row. The value is buried inside a legal sentence.
2. **Cross-clause reference** — "Initial Share Price" is defined two pages earlier in a different section. You need to read both clauses to understand what 75% is of.
3. **Ambiguity** — the same "75%" could be a barrier, a coupon, a conversion ratio, or a recovery rate depending on context. Only reading the full sentence resolves it.

An LLM reads the clause in full, understands the legal phrasing, and resolves cross-references. That is the capability that makes it the right tool for this document class.

The entities to extract from the PDF term sheet are:

| Entity | Example from sample |
|--------|---------------------|
| Counterparty | BANK ABC |
| Initial Valuation Date | 31 January 2025 |
| Notional | EUR 1 million |
| Valuation Date | 31 July 2026 |
| Maturity | 07 August 2026 |
| Underlying | Allianz SE (ISIN DE0008404005, Reuters: ALVG.DE) |
| Coupon | 0% |
| Barrier | 75.00% of Share_ini |
| Calendar | TARGET |

---

## 2. Pipeline overview

```
PDF
 ↓
1. PARSE — extract text from the PDF preserving reading order
 ↓
2. CHUNK — split into overlapping passages with metadata
 ↓
3. EMBED & INDEX — convert chunks to vectors, store in vector DB
 ↓
4. RETRIEVE — for each entity, find the most relevant chunks (RAG)
 ↓
5. PROMPT LLM — structured output with evidence quote required
 ↓
6. VALIDATE — grounding check, normalisation, sanity checks
 ↓
ExtractionResult (same canonical schema as rule-based and NER)
```

---

## 3. PDF Parsing

For a digital PDF (text is embedded), `pdfplumber` preserves reading order across multi-column layouts and handles embedded tables:

```python
import pdfplumber

def parse_pdf(path: str) -> list[dict]:
    blocks = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                blocks.append({
                    "text": text,
                    "page": i + 1,
                    "source": path,
                })
    return blocks
```

For scanned PDFs (pages are images with no embedded text), an OCR step runs first using `PaddleOCR` (best accuracy, multilingual, on-prem) or `pytesseract` (simpler setup). The output is the same list of text blocks regardless of which path ran — downstream stages are unaware of the difference.

---

## 4. Chunking

A 40-page term sheet has tens of thousands of tokens — too many to send to the LLM for every entity. Chunking breaks the document into passages, and retrieval selects only the relevant ones.

We use LangChain's `RecursiveCharacterTextSplitter` which tries to split on paragraph boundaries first, then sentence boundaries, then words — never mid-sentence:

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document

splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=100,   # overlap prevents entities at boundaries from being missed
    separators=["\n\n", "\n", ". ", " "],
)

chunks = splitter.create_documents(
    texts=[b["text"] for b in blocks],
    metadatas=[{"page": b["page"], "source": b["source"]} for b in blocks],
)
```

The 100-token overlap is important — without it, an entity that straddles a chunk boundary (e.g. "Barrier Level shall be set at" in one chunk, "75%" in the next) would be missed entirely. The metadata (page number, source path) flows through to `Entity.source_span.ref` in the final output, giving auditors an exact location in the document for every extracted value.

---

## 5. Embeddings and Vector Store

Each chunk is converted to a dense vector (embedding) that captures its meaning. Similar meanings produce nearby vectors. When we search for "barrier level", the retriever finds the chunk about "knock-in threshold" even if those exact words don't appear together.

**Embedding models:**

| Model | Use case |
|-------|---------|
| `intfloat/multilingual-e5-base` | On-prem — handles French + English. Best for C3/C4 documents. |
| `BAAI/bge-m3` | On-prem — state-of-the-art open-source, slightly better quality. |
| `text-embedding-3-large` (OpenAI) | Hosted — highest quality, C1/C2 only (data egress). |

**Vector stores:**

| Store | Use case |
|-------|---------|
| `FAISS` | Local development and PoC — no server needed. |
| `pgvector` | Production — Postgres extension, no new infrastructure, ACID transactions. |
| `Chroma` | Lightweight persistent store for small deployments. |

```python
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS, PGVector

embeddings = HuggingFaceEmbeddings(
    model_name="intfloat/multilingual-e5-base",
    encode_kwargs={"normalize_embeddings": True},
)

# PoC / local
vectorstore = FAISS.from_documents(chunks, embeddings)

# Production
vectorstore = PGVector.from_documents(
    documents=chunks,
    embedding=embeddings,
    connection_string="postgresql+psycopg2://user:pass@db/ador",
    collection_name="term_sheet_chunks",
)
```

---

## 6. Retrieval (RAG)

RAG — Retrieval-Augmented Generation — means: instead of sending the whole PDF to the LLM, retrieve only the 3-5 most relevant chunks per entity and send those. This keeps prompts focused and costs low.

We use **hybrid retrieval** — combining dense semantic search with BM25 keyword search. Dense search handles paraphrased text ("protection floor" vs "barrier level"). BM25 handles exact rare tokens (ISIN codes, clause numbers). Together they are measurably better than either alone on financial documents.

```python
from langchain.retrievers import BM25Retriever, EnsembleRetriever
from langchain.retrievers.document_compressors import CrossEncoderReranker
from langchain.retrievers import ContextualCompressionRetriever
from langchain_community.cross_encoders import HuggingFaceCrossEncoder

# Dense retriever
dense = vectorstore.as_retriever(search_kwargs={"k": 20})

# BM25 keyword retriever
bm25 = BM25Retriever.from_documents(chunks, k=20)

# Hybrid: merge both rankings with reciprocal-rank fusion
ensemble = EnsembleRetriever(
    retrievers=[bm25, dense],
    weights=[0.4, 0.6],
)

# Cross-encoder reranker: re-scores top 20 → top 5
# More accurate than similarity alone but too slow to run on full corpus
reranker = CrossEncoderReranker(
    model=HuggingFaceCrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2"),
    top_n=5,
)
retriever = ContextualCompressionRetriever(
    base_compressor=reranker,
    base_retriever=ensemble,
)
```

We run retrieval **once per entity group**, not once for the whole document. Each entity has its own focused query with synonyms:

```python
ENTITY_QUERIES = {
    "barrier":   "barrier level knock-in threshold protection percentage",
    "notional":  "notional amount principal financing aggregate investment",
    "maturity":  "termination date maturity tenor final redemption date",
    "underlying":"underlying share reference asset linked to",
    "coupon":    "coupon rate interest annual fixed rate",
}
```

---

## 7. Prompting Strategy

The most important rule: **never ask the LLM for free-form text**. Use structured output — the model is forced to return a typed JSON object conforming to our schema. Anything that doesn't conform is rejected immediately.

LangChain's `.with_structured_output()` handles this cleanly:

```python
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate

class EntityEvidence(BaseModel):
    quote: str      # exact sentence from the document
    chunk_ref: str  # page reference

class ExtractedEntity(BaseModel):
    name: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: EntityEvidence

class ExtractionOutput(BaseModel):
    entities: list[ExtractedEntity]
    missing: list[str]   # fields not found — declare, do not guess

# Model selection based on confidentiality tier
def get_llm(tier: str):
    if tier in ("C3", "C4"):
        return ChatOllama(model="llama3:70b", base_url="http://llm.cacib.internal")
    return ChatAnthropic(model="claude-opus-4-7", temperature=0.0)

llm = get_llm("C3")
structured_llm = llm.with_structured_output(ExtractionOutput)
```

**System prompt:**

```python
SYSTEM = """You are a financial entity extractor for CIB term sheets at Crédit Agricole CIB.
You receive excerpts from a PDF term sheet. Extract the financial entities requested.

Rules:
(a) For every entity, include the exact supporting sentence in evidence.quote.
    If you cannot find one, put the field in missing — never guess.
(b) value must be the raw text exactly as it appears in the document. No paraphrasing.
(c) Placeholders like "XX" or "[TBD]" mean the field is not filled in.
    Put them in missing — never invent a value.
(d) Return at most one entity per field. Use the most explicit statement if repeated.
(e) Confidence: 0.9+ for a directly labelled value, 0.7-0.8 for an inferred value.
"""

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM),
    ("human", "Entities to extract: {entity_list}\n\nDocument excerpts:\n\n{context}"),
])

chain = prompt | structured_llm
```

**Running the chain:**

```python
context_docs = retriever.invoke(ENTITY_QUERIES["barrier"])
result = chain.invoke({
    "entity_list": "barrier, coupon, notional",
    "context": "\n\n---\n\n".join(d.page_content for d in context_docs),
})
# result.entities → list of validated ExtractedEntity objects
# result.missing  → list of field names not found in the document
```

---

## 8. Validation and Hallucination Control

After the LLM responds, three checks run before emitting any entity:

**1. Source grounding** — `evidence.quote` must exist as a near-exact substring of the retrieved chunks. If the quote is not in the source, the entity is dropped and a warning is emitted. This is the primary hallucination guard — an invented value cannot also come with an invented quote that happens to appear verbatim in the document.

```python
from difflib import SequenceMatcher

def is_grounded(quote: str, chunks: list, threshold: float = 0.90) -> bool:
    return any(
        SequenceMatcher(None, quote, c.page_content).ratio() >= threshold
        for c in chunks
    )
```

**2. Normalisation** — the same parsers from `processors/_normalizers.py` used by the rule-based and NER processors are applied. Dates, notionals, percentages all go through the same typed conversion. A value that fails to parse gets a warning and reduced confidence.

**3. Cross-field sanity checks** — logical consistency: `initial_valuation_date ≤ valuation_date ≤ maturity`, barrier strictly between 0 and 1, ISIN passes its check-digit. Violations surface as warnings, not silent corrections.

---

## 9. Model Selection and Confidentiality

Most client term sheets are C3 (restricted) or C4 (MNPI). These cannot be sent to hosted APIs — a regulatory requirement, not a preference.

| Tier | Document type | Model |
|------|--------------|-------|
| C1 Public | Marketing, public templates | Claude Opus 4.7 / GPT-4 (hosted) |
| C2 Internal | Desanitised internal documents | Hosted model in private VPC |
| C3 Restricted | Real client term sheets | Llama-3-70B on-prem (CACIB data centre) |
| C4 MNPI | In-progress deal documents | Same as C3 + mandatory human review |

A well-prompted on-prem 70B model with good RAG reaches around 85-90% of hosted frontier model quality on this task. That trade-off is correct given the confidentiality constraint. The LLM object in the chain swaps cleanly between tiers — no other code changes.

---

## 10. Implementation Seam

```python
# src/ador/processors/llm.py  (to be implemented)

class LlmPdfProcessor:
    name = "llm_pdf"

    def supports(self) -> set[DocType]:
        return {DocType.PDF_TERMSHEET}

    def extract(self, document: Path) -> ExtractionResult:
        blocks  = parse_pdf(str(document))
        chunks  = chunk_blocks(blocks)
        store   = FAISS.from_documents(chunks, embeddings)
        retriever = build_hybrid_retriever(store, chunks)
        chain   = EXTRACTION_PROMPT | get_llm(tier).with_structured_output(ExtractionOutput)

        entities, warnings = [], []
        for group in ENTITY_GROUPS:
            docs = retriever.invoke(group["query"])
            raw  = chain.invoke({
                "entity_list": group["names"],
                "context": format_context(docs),
            })
            entities.extend(validate_and_ground(raw, docs, warnings))

        return ExtractionResult(
            document_type=DocType.PDF_TERMSHEET,
            entities=entities,
            warnings=warnings,
        )
```

Emits the same `ExtractionResult` as the rule-based and NER processors. The router, API, and CLI do not change.
