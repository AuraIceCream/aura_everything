# Evidence-backed answer accuracy

The goal is stronger factual answers and usable citations across local models,
without accessing benchmark answer keys during retrieval or answer selection.
The frozen 15 questions are diagnostic; the remaining 35 are for validation.

## Techniques and their fit

| Technique | Decision | Reason |
| --- | --- | --- |
| Hybrid lexical/dense retrieval and exact title matches | Retained; title channel enabled in robust mode | An exact topic such as “test cross” can be lost by semantic search or query relaxation. |
| Multi-query retrieval | Added, bounded to four explicit query variants | Splits named comparison/list subjects while preserving the original question. Does not ask the model to invent hypothetical answers. |
| Cross-encoder reranking | Retained | Robust mode reranks the full candidate pool before selection, rather than discarding everything outside the final top-k first. |
| MMR / coverage-aware evidence selection | Added | Greedy relevance, diversity and question-term coverage; rejects very low reranker scores, deduplicates text, limits passages per document, and enforces a character budget. A new explicitly asked subject can exceed the document cap. This is lexical MMR, not an embedding-based MMR implementation. |
| Verifier-guided candidate selection | Added | Two independent drafts by default in robust mode, plus the routed revision budget. Specific errors take priority over question coverage or citation rate; the best earlier draft survives a worse revision. |
| Targeted revision | Fixed | All trusted critic findings now reach revision instructions: unsupported claims, terminology errors, process errors and missing concepts. |
| Smaller prompts | Compact profile available and corrected | The model, critic, verifier and trace now receive the same selected evidence. Previously compact generation hid/truncated passages that the other stages still saw. Selection owns the evidence budget. |
| Sentence compression | Existing deep-level setting retained | The compression ablation did not justify enabling it everywhere. Compression now copies passages rather than mutating the uncompressed candidate pool. |
| Memory-first answer / concept union | Deferred | Combining two answers can combine two errors. Benchmark concept keys must never guide production merging. Candidate selection preserves useful earlier answers without an unchecked union. |
| HyDE | Deferred | Hypothetical passages from the 1B model could reinforce its own misconceptions. Explicit query expansion is cheaper and easier to audit. |
| RAFT | Separate training experiment | Requires training data, distractors, held-out validation and retraining; it is not an inference toggle. |
| Larger reranker / more models | Configurable, no forced download | The current machine has limited memory. A larger model is not a substitute for fixing lost feedback or evidence selection. |
| Internet retrieval | Later phase | The user asked to add it after local accuracy work. |

## Runtime controls

Existing runs use `standard` by default until the new mode has measured results.
Enable the new path with:

```powershell
python aura_bio_system/benchmarks/run_full_rag.py --model llama3.2:1b --dense --rerank --critic --accuracy-mode robust --draft-candidates 2 --ids-file aura_bio_system/benchmarks/diagnostic_15_20260929.txt --tag llama32_1b_robust15_20261003
```

To use the same mode through the GUI/API, set `AURA_ACCURACY_MODE=robust` and
`AURA_DRAFT_CANDIDATES=2` before starting the server. `AURA_PROMPT_PROFILE=compact`
is an independent prompt ablation; keep the profile identical between comparison
arms. Dense retrieval and reranking retain their existing `AURA_DENSE=1` and
`AURA_RERANK=1` switches. A configured critic runs when requested by the caller.

Every robust candidate stores its answer, verifier report, critic report,
ranking measurements, phase, and provenance. `selected_revision` identifies the
returned candidate, and `final_verification` describes that answer. Returning an
earlier draft must not display the last attempt's verification.

Candidate ranking is a heuristic, not a calibrated probability of correctness.
The verifier can miss errors, and citation overlap does not establish entailment.
If every candidate fails, the selected answer retains its failed decision.
Independent drafts increase latency and critic calls; the count is bounded to 1–5.

## Measurement

First run matched small probes with the same model, device, context, token budget,
critic and prompt profile. Then run the frozen diagnostic 15 and the held-out 35.
Report phrase-coverage scores, factual contradictions, claim citation rate,
verifier decisions, latency and infrastructure errors. Review examples where a
score increases while a biological error survives. Do not revise benchmark keys
after looking at candidate answers.

A fixed claim that “157 questions resolves a 2.7-point gain” is not justified
without the variance of paired differences and assumptions about power. Use
paired uncertainty estimates and publish the question bank and run settings.
Scores from old runs are historical comparisons, not matched controls.

Full-pipeline runs save settings plus SHA-256 fingerprints of runtime/retrieval
Python source, the benchmark runner, package manifests, and explicit question/ID
files. Resuming after an edit, or resuming old results without these fingerprints,
requires a new `--tag`. Validation happens before model loading. Model weights,
indexes, installed dependencies and environment settings are not fingerprinted:
keep them unchanged across paired runs. Never edit runtime code during a run.

### Current handoff

The queued runs were stopped at the user's request to handle terminal execution.
Both `robust_evidence15_20261003.jsonl` and
`robust_evidence15_v2_20261003.jsonl` are partial diagnostics, not completed
15-question results. The user subsequently ran the full suite: 233 tests passed
in 95.3 seconds, including the manifest guard's eight regression tests. The
calculation-handoff change below and its four tests have not yet been run.

Run the tests first. Then run matched standard/robust three-question probes with
dense retrieval, reranking and critic enabled. Inspect NLI/critic availability and
factual errors before committing to the diagnostic 15 and held-out 35 runs.

## Research basis

- [Self-RAG](https://arxiv.org/abs/2310.11511): retrieve and assess relevance/support during generation. This mode borrows the feedback principle; it does not claim to reproduce the trained Self-RAG method.
- [Corrective RAG](https://arxiv.org/abs/2401.15884): assess retrieval quality and focus on relevant evidence. Internet correction remains deferred here.
- [RAFT](https://arxiv.org/abs/2403.10131): trains models to use relevant passages amid distractors; a separate training direction.
- [BGE model card](https://huggingface.co/BAAI/bge-base-en-v1.5): query instructions are already applied in `HybridSearcher.encode` through `QUERY_PREFIX`.

Implementation tests and empirical run results are recorded separately. Passing
tests alone does not establish an accuracy increase.

The package now declares Pint, Biopython and periodictable because the enabled
unit, sequence and chemistry checks depend on them. Those packages were installed
in the project virtual environment. The global Python installation used for the
historical experiments needs the workspace-local platformdirs supplement at
`.cache/verification-deps`; experiment commands set `PYTHONPATH` accordingly.

## Matched three-question probe (2026-10-03)

The `llama32_1b_standard3_20261003_v2` and
`llama32_1b_robust3_20261003_v2` runs completed with zero infrastructure errors.
Both used compact prompts, seed 42, 768 output tokens, dense retrieval,
reranking and a trusted critic. NLI and the biochemistry checkers ran.

| Question | Standard score | Robust score |
| --- | ---: | ---: |
| Test cross (`bio-0097`) | 1.000 | 0.667 |
| Vessel structure (`bio-0288`) | 0.167 | 0.667 |
| Hardy-Weinberg calculation (`bio-0091`) | 0.100 | 0.100 |
| Mean | 0.4223 | 0.4780 |

These are concept/numeric scorer results, not measured factual accuracy. The
standard test-cross answer included all expected keywords but also false claims
that a test cross is not a standard biological term. Robust retrieval removed
the clinical-assay confusion, but accepted answers still contained errors and
had no inline citations. The selected numeric revision was truncated and wrong
despite the deterministic verifier having computed the correct 0.48.

Next change: robust generation now receives the existing Hardy-Weinberg solver's
question-derived values before every draft and revision. Computations are traced
separately from retrieved source citations. No benchmark answer keys are used.
Other numerical solvers are not promoted into generation yet: their premise and
unit handling needs auditing first. Standard mode is unchanged. Four regression
tests were added; this change awaits the user's test/benchmark execution.

### Calculation-handoff probe v3

The user ran all 237 tests successfully, then completed
`llama32_1b_robust3_20261003_v3`: scores 0.667, 0.667 and 1.000, mean 0.778,
zero infrastructure errors. NLI and a trusted critic ran on every candidate.
The numeric draft returned the correct 0.48, but also asserted q = 0.16 before
using q = 0.4. Both verifier and critic accepted it. This is not a clean factual
success; the anatomy answer also retains defects and all selected drafts lack
inline citations. Critic decisions varied between v2 and v3 despite identical
non-numeric drafts, so judge variability is another measurement limitation.

The Hardy-Weinberg checker now inspects explicitly named scalar values for q,
p, squared frequencies and 2pq. A correct final number cannot hide an incorrect
named intermediate value or a second conflicting result. Expression prefixes,
sum equations and explicitly rejected examples are excluded conservatively.
Six regression tests were added; this checker change has not yet been executed.
Because it affects the shared verifier, future matched standard/robust comparisons
must use this same checker version in both arms.

## Reliability fixes after the diagnostic 15 (2026-10-04)

The v4 standard/robust runs completed 15 questions each, with no top-level
infrastructure errors. Historical scores were 0.5956 and 0.6234; robust gained
on four questions, regressed on three and tied on eight. But 13 robust answers
had no inline citations, and nine of 35 critic records were untrusted. The
numeric answer concluded 24% despite containing 0.48 earlier, scoring 1.0.
Those historical scores must not be advertised as factual accuracy.

Implemented, awaiting user-run tests:

- Untrusted or failed critic reviews produce an explicit `degraded` decision
  rather than approval when deterministic checks are otherwise clean. The UI
  shows partial verification and a visible failure reason. Untrusted content
  still cannot inject revision instructions. At equal deterministic error
  counts, checked candidates outrank unchecked candidates. Degraded-only review
  failures do not consume more revision-generation calls.
- Named heterozygote/carrier conclusions are checked against computed 2pq.
  The benchmark numeric scorer prioritises the last explicitly marked
  conclusion and cannot be promoted by a different solver sub-quantity. This
  remains a rule-based scorer: unmarked prose, negations and complex multi-part
  conclusions still need human review. It does not evaluate every factual claim.
- Robust evidence answers require at least one inline citation connected to a
  claim labelled supported by the verifier and to its matching passage ID.
  A references list alone does not qualify; no citations are appended by code.
  This is a minimum grounding floor, not full citation coverage or a proof of
  truth. It inherits NLI/lexical support limitations. Recognised question-derived
  arithmetic is exempt from this source requirement and remains visibly traced
  as a calculation, so the model is not forced to invent a source for arithmetic.

`benchmarks/rescore_runs.py` regrades saved answers without any retrieval,
generation, or critic calls. It writes exclusive new copies and summaries,
preserves the original scores in metadata, and never modifies the originals.
Their runtime traces are historical and explicitly marked **not rerun**. Regrade
both comparison arms with the same scoring version before interpreting gains.
Do not compare corrected scores against uncorrected summaries.

These runtime changes have not yet been benchmarked. Run the unit suite first,
then cheaply rescore the saved v4 pair before choosing another inference run.

## Answer-production changes after v5 (2026-10-04)

The user-run reliability suite passed 260 tests. Rescoring v4 left standard at
0.5956 but reduced robust to 0.5701 after correcting one false numeric pass.
The v5 three-question probe scored 0.5113: two 0.667 answers and a 0.20 numeric
answer. The numerical verifier now detected the wrong 24% conclusion, but the
1B model still changed the solver's correct 48% into 24%. Detection improved;
answer accuracy did not. Seven of eight critic responses were structurally valid,
not necessarily factually correct.

New edits, not yet executed or benchmarked:

- Robust mode always repairs its selected previous draft, prioritising up to
  four concrete edits. Full feedback remains in the trace, along with the
  applied instructions and the candidate being revised. Standard mode keeps
  its opt-in revision-context behaviour.
- A narrowly validated Hardy-Weinberg calculation owns the complete worked
  answer, rather than appending a correct result to erroneous LLM reasoning.
  It requires stated equilibrium, one frequency premise, one explicit numeric
  request and independently consistent solver values. Ambiguous, qualitative,
  multi-part, invalid and unsupported cases fall back to generation. Socratic
  and teach-back modes do not get a rendered full solution.
- Generation, source verification and critique still run. Raw model drafts,
  tool-owned answer origin and calculated values remain in the trace; all
  verifier/critic findings remain visible. NLI or the critic can still flag a
  tool answer. No answer key is read, no citation is invented, and no failing
  review is silently converted into approval.
- Compact prompts put focused corrections before the prior draft and source
  context. Source passages and citation numbering are unchanged. Numeric
  revision feedback no longer demands source citations for question-derived
  arithmetic. This shortens instruction overhead, not the evidence itself.

Use a new benchmark tag after tests pass. Correcting one calculation is not
evidence of a general accuracy gain; keep the diagnostic sample frozen and
follow with a matched comparison before using the held-out questions.

## Final bounded retrieval/answer pass (2026-10-06)

The v6 three-question probe completed at 0.778 concept recall with no run
errors. Its calculation answer was correct, but two answers remained uncited;
eight structurally valid critic reviews did not guarantee factual accuracy.
The vessel revision copied source context and exhausted its output budget.
These are diagnostic observations, not a matched improvement estimate.

- Compact generation now requests short cited bullets, itemwise comparisons
  and ordered mechanisms, without repeating source context or old drafts.
  Socratic and teach-back instructions retain their non-revealing behaviour.
- Robust candidates with exhausted output budgets or substantial source dumps
  receive blocking delivery issues and concrete shortening/repair instructions.
  A source dump requires an internal-style heading plus a long verbatim prefix
  from an actual passage; ordinary definitions and explicitly requested quotes
  are not penalised. This conservative rule does not detect every context echo.
  Raw answers and generation metadata remain unchanged in traces.
- Candidate selection prioritises factual blocking errors, then delivery
  defects, before critic flag counts or lexical coverage. Formatting cannot
  clear numeric errors, and a truncated source dump cannot win merely because
  its critic flags are fewer. The quality trace exposes these separate counts.
- The critic receives query/answer-relevant verbatim sentences from anywhere
  in each selected passage, rather than blindly receiving its first 600
  characters. Numbering, sentence order and negation are retained; each excerpt
  stays within 600 characters and omissions/clipping are disclosed. This is
  lexical excerpt selection, not a new support classifier or a full-source review.
- Deep-query fusion now copies searcher-owned evidence before changing scores,
  preventing repeated requests from accumulating scores in cached objects.

The audit retained the existing BGE query prefix, hybrid dense/sparse retrieval,
bounded query expansion, full candidate-pool reranking and relevance-filtered
diversity selection. Corpus paths and indexes are unchanged. No answer keys,
automatic citations, new model training or new external search were introduced;
generation, verification, critique and bounded revision still run.

Regression checks cover delivery gates, quote exceptions, factual-error
precedence, excerpt relevance/order/budget, teaching-mode preservation and cache
isolation. The full system suite passed 293 tests in 170.031 seconds, including
19 final-quality tests, two isolation tests and 12 calculator/revision tests.
The separate corpus retrieval suite passed 18 tests. The full-system run used
cached Hugging Face models only (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`),
CPU execution and TensorFlow disabled; no pipeline stages or test cases were
removed. A read-only review caught a line-wrap/negation excerpt defect; its
regression reproduced the failure before the fix and then passed.

These edits have not yet had a new inference benchmark; do not claim an
accuracy gain from unit tests or from replaying historical answers. Use a fresh
run tag and the frozen diagnostic questions for the next matched comparison.

## Older-review reconciliation (2026-10-06)

Checked against the local working tree, not the older GitHub checkout:

| Recommendation | Current implementation and remaining work |
|---|---|
| Memory-first, additive second pass | Not implemented as two separate generations. The core prompt encourages additions, which is not the same algorithm. Consider only as an opt-in core experiment; never use memory expansion in pack-only mode or union against evaluation keys. |
| Verifier-guided best-of-N | Implemented in robust mode, configurable from 1 to 5 drafts. Recent runs use 2. More drafts cost more time and have not been shown to improve accuracy. |
| RAFT fine-tuning | Not implemented or trained. This remains a separate training/data-curation project, not a completed pipeline feature. No training or model download starts while the GPU is occupied. |
| Coverage/diversity evidence selection | Implemented: question-term coverage, MMR-style diversity, relevance floor, deduplication and a prompt budget. Both source/document caps still need a pack-specific exception. This does not use gold-answer concepts. |
| Small-model compact prompts | Implemented, including delivery checks and targeted repairs. A matched post-pass inference comparison is still outstanding. |
| HyDE or multi-query at all depths | Bounded explicit multi-query expansion is implemented in robust mode at all retrieval depths. HyDE is not implemented; the alternative is already present without an additional generated hypothesis. |
| BGE query instruction | Already present in the embedding module and applied by the hybrid searcher's encoder. No missing-prefix fix is needed. |
| RRF source/domain weight tuning | Not measured/tuned against a held-out retrieval set. Do not retune on the frozen answer benchmark or claim fixed weights are optimal. |
| Stronger reranker | Default remains bge-reranker-base. A configurable stronger model needs a controlled latency/quality comparison, not an unmeasured default replacement or automatic download. |
| Sentence compression at every depth | Currently deeper levels only. Extending it everywhere is an ablation, not a guaranteed improvement; it can remove needed context. |

For the next core accuracy experiment, compare optional memory-first enrichment,
draft count, compression depth and reranker/weight settings one change at a time,
keeping the existing standard mode and frozen evaluation split intact. Implement
experimental controls only with regression tests; choose defaults from measured
results. RAFT additionally needs an approved, leakage-checked training set and a
separate training run. Neither private study-pack support nor these proposed
experiments establishes model-independent accuracy or perfect evidence support.
