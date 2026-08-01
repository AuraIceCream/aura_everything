# Handoff — AURA-Bio

For a fresh session picking this up. Written 2026-07-27; every fact below was
verified against the machine that day, not recalled.

Read [`SUMMARY.md`](SUMMARY.md) for the project map and
[`ROADMAP.md`](ROADMAP.md) for the full status. This document covers what a new
session needs that those two do not: what changed recently, what is ready to
run, and the traps.

---

## What this project is

A local-first biology tutor that answers from a verified 25 GiB corpus rather
than model memory, and can prove what it used. A question is routed (subject,
level, teaching style, depth), evidence is retrieved by hybrid search, an answer
is generated against that evidence, and the answer is then *checked* — claims
against sources, terminology, process order, arithmetic — before it reaches the
learner. Everything is traced.

Four packages: `aura_corpus` (acquisition), `corpus_pipeline` (preparation and
indexing), `aura_bio_system` (per-query runtime), `frontend` (React UI).

---

## Two things changed since the last session — check these first

### 1. The data moved from `D:` to `G:`

All of `aura_data` now lives at `G:\aura_data\`. Everything survived:

| Path | Size |
|---|---|
| `G:\aura_data\AURA-Bio-Processed\02_chunks` | 26 GB |
| `G:\aura_data\AURA-Embedded` | 15 GB |
| `G:\aura_data\AURA-Bio-Index` | 4.8 GB |
| `G:\aura_data\AURA-Training` | 95 MB |
| `G:\aura_llm\AURA-Bio-Corpus` | raw downloads |

**`retrieval.manifest.json` stores absolute paths**, so the move broke
retrieval. Already fixed and verified this session — but if you ever move data
again, rewrite it:

```powershell
python -m aura_bio_pipeline write-retrieval-manifest `
  --index-root G:\aura_data\AURA-Bio-Index `
  --dense-index G:\aura_data\AURA-Bio-Index\core-dense.faiss `
  --dense-map G:\aura_data\AURA-Bio-Index\core-dense-map.sqlite3 `
  --core-sparse G:\aura_data\AURA-Bio-Index\core-sparse.sqlite3
```

Still stale and **not** yet updated: `corpus_pipeline/config/pipeline.toml`
(`corpus_root`, `chunk_root`) and `corpus_pipeline/kaggle/aura_kaggle_embeddings.py`.
Those only matter if you re-run chunking or Kaggle embedding. Defaults inside
`benchmarks/*.py` also still say `D:` — pass `--index-root` explicitly.

**`G:` is now 99% full (3.5 GB free).** `D:` has 75 GB free. Anything large goes
on `D:`.

### 2. CUDA torch is installed and working

`torch 2.13.0+cu126`, `cuda_available: true`, GTX 1650 detected. Confirm with
`aura-bio device`.

Note for future installs: **`cu121` has no Python 3.13 wheels** — that is why
the documented command failed. Use `cu126` (driver 556.12 is too old for
`cu128`).

This unblocks GPU encoding and reranking. The LLM (`aura-bio:v0` via Ollama)
already ran on GPU regardless.

---

## Verified state, 2026-07-27

| Check | Result |
|---|---|
| `corpus_pipeline` tests | **45 pass** |
| `aura_bio_system` tests | **154 pass** |
| GPU | `cuda` selected, GTX 1650 |
| Retrieval | working — 3 hits, 7.5 s cold |
| Baseline benchmark | complete, in `benchmarks/results/` |

Run tests from *inside* the `tests/` directory (discovery fails otherwise), with
`USE_TF=0 AURA_GENERATOR=extractive AURA_CRITIC=off` so they never touch Ollama
or a paid API.

---

## The single most important number

Baseline (raw model, no pipeline, all 441 questions):

| Metric | Value |
|---|---:|
| Overall | 0.822 |
| **Hallucination rate** | **0.375** |
| Numeric accuracy | 0.800 |
| Process-order accuracy | 0.833 |

**55% of questions are already perfect at baseline.** The model is not short of
biology knowledge; its measured failure is behavioural — it invents confident
answers for entities that do not exist. That single fact should drive most
decisions: it is why fine-tuning should start with SFT and refusal examples
rather than more prose, and why the headline mean will compress differences
between systems (use `discriminative_mean` instead).

---

## Next action — ready to run

Everything is prepared. Nothing is blocked.

```powershell
python aura_bio_system\benchmarks\run_full_rag.py --system full_rag `
  --index-root G:\aura_data\AURA-Bio-Index --rerank
```

Resumable — re-run the same command after any interruption and it skips
finished questions. Expect 8–14 hours. Then `--system basic_rag` to isolate what
retrieval alone contributes.

Expected: overall 0.87–0.91, hallucination **0.375 → 0.00–0.13**, numeric and
process-order to 0.90+. High confidence on the deterministic metrics because
they do not depend on retrieval — SymPy and the order checker detect the error
and the revision loop fixes it. Reasoning in
[`benchmarks/PROJECTIONS.md`](aura_bio_system/benchmarks/PROJECTIONS.md).

After that: fine-tune (data is built, see below), then
`--system finetuned_rag --model <tag>` completes the four-way ablation.

---

## Fine-tuning data is built

`G:\aura_data\AURA-Training\` — 202,442 records, 293 MB text, 73M tokens.

| Kind | Count | What it is |
|---|---:|---|
| `prose` | 140,455 | filtered biology text |
| `template` | 61,139 | heading-derived QA — **format, not reasoning** |
| `pubmedqa` | 723 | expert-labelled, with evidence |
| `gold` | 125 | verified against answer key *and* corpus |

**Only ~850 records are real supervision.** A template question is mechanically
derived from the answer it is paired with, so it cannot supervise inference.
Every record carries `kind` — weight or drop templates; do not report them as
instruction data.

**Start with SFT and explicit refusal examples**, not continued pretraining. 1 GB
of prose is ~262M tokens ≈ 10–15 days on this GPU, to move a metric already at
0.822. Full argument in
[`benchmarks/FINETUNING_DATA.md`](aura_bio_system/benchmarks/FINETUNING_DATA.md).

**Known corpus limitation:** short of textbook prose (LibreTexts has only 6,515
chunks total; most NLM LitArch is clinical reviews and gets filtered). Mix lands
at 43% Wikipedia / 47% papers / 9% textbooks despite weighting toward textbooks.
That is an acquisition gap, not a filter setting.

---

## Traps — each of these cost real time

- **FAISS here cannot mmap IVF indexes.** Even a 5,000-vector index fails. The
  dense index must fit in RAM, hence IVF-PQ (~1 GiB), and `merge_ondisk` is
  unusable. Do not reintroduce `IO_FLAG_MMAP`.
- **RAM is the binding constraint, not disk.** ~4 GiB free is common. Loading
  the encoder plus a 1 GiB dense index plus a 3.5 GiB sparse index will thrash
  or be OOM-killed. Dense is opt-in via `AURA_DENSE=1`; sparse-only hybrid
  answers in 2–850 ms and is the default. First cold sparse query can take
  minutes while the OS pages in the FTS.
- **Qwen 3.5 needs `think: false`** or it spends the whole token budget
  reasoning and returns an empty message (`done_reason: length`).
- **GLM free tier rate-limits hard.** The client retries 429/5xx with backoff;
  a failed critique is marked untrusted and, by design, can never clear or block
  an answer on its own.
- **Retrieval quality ≠ training quality.** A UniProt record is good evidence
  and terrible training prose. Biographies of biologists and clinical systematic
  reviews pass a prose filter while teaching no biology.

---

## How to work on this codebase

The verifier and the data filters are the parts most likely to bite you, and
they share one failure mode. Seven verifier bugs and five data-filter bugs were
found this project; **every one was the same mistake — treating textual
proximity as a semantic claim**:

| Rule | Flagged | Reality |
|---|---|---|
| `overstated` | "…unit of **all** living organisms" | true statement |
| `misspelling` | `chlorophyll` | *contains* `chlorophyl` |
| `step_order` | first-mention order | topic named first, then situated |
| `wrong_location` | "lack mitochondria, so rely on glycolysis" | asserts the opposite |
| Hardy-Weinberg | number near "recessive" | it was **p**, stated explicitly |

Each looked correct against synthetic tests and failed on real generated prose.
Had they shipped, the full pipeline would have scored *worse and slower* than
the baseline — burning revision cycles correcting answers that were already
right, which reads as "the pipeline doesn't help".

Three practices follow, and they are worth keeping:

1. **Build regression tests from real model output**, never from a paraphrase of
   it. Twice a fix was declared good after testing a hand-written approximation
   of a failing case; both times the real answer still failed.
2. **Read the content, not the counts.** A manifest saying "63,508 templates
   kept" gave no hint that 89% were rare-disease counselling boilerplate. Every
   data-filter bug was caught by sampling actual generated questions.
3. **Prefer warning severity for rules that cannot be made precise.** A false
   error costs a wasted revision and a worse score; a missed warning costs only
   a review. `overstated` was downgraded for exactly this reason.

More generally: this session repeatedly reported work as finished before it was
— stale logs matched, a silently-dropped `--gold` input, paraphrase tests. The
work held up because things were re-checked. Verify against the artifact on
disk, not the exit code.

---

## Open items

| Item | Note |
|---|---|
| PubMed BM25 index | 26.4M chunks, ~56 GiB; only tutoring-core (1.14M) is built |
| Retrieval Recall@k | needs relevance labels; gold set chunk ids are a start |
| Routing benchmark | labelled set not built |
| Teaching evaluation | rubric not built |
| Failure-review UI | capture works; human approval flow missing |
| Gemini critic | implemented, needs a key; GLM is the working one |
| Stale `D:` paths | `pipeline.toml`, kaggle script, benchmark defaults |
