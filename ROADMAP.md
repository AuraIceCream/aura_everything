# AURA-Bio — status and next steps

> Historical status snapshot (2026-07-27). Its benchmark projections and
> 0.375 hallucination figure were superseded by the measured analysis in
> [`FINDINGS.md`](aura_bio_system/benchmarks/FINDINGS.md). See the
> [evaluation and expansion plan](docs/EVALUATION_AND_EXPANSION.md) for the
> proposed matched, two-model study.

Companion to [`SUMMARY.md`](SUMMARY.md). Phase numbers refer to
[`srs.md`](srs.md) §29.

---

## Done

### Corpus (Phases 1–4)
Acquired from official sources and verified: **3,659 of 3,659 files `ok`**,
zero failures. Cleaned, deduplicated, and chunked to **25.0 GiB across nine
sources**. Chunks target 450 BGE tokens (the model truncates above 512, so the
SRS's generic 500–900 range would have silently discarded text).

### Retrieval (Phases 6–8)
- **Dense**: 10,394,250 BGE vectors → FAISS `IVF,PQ96` index, 1.02 GiB, 7–137 ms
  queries. PQ rather than SQ8 because this FAISS build cannot memory-map IVF
  indexes, so the index must fit in RAM.
- **Sparse**: BM25/FTS5 over 1.14M tutoring-core chunks, 3.3 GiB. `detail=none`
  was measured rank-identical to `detail=full` at 23% less disk.
- **Hybrid**: Reciprocal Rank Fusion across dense, core-BM25, and a separately
  weighted PubMed-BM25 channel.
- **Reranking**: BGE cross-encoder with per-source caps.
- **Deep levels**: hierarchical document expansion (L3) and query decomposition
  with evidence compression (L4).

### Runtime (Phases 9–16)
Routing (13 task types, 18 subdomains, 8 levels, 9 teaching modes, depth 0–4),
verification, critique, revision, tracing, FastAPI backend, React frontend.

### Model and critic
- `aura-bio:v0` (persona Qwen 3.5 4B) wired through Ollama, **100% on GPU**.
  Thinking is disabled — Qwen 3.5 otherwise spends the whole token budget
  reasoning and returns an empty answer.
- **GLM `glm-4.7-flash`** critic: 0.917 decision accuracy, **0.000
  false-accepts**, versus 0.750 for the deterministic verifier alone. Retries
  429/5xx with backoff. Gemini implemented but deprioritised.

### Benchmark (Phase 18)
441 questions, all 18 subdomains, with machine-checkable keys — 10 SymPy-checked
numerics, 12 process-order items, 8 adversarial items naming non-existent
entities.

**Baseline measured** (raw model, no pipeline, 441/441, zero errors):

| Metric | Value |
|---|---:|
| Overall | 0.822 |
| Concept recall | 0.827 |
| Numeric accuracy | 0.800 |
| Process-order accuracy | 0.833 |
| **Hallucination rate** | **0.375** |
| Median latency | 29.3 s |

### Gold set
**125 answers** that passed both the answer key *and* corpus verification, each
carrying its supporting chunk ids. All 18 subdomains.

### Verifier calibration — the most consequential work
Running the verifier over 243 real answers exposed **seven false-positive
rules**, every one an instance of the same mistake: *treating textual proximity
as a semantic claim*.

| Rule | Flagged | Reality |
|---|---|---|
| `overstated` | "…unit of **all** living organisms" | true statement |
| `overstated` | `unverifiable` treated as overreach | absence of evidence |
| `misspelling` | `chlorophyll` | **contains** `chlorophyl` |
| `step_order` ×3 | topic-first; bullet lists; "**anaphase**-promoting complex" | not sequence claims |
| `wrong_location` | "lack mitochondria, so rely on glycolysis" | asserts the opposite |
| Hardy-Weinberg | number near "recessive" | it was **p**, stated explicitly |

Blocking rejections fell **47 → 1**, and the survivor is genuine. Had these
shipped, the full pipeline would have scored *worse and slower* than the
baseline, burning revision cycles correcting answers that were already right —
which reads as "the pipeline doesn't help".

Each rule is now pinned by a regression test built from **real model output**.
A checker tuned only on synthetic examples fires on real prose.

---

## Next, in order

### 1. CUDA torch — DONE (2026-07-27)
`torch 2.13.0+cu126`, `cuda_available: true`, GTX 1650 detected. Note that
`cu121` has **no Python 3.13 wheels**, which is why the originally documented
command failed; `cu126` is correct for driver 556.12.

### 2. Run the full-RAG benchmark — ready, nothing blocking
```powershell
python aura_bio_system\benchmarks\run_full_rag.py --system full_rag `
  --index-root G:\aura_data\AURA-Bio-Index --rerank
```
The data now lives on `G:`, not `D:` — see [`HANDOFF.md`](HANDOFF.md).
Resumable. Expect 8–14 hours. Then `--system basic_rag` to isolate what
retrieval alone contributes.

**Expected** ([`PROJECTIONS.md`](aura_bio_system/benchmarks/PROJECTIONS.md)):
overall 0.87–0.91, hallucination **0.375 → 0.00–0.13**, numeric and
process-order to 0.90+. High confidence on the deterministic metrics, medium on
overall.

Read the **`discriminative_mean`** in the summary, not only the headline: 55% of
questions are already perfect at baseline, which compresses differences.

### 3. Fine-tune
Data is built: `G:\aura_data\AURA-Training\`, ~300 MB, 30% question-answer.
Provenance is recorded per record — `gold` (125, verified), `pubmedqa` (~723,
expert-labelled), `template` (structural, teaches format not reasoning).

Start with **SFT**, not continued pretraining, and include **explicit refusal
examples** — hallucination at 0.375 is the largest measurable gap, and no
amount of extra biology prose teaches a model to say "that enzyme does not
exist". Reasoning in
[`FINETUNING_DATA.md`](aura_bio_system/benchmarks/FINETUNING_DATA.md).

### 4. Re-run the benchmark on the adapter
`run_full_rag.py --system finetuned_rag --model <adapter-tag>` completes the
four-way SRS §25 ablation.

---

## Open items

| Item | Note |
|---|---|
| PubMed BM25 index | 26.4M chunks, ~56 GiB; only tutoring-core is built |
| Retrieval Recall@k | needs relevance labels; the gold set's chunk ids are a start |
| Routing benchmark | labelled routing set not yet built |
| Teaching evaluation | rubric and set not yet built |
| Failure-review UI | capture works; human approval flow is not built |
| Gemini critic | implemented, needs a key |
| User study | Phase 22, optional |

---

## Things worth not re-learning

- **FAISS here cannot mmap IVF indexes** — even a 5,000-vector index fails. The
  dense index must fit in RAM; hence IVF-PQ, and `merge_ondisk` is unusable.
- **RAM is the binding constraint**, not disk. ~4 GiB free is common; loading
  the encoder plus a 1 GiB dense index plus a 3.5 GiB sparse index will thrash
  or be OOM-killed. Sparse-only hybrid answers in 2–850 ms and is the default.
- **Qwen 3.5 needs `think: false`** or it returns nothing.
- **Retrieval quality ≠ training quality.** A UniProt record is good evidence
  and terrible training prose. Biographies of biologists and clinical
  systematic reviews pass a prose filter while teaching no biology — a
  topical-relevance check rejects ~19,000 such chunks per 20 MB kept.
- **Verify fixes against real data, not paraphrases.** Twice a fix was declared
  good after testing a hand-written approximation of a failing case; both times
  the real answer still failed.
