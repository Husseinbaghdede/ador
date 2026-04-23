# NER Methodology — Global Methodology Document (GMD)

> **Work Item:** WI 3 — NER
> **Companion code:** [`src/ador/processors/ner.py`](../src/ador/processors/ner.py)

---

## 1. The problem with a general-purpose NER model

The code runs `dslim/bert-base-NER` — a BERT model trained on news articles. It knows four labels: PER, ORG, LOC, MISC. On the sample trader chat:

```
11:49:05 I'll revert regarding BANK ABC to try to do another 200 mio at 2Y
FR001400QV82    AVMAFC FLOAT    06/30/28
offer 2Y EVG estr+45bps
estr average Estr average / Quarterly interest payment
```

It correctly finds `BANK ABC` as ORG → Counterparty. Everything else it misses entirely. `FR001400QV82`, `estr+45bps`, `200 mio`, `2Y EVG` — none of this exists in news articles. The model has never seen financial shorthand and cannot recognise it.

The current stopgap is domain regex patterns. They work for the sample data but break on any variation: "two yards" instead of "200 mio", "48 over" instead of "estr+48bps", "trimestriel" instead of "Quarterly". The correct solution is fine-tuning the model on real financial chat data so it understands the domain natively.

---

## 2. Target entities

Based on the test specification, the entities to extract from trader chats are:

| Entity | Example from sample chat |
|--------|--------------------------|
| Counterparty | `BANK ABC` |
| Notional | `200 mio` |
| ISIN | `FR001400QV82` |
| Underlying | `AVMAFC FLOAT 06/30/28` |
| Maturity | `2Y EVG` |
| Bid | `estr+45bps` |
| Offer | *(empty in sample — depends on chat context)* |
| PaymentFrequency | `Quarterly` |

These become the fine-tuning label set. Each maps directly to `EntityName` in `core/schemas.py`.

---

## 3. How fine-tuning works

Fine-tuning takes a pretrained model and continues training it on domain-specific labelled data. The model already understands grammar and context from its pretraining. Fine-tuning teaches it the financial vocabulary on top of that existing knowledge.

We use **BIO (Begin-Inside-Outside) tagging** — the standard scheme for NER:

- `B-NOTIONAL` → first token of a notional span
- `I-NOTIONAL` → continuation token of that span
- `O` → not an entity

For the sample chat, the labels look like:

```
Token:   200     mio    at   2Y    EVG   estr   +    45    bps
Label:   B-NOT  I-NOT   O    B-MAT I-MAT B-BID  I-BID I-BID I-BID
```

The model learns to predict these labels token by token. After fine-tuning, it recognises financial patterns directly instead of relying on regex.

---

## 4. What the training data looks like

Each training example is a chat message with a BIO label assigned to every token:

```python
# One training example
{
    "tokens": ["BANK", "ABC", "wants", "200", "mio", "at", "2Y", "EVG", "estr", "+", "45", "bps"],
    "ner_tags": [
        "B-COUNTERPARTY",   # BANK  ← start of counterparty
        "I-COUNTERPARTY",   # ABC   ← continuation
        "O",                # wants
        "B-NOTIONAL",       # 200   ← start of notional
        "I-NOTIONAL",       # mio   ← continuation
        "O",                # at
        "B-MATURITY",       # 2Y    ← start of maturity
        "I-MATURITY",       # EVG   ← continuation (evergreen flag)
        "B-BID",            # estr  ← start of bid spread
        "I-BID",            # +
        "I-BID",            # 45
        "I-BID",            # bps   ← end of bid span
    ]
}
```

A dataset of 500 such examples, all structured this way, is what gets passed to the `Trainer`. Each example is one chat message (or one turn of a multi-turn chat). The model sees thousands of these and learns which token patterns correspond to which financial entity.

---

## 5. Model selection

| Model | Why consider it |
|-------|----------------|
| `microsoft/deberta-v3-base` | Best NER accuracy at this size. Handles financial sub-word tokens well. **Recommended.** |
| `dslim/bert-base-NER` | Already NER fine-tuned — good starting point. Currently in use. |
| `Davlan/bert-base-multilingual-cased-ner-hrl` | Handles French + English mixed chats — important for Paris desks. |
| `microsoft/deberta-v3-small` | Faster inference, slightly lower accuracy — good for high-throughput deployments. |

**DeBERTa-v3-base** is the right choice for quality. For a multilingual desk, prefer the multilingual variant. FinBERT is pretrained for sentiment, not NER — less useful here than it looks.

---

## 6. Training data

Fine-tuning needs labelled examples. Two sources:

**Silver labels from the booking system** — every booked trade has the field values recorded (counterparty, ISIN, notional, tenor, etc.). We join those values back to the chat that preceded the booking via trade ID and auto-label the matching token spans. This gives thousands of examples without manual annotation work.

**Manual annotation** — a smaller set of chats labelled by hand for quality. Tools: Prodigy or Label Studio both support BIO token classification. Annotation guidelines must cover edge cases: where does UNDERLYING start and end, how to handle typos like "Quaterly", what to do with hedged quantities like "maybe 200 mio".

Target data volumes:

| Stage | Gold (manual) | Silver (bookings) |
|-------|-------------|-----------------|
| PoC | ~500 chats | ~2,000 |
| Production | ~10,000 | ~50,000 |

All annotation happens on-prem. Chat archives are C3/C4 — no data leaves the bank's network.

---

## 7. Fine-tuning with HuggingFace

```python
from transformers import (
    AutoTokenizer,
    AutoModelForTokenClassification,
    TrainingArguments,
    Trainer,
    DataCollatorForTokenClassification,
)

LABELS = [
    "O",
    "B-COUNTERPARTY", "I-COUNTERPARTY",
    "B-NOTIONAL",     "I-NOTIONAL",
    "B-ISIN",         "I-ISIN",
    "B-UNDERLYING",   "I-UNDERLYING",
    "B-MATURITY",     "I-MATURITY",
    "B-BID",          "I-BID",
    "B-OFFER",        "I-OFFER",
    "B-PAYMENT_FREQUENCY", "I-PAYMENT_FREQUENCY",
]
label2id = {l: i for i, l in enumerate(LABELS)}

model = AutoModelForTokenClassification.from_pretrained(
    "microsoft/deberta-v3-base",
    num_labels=len(LABELS),
    id2label={i: l for l, i in label2id.items()},
    label2id=label2id,
)
tokenizer = AutoTokenizer.from_pretrained("microsoft/deberta-v3-base")

training_args = TrainingArguments(
    output_dir="models/ador-ner",
    num_train_epochs=5,
    per_device_train_batch_size=16,
    learning_rate=3e-5,
    warmup_ratio=0.1,
    weight_decay=0.01,
    fp16=True,                          # mixed precision — 2× faster
    eval_strategy="epoch",
    save_strategy="epoch",
    load_best_model_at_end=True,
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=eval_dataset,
    data_collator=DataCollatorForTokenClassification(tokenizer),
    compute_metrics=compute_seqeval_metrics,
)
trainer.train()
```

### Critical detail — tokenisation alignment

Word-level BIO labels must be aligned onto sub-word tokens. The word `estr+45bps` may split into `["estr", "+", "45", "bps"]` — four sub-words, but one label. We assign the label to the first sub-word and use `-100` (ignored by the loss) for the rest:

```python
def tokenize_and_align_labels(examples, tokenizer, label2id):
    tokenized = tokenizer(
        examples["tokens"],
        truncation=True,
        is_split_into_words=True,
        max_length=256,
    )
    all_labels = []
    for i, word_labels in enumerate(examples["ner_tags"]):
        word_ids = tokenized.word_ids(batch_index=i)
        prev_word_id = None
        label_ids = []
        for word_id in word_ids:
            if word_id is None:
                label_ids.append(-100)
            elif word_id != prev_word_id:
                label_ids.append(label2id[word_labels[word_id]])
            else:
                label_ids.append(-100)   # continuation sub-word — ignored
            prev_word_id = word_id
        all_labels.append(label_ids)
    tokenized["labels"] = all_labels
    return tokenized
```

Misalignment here is the most common silent bug — the model trains without error but evaluates poorly.

### Fast experimentation with LoRA

For hyperparameter sweeps, LoRA reduces training cost ~10× at minimal quality loss:

```python
from peft import get_peft_model, LoraConfig, TaskType

model = get_peft_model(model, LoraConfig(
    task_type=TaskType.TOKEN_CLS,
    r=16,
    lora_alpha=32,
    lora_dropout=0.1,
    target_modules=["query_proj", "key_proj", "value_proj"],
))
# Only ~1.3% of parameters are trainable
```

Use LoRA to find the best config, then run a full fine-tune for the production model.

---

## 8. Evaluation

Primary metric: **entity-level F1** with `seqeval` — strict span matching. We report per entity, not just macro, because a model that scores 0.95 overall but 0.3 on ISIN is not acceptable.

```python
from seqeval.metrics import classification_report
print(classification_report(true_labels, pred_labels))
```

Approximate production targets:

| Entity | Target F1 |
|--------|-----------|
| ISIN | ~0.98 — format is regular, low tolerance for errors |
| PaymentFrequency | ~0.97 |
| Counterparty | ~0.95 |
| Maturity | ~0.93 |
| Notional | ~0.92 |
| Bid / Offer | ~0.90 |
| Underlying | ~0.88 — hardest, most surface form variation |

---

## 9. Deployment and fallback chain

The fine-tuned model slots into the existing `NerPipeline` protocol in `ner.py` — one line changes:

```python
from transformers import pipeline

pipe = pipeline(
    "ner",
    model="registry/ador-ner-deberta-v3-base-v1.2",
    aggregation_strategy="simple",   # auto-merges B/I tokens into spans
)
```

Runtime fallback chain if any tier fails:

```
Fine-tuned DeBERTa (domain model)
         ↓
dslim/bert-base-NER (general model)
         ↓
Domain regex stopgaps
```

Each downgrade writes to `ExtractionResult.warnings`. Silent degradation is never acceptable.

---

## 10. Summary

Fine-tune DeBERTa-v3-base on silver-labelled chats from the booking system plus manually annotated examples. The model learns the 8 financial entity types natively, replacing the regex stopgaps. The architectural seam is already in place — swapping in the fine-tuned model is a one-line change. The most important investment is data quality: 2,000 well-labelled chats outperform any model trained on 20,000 noisy examples.
