# AURA-Bio — project map

A local-first biology tutor that answers from a verified corpus rather than from
model memory, and can prove what it used. Full specification in
[`srs.md`](srs.md); this file is the orientation document.

---

## The idea in one paragraph

A small local model is surrounded by a pipeline: the question is routed
(subject, level, teaching style, depth), evidence is retrieved from a 25 GiB
biology corpus by hybrid search, an answer is generated against that evidence,
and the answer is then *checked* — claims against sources, terminology, process
order, arithmetic — before it reaches the learner. Everything is traced, so any
answer can be explained after the fact.

---

## Repository layout

```
aura_llm/
├── srs.md                    full specification (37 sections)
├── SUMMARY.md                this file
├── README.md                 acquisition-pipeline guide
│
├── aura_corpus/              [1] ACQUISITION   → CLI: aura-corpus
├── corpus_pipeline/          [2] PREPARATION   → CLI: aura-process
├── aura_bio_system/          [3] RUNTIME       → CLI: aura-bio, aura-bio-api
└── frontend/                 [4] INTERFACE     → Vite + React 19
```

Four stages, each usable on its own.

### [1] `aura_corpus/` — acquisition
Downloads from official sources only (PubMed, PMC, Wikipedia, NLM LitArch,
UniProt, GO, MeSH, Reactome), with checksums, licence records, resumable
transfers, and quarantine for anything that fails validation. No dependencies.

| File | Role |
|---|---|
| `download.py`, `net.py` | resumable fetching |
| `validation.py` | checksums, archive integrity |
| `registry.py`, `store.py` | manifests in SQLite |
| `curation.py` | optional LLM licence review |

### [2] `corpus_pipeline/` — preparation and indexing
Turns raw downloads into searchable indexes. Reads `G:\aura_llm\AURA-Bio-Corpus`,
never modifies it.

| File | Role |
|---|---|
| `parsers.py` | PDF, JATS/NLM XML, MediaWiki, OBO, UniProt DAT, CSV |
| `cleaning.py`, `dedup.py` | boilerplate removal, exact/paragraph dedup |
| `chunking.py` | 450-token passages (BGE's limit is 512) |
| `embedding.py` | BGE Base v1.5 vectors |
| **`retrieval.py`** | **BM25/FTS5 + FAISS index building, `HybridSearcher`** |
| `training_data.py` | quality-filtered corpus for fine-tuning |
| `qa_data.py` | question-answer records from PubMedQA, gold set, templates |
| `kaggle/` | GPU embedding jobs run on Kaggle |

### [3] `aura_bio_system/` — the runtime (per query)
Everything that happens when a question is asked.

| Package | Role |
|---|---|
| `routing/` | task, subdomain, learner level, teaching mode, depth 0–4 |
| `retrieval/` | reranking, evidence selection, hierarchical/deep strategies, metrics |
| `verification/` | claims, terminology, process order, SymPy numerics, uncertainty |
| `critique/` | GLM/Gemini critic clients, comparison harness |
| `generation/` | prompt construction per teaching mode and level |
| `evaluation/` | 441-question benchmark, scorer, ablation harness |
| `pipeline.py` | the orchestrator |
| `tracing.py` | trace and failure logging (SQLite + JSONL) |
| `api/` | FastAPI backend serving the frontend |
| `benchmarks/` | runners, results, gold set, and analysis documents |

### [4] `frontend/` — the interface
Vite + React 19 + TanStack Query + Tailwind. Six routes: Ask, Retrieval lab,
Evaluation, Traces, Corpus, Settings. Runs on mock data standalone, or against
the live API with `VITE_USE_MOCKS=false`.

---

## Data on disk (not in the repo)

| Path | What | Size |
|---|---|---|
| `G:\aura_llm\AURA-Bio-Corpus` | raw verified downloads | — |
| `G:\aura_data\AURA-Bio-Processed\02_chunks` | retrieval chunks, 9 sources | 25.0 GiB |
| `G:\aura_data\AURA-Embedded\` | 11 Kaggle embedding jobs | 14.9 GiB |
| `G:\aura_data\AURA-Bio-Index\` | FAISS + BM25 indexes | 4.6 GiB |
| `G:\aura_data\AURA-Training\` | fine-tuning corpus | ~300 MB |

---

## Where things stand

**Working end to end.** Corpus acquired and verified (3,659/3,659 files);
10.4M BGE vectors; hybrid retrieval; the full routing → retrieval →
verification → critique → revision pipeline; a FastAPI backend; a React
frontend; a 441-question benchmark with a measured baseline.

| Component | State |
|---|---|
| Corpus, chunking, embedding | complete |
| Dense (IVF-PQ) + BM25 indexes | complete |
| Routing, verification, critique | complete, calibrated on real output |
| Local model (`aura-bio:v0`, Qwen 3.5 4B) | wired, runs on GPU |
| GLM critic | working — 0.917 accuracy, 0.000 false-accepts |
| Baseline benchmark | measured — **0.822 overall, 0.375 hallucination** |
| Gold set | 125 corpus-verified answers |
| Full-RAG benchmark | ready to run, not yet run |
| Fine-tuning | not started |

**Two known constraints on this machine.** `torch` is a CPU-only build, so the
encoder and reranker cannot use the GPU until a CUDA wheel is installed (the
LLM already runs 100% on GPU via Ollama). And FAISS here cannot memory-map IVF
indexes, so the dense index is IVF-PQ (~1 GiB) and loaded into RAM; dense
retrieval is opt-in via `AURA_DENSE=1`.

---

## Running it

```powershell
python -m pip install -e .\corpus_pipeline
python -m pip install -e ".\aura_bio_system[api]"

aura-bio device                                    # what hardware will be used
aura-bio route "Explain mitosis for class 10" --summary
aura-bio-api --index-root G:\aura_data\AURA-Bio-Index
cd frontend; npm install; npm run dev
```

Tests — no GPU, model, or index required:

```powershell
cd corpus_pipeline\tests; python -m unittest discover -s .    # 39
cd aura_bio_system\tests; python -m unittest discover -s .    # 154
```

---

## Further reading

| Document | Contents |
|---|---|
| [`srs.md`](srs.md) | full specification, phase status, design decisions |
| [`ROADMAP.md`](ROADMAP.md) | what is done, what is next, in order |
| [`benchmarks/PROJECTIONS.md`](aura_bio_system/benchmarks/PROJECTIONS.md) | expected benchmark movement, with reasoning |
| [`benchmarks/FINETUNING_DATA.md`](aura_bio_system/benchmarks/FINETUNING_DATA.md) | how much training data, and why |
| [`aura_bio_system/README.md`](aura_bio_system/README.md) | runtime design and API |
| [`corpus_pipeline/README.md`](corpus_pipeline/README.md) | preparation and indexing |
