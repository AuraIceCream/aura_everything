# AURA-Bio runtime system

This is the per-query half of AURA-Bio. Corpus acquisition lives in
`aura_corpus`, corpus preparation and index building in `corpus_pipeline`
(`aura_bio_pipeline`). This package is everything that runs when a learner asks
a question.

```text
query
  -> QueryRouter          task, subdomain, learner level, teaching mode, depth
  -> HybridSearcher       dense BGE + core BM25 + PubMed BM25, fused with RRF
  -> CrossEncoderReranker query-passage scoring
  -> select_evidence      per-source cap and prompt budget
  -> Generator            the local biology LLM (injected)
  -> BiologyVerifier      claims, terminology, process order, SymPy, hedging
  -> Critic               optional external reviewer (injected)
  -> revision loop        bounded by the context level
  -> Trace                every stage, to SQLite and JSONL
```

## Installation

Local study packs now also accept PNG/JPEG and retain PDF page/figure previews.
OCR/vision passes are explicitly started, checkpointed and provenance-labelled;
model descriptions never verify themselves. See the [study-pack guide](../docs/study-packs.md)
for optional `[api,study,visual]` dependencies, local resource checks and hosted
permission. The original biology corpus is separate and unchanged.

From `G:\aura_llm`:

```powershell
python -m pip install -e .\corpus_pipeline
python -m pip install -e .\aura_bio_system
python -m pip install -e ".\aura_bio_system[api]"   # adds FastAPI + uvicorn
```

## API server

`aura_bio.api` is a FastAPI backend serving the `frontend/` React app against
this runtime. It degrades gracefully: no model means extractive answers, no
dense index means the instant BM25 channels.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/health` | index and model readiness |
| `GET /api/v1/capabilities` | models, teaching modes, retrieval modes |
| `GET /api/v1/corpus/status` | corpus and preparation coverage |
| `POST /api/v1/runs` | answer one question through the full pipeline |
| `GET /api/v1/runs` | recent runs with their trace summaries |
| `GET /api/v1/runs/{id}` | one run with its full trace |
| `GET /api/v1/runs/{id}/events` | SSE replay of the run |
| `POST /api/v1/retrieval/search` | retrieval only, no generation |
| `GET /api/v1/evaluation/summary` | benchmark composition |

`GET /api/v1/runs` is what the interface's recent-runs, teaching-quality and
failure-review panels read, so those panels show measured behaviour rather
than sample data. Runs are held in memory and reset when the server restarts.

An exception inside a request is converted to a normal HTTP error before it
leaves the handler. This matters more than it sounds: an unhandled exception
is returned by Starlette's outermost error middleware, which sits *outside*
the CORS middleware, so the browser sees a bare 500 with no
`Access-Control-Allow-Origin` header and reports it as a CORS failure. Running
out of memory returns 503 naming the component to switch off.

```powershell
aura-bio-api --index-root D:\aura_data\AURA-Bio-Index
```

Environment:
- `AURA_INDEX_ROOT` overrides the index location (or pass `--index-root`)
- `AURA_DENSE=1` enables the dense channel (needs several GiB free)
- `AURA_RERANK=1` enables the cross-encoder reranker
- The generator prefers Ollama `aura-bio:v0` (persona Qwen 3.5 4B) when
  reachable; `AURA_OLLAMA_MODEL=<name>` overrides it and
  `AURA_GENERATOR=extractive` forces the no-model path
- `AURA_ROUTER=rules` disables the trained router and uses the rules only
- `AURA_CRITIC=glm|gemini|off` selects the external critic (opt-in per request
  via `allow_external_critic`); keys are `ZAI_API_KEY` / `GEMINI_API_KEY`
- `AURA_TRACE_DB` relocates the trace store

The full end-to-end setup, including the frontend, is in the root
[`README.md`](../README.md).

## The learned router

`QueryRouter` combines hand-written rules with an optional trained classifier
over frozen sentence embeddings (SapBERT + BGE) and lexical features. Train it
with:

```powershell
python aura_bio_system\benchmarks\run_routing_eval.py --all --encoders sapbert,bge --ablate --jobs 1 --save
```

That writes `benchmarks/router_model/`, which the runtime loads automatically
when present. Questions in `benchmarks/subset_50.txt` are held out of training
so the end-to-end evaluation stays clean.

Two design points worth knowing before changing this:

**The classifier may only overrule a confident rule where it was measured
better.** Training records the rule router's score alongside the model's, and
`RouterModel.supersedes_rules` gates the override on that comparison. Without
it, a rule that is *confidently wrong* is unreachable and the trained model is
silently discarded, which looks identical from the outside to a model that does
not work.

**Selection is on `f1_macro`, not `balanced_accuracy`.** Balanced accuracy is
macro *recall* and carries no precision term, so over-predicting a rare class
costs nothing. Since learner level drives the prompt's register, that produced
systematic over-escalation and measurably shorter answers. The costs are
asymmetric, so the metric has to charge for false positives.

### Comparing external critics

```powershell
aura-bio compare-critics --markdown           # whichever provider keys are set
aura-bio compare-critics --critic glm --critic gemini --markdown
```

Scores GLM vs Gemini on 12 biology answers with planted errors — decision
accuracy, false-accept/false-revise rates, agreement with the deterministic
verifier, latency, and tokens — against the verifier-only baseline. Sends those
answers to the external providers, so it needs network and the relevant key.

## Benchmark and ablation

`aura_bio.evaluation` holds a 441-question biology benchmark with
machine-checkable answer keys (concept lists, SymPy-checked numbers, process
order, and hallucination-bait adversarials) and a four-system harness for the
SRS 25 ablation — baseline, basic RAG, full pipeline, finetuned+RAG. Export the
question set with:

```python
from pathlib import Path
from aura_bio.evaluation import all_questions, write_jsonl
write_jsonl(all_questions(), Path("benchmarks/biology_benchmark.jsonl"))
```

Run the ablation by wrapping each system as a `SystemRunner` (or `CallableRunner`)
and calling `run_benchmark`; `format_markdown_table` renders the SRS 25 table.

### Baseline and gold set

```powershell
# raw model, no pipeline (SRS 25 config 1). Resumable; GPU via Ollama.
python aura_bio_system\benchmarks\run_baseline.py

# second, independent check: verify answers against the real corpus
python aura_bio_system\benchmarks\build_gold_set.py --min-grounded 0.25
```

`run_baseline.py` scores answers against the hand-authored answer keys only —
it never consults the corpus, which is correct for a no-retrieval baseline.
`build_gold_set.py` adds the corpus check: it retrieves real evidence for each
perfect-scoring answer and keeps only those the verifier also grounds, writing
`gold/gold_answers.jsonl` with the supporting chunk ids. Answers that fail land
in `gold/rejected_ungrounded.jsonl` with the reason, so the rejects are
reviewable rather than silently dropped.

See [`benchmarks/PROJECTIONS.md`](benchmarks/PROJECTIONS.md) for the measured
baseline, where its lost points actually are, and what full RAG and
finetuned+RAG should be expected to move.
[`benchmarks/FINDINGS.md`](benchmarks/FINDINGS.md) records what measuring the
pipeline actually showed, including the results that did not go the expected
way.

### Running the pipeline over the benchmark

```powershell
python aura_bio_system\benchmarks\run_full_rag.py --system full_rag --dense --rerank --critic --limit 6 --tag smoke
```

`--system` selects `basic_rag`, `full_rag`, or `finetuned_rag`; `--rules-router`
forces the rules-only router for ablation parity; `--ids` and `--ids-file`
target specific questions. Runs are resumable and append as they go. A row that
errored is *not* treated as done, so a transient failure is retried on the next
pass rather than baked in as a zero.

### Diagnostics

```powershell
# Did every stage actually fire, or did something load and stay silent?
python aura_bio_system\benchmarks\check_liveness.py benchmarks\results\<run>.jsonl

# Which concepts does the pipeline lose that the bare model already had?
python aura_bio_system\benchmarks\analyse_dropped.py benchmarks\results\baseline.jsonl benchmarks\results\full_rag.jsonl

# Compare two runs under one scorer, with a confidence interval.
python aura_bio_system\benchmarks\compare_runs.py benchmarks\results\a.jsonl benchmarks\results\b.jsonl
```

`check_liveness.py` exists because a trained component was once loaded, reported
healthy, and never consulted; neither the unit tests nor the accuracy number
could see it. `compare_runs.py` prints an interval rather than a bare mean
because differences between these systems are usually not resolvable at fifty
questions, and a bare mean invites reading noise as a result.

## Design commitments

**Deterministic checks gate the loop.** SRS 31 Risk 4 warns that an LLM judge
will approve wrong answers. So the verifier is lexical and reproducible, and the
external critic can only ever make the decision stricter: a critic saying
`accept` cannot clear an error the verifier raised, and a critic returning
malformed JSON is marked untrusted rather than treated as approval.

**Nothing model-shaped is imported to run the rules.** Routing and verification
work with no model present, which keeps them testable and keeps the ablation
honest. Generation, critique, reranking, and the search backend are injected as
protocols.

**Every component can be switched off.** SRS 25 compares eleven configurations
against the full system, so each checker and each stage is independently
disableable rather than wired in.

**Silence never means "correct".** A numerical solver that does not recognise a
question returns nothing. A claim with no retrieved evidence is `unverifiable`,
not `unsupported`. A draft that gives a method without a figure is `unstated`,
not `incorrect`.

## Usage

```python
from pathlib import Path

from aura_bio.pipeline import AuraBioPipeline
from aura_bio.retrieval import CrossEncoderReranker
from aura_bio.tracing import TraceStore
from aura_bio_pipeline.retrieval import HybridSearcher

searcher = HybridSearcher(Path(r"D:\aura_data\AURA-Bio-Index"))
pipeline = AuraBioPipeline(
    generator=my_local_llm,
    searcher=searcher,
    reranker=CrossEncoderReranker(),
    store=TraceStore(Path("traces.sqlite3"), Path("traces.jsonl")),
)

answer = pipeline.answer("Explain how DNA replication occurs for a Class 12 student.")
print(answer.text, answer.decision, answer.confidence)
print(answer.sources)
```

`Generator` needs one method:

```python
def generate(self, route, evidence, instructions,
             coverage_pool=(), unknown_entities=()) -> str: ...
```

`instructions` is empty on the first draft and carries specific, deduplicated
repair instructions on any revision pass.

`coverage_pool` is the full candidate list from before reranking. Only
`evidence` is quoted and cited; the pool exists so the prompt's vocabulary
checklist can draw on passages that reranking dropped.

`unknown_entities` names anything the question calls by a name that no corpus
naming authority lists — Gene Ontology, MeSH, Reactome or the encyclopaedia
index. It is a search result, not a verdict, and the prompt says so.

Both are optional; a generator may ignore them.

## Routing

| Router | Labels | Fallback when unsure |
|---|---|---|
| Task type | 13 | `concept_explanation` |
| Subdomain | 18 | `general_biology`, or `interdisciplinary` on a tie |
| Learner level | 8 | inferred from vocabulary, else `high_school` |
| Teaching mode | 9 | derived from task type |
| Context level | 0–4 | derived from task type, escalated by query depth |

Explicit user choices always win and are recorded in `explicit_overrides`.
Every decision carries the patterns that produced it, so a routing benchmark can
attribute a wrong answer to a specific rule rather than to "the router".

## Verification

| Checker | Catches | Worst severity |
|---|---|---|
| Claim support | claims the evidence does not cover | — (labels only) |
| Terminology | misspellings, invalid binomials, confusable pairs | error |
| Abbreviations | unexpanded `ATP`/`DNA` at school levels | warning |
| Process order | steps stated out of canonical order | error |
| Process location | glycolysis "in the mitochondria" | error |
| Numerical | arithmetic that disagrees with SymPy | error |
| Uncertainty | unsupported absolutes stated as fact | error |
| Citations | citations pointing at absent evidence | error |

Decisions are `accept`, `revise`, or `insufficient_evidence`.

## Tests

```powershell
python -m unittest discover -s .\aura_bio_system\tests -v
```

The suite runs without a GPU, without a model download, and without the built
indexes.
