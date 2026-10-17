# Pipeline failure assessment — 2026-09-30

This is a diagnostic assessment of the current biology pipeline, not a new
benchmark claim. The 15-question slice is failure-enriched and must not be
reported as an unbiased estimate. No internet search was used.

## What the existing scores say

| Run | Model | Questions | Mean score | Interpretation |
| --- | --- | ---: | ---: | --- |
| Bare baseline | Llama 3.2 1B | 50 | 0.6917 | Existing frozen run |
| Complete pipeline | Llama 3.2 1B | 50 | 0.7904 | Existing run; log confirms critic enabled |
| Bare baseline | Llama 3.2 1B | diagnostic 15 | 0.5822 | Failure-enriched slice |
| Basic RAG | Llama 3.2 1B | diagnostic 15 | 0.6067 | Retrieval plus generation |
| Full RAG | Llama 3.2 1B | diagnostic 15 | 0.5945 | Previous full run, no critic |
| Bare baseline | Qwen-based `aura-bio:v0` | diagnostic 15 | 0.8478 | Existing rescored run |
| Full RAG | Qwen-based `aura-bio:v0` | diagnostic 15 | 0.8344 | Existing rescored run, no critic |

The 50-question Llama scores show a historical +0.0987 full-pipeline difference.
That is evidence the pipeline can help this model on this bank, but it is not a
matched controlled ablation of each stage. On the failure-enriched 15, the old
full configuration trails basic RAG by 0.0122. The Qwen-based model starts much
higher and its old full run trails its baseline by 0.0134 on these generic
questions.

## Stage-by-stage findings

| Stage | Evidence checked | Assessment |
| --- | --- | --- |
| Benchmark and routing | The frozen set covers 13 subdomains. For `bio-0288`, the learned router called “Describe the structure of an artery, vein, and capillary” `concept_explanation`; the task is more naturally a comparison. | Routing can select an unhelpful teaching format, though this alone does not explain the factual errors. |
| Retrieval | For `bio-0097`, the old hybrid results were cross-reactivity and blood-compatibility passages. Exact-topic title search instead found `Test cross` passages and recovered all three novel answer-key terms in the first evidence replay. | A real retrieval miss. The early broad phrase version also boosted generic titles, so title matching was tightened. |
| Reranking | With the tightened title channel, the cross-encoder ranked `Test cross / Introduction` first (0.945), followed by `Limitations` (0.918), `Applications in model organisms` (0.892), and `Test cross types` (0.876). | It promotes the definition, but still places example-heavy sections near the top. Those sections can distract a small generator. |
| Evidence selection | Standard selection takes the top reranked passages, allows up to four per source, and has a 14,000-character budget. The selected context can therefore contain several sections from the same long article. | Redundancy and irrelevant examples remain a plausible contributor. Evidence-term coverage is an upper bound, not proof the model used the source correctly. |
| Deep compression | The prior 15-question ablation produced 0.5922 with compression off versus 0.5945 in an earlier run; the device and sampling differed. A six-question matched CPU check was nearly tied. | No justified global change. Compression stays on by default. |
| Generation | Compact/direct-format probes raised some keyword scores, but `bio-0288` still contained false vessel claims and `bio-0403` said every species can regenerate. `bio-0195` improved from 0.4 to 0.6 and was mostly sound, but remained repetitive and uncited. | The 1B model does not consistently turn retrieved context into a concise, supported answer. A score rise alone is not enough to accept a prompt variant. |
| Verification and revision | The `bio-0288` critic-enabled trace recorded contradictions and missing citations, yet exhausted two revisions and returned an answer still marked `revise`. Its final provenance had 0 citations in one probe and 0.458 unsupported-assertion rate in another. | Checks detect some defects but do not reliably repair them; the caller still receives a failed final answer after the revision budget. The external critic is not a correctness guarantee. |
| Scoring | The current score is answer-key phrase coverage. For broad questions such as `bio-0403`, other biologically valid organism examples may miss the key's named examples. `bio-0288` requires phrases such as “thick muscular wall,” which can miss a semantically similar description. | The benchmark is useful for repeatability but needs human review of apparent misses before interpreting every lexical penalty as a factual error. Do not alter keys after seeing results. |

## Retrieval evidence measurement

On the initial exact-title replay of the frozen 15, the answer-key terms absent
from the question and present in final evidence increased from 25/46 to 28/46.
All three added terms came from `bio-0097`; the other 14 questions showed no
term losses. The phrase channel was subsequently tightened to return at most two
sections per exact title and to prioritize an introduction for definition
questions. **The 25/46 versus 28/46 total has not yet been rerun after that final
section-selection refinement.** Neither replay establishes an end-to-end
answer-accuracy gain.

The attempted 15-question generation run with the earlier broad phrase variant
exited after one row and therefore has no valid aggregate. That row scored 0.333
on `bio-0097`; it is retained as a diagnostic artifact, not counted as a
benchmark result.

## Verification status and next priority

The current retrieval-specific tests pass (18 tests); the focused prompt and
pipeline tests pass (13 and 22 tests). The full biology-system suite ran 204
tests and had two environment errors because `platformdirs` is missing from the
active Python installation; the remaining tests passed. No commit or push was
made.

The next accuracy work should focus on reducing redundant same-document
evidence and making failed verification outcomes actionable, then validate on
the untouched 35 questions. Preserve the 15-question slice for diagnosis and
report both answer-key scores and human-checked factuality/citation behavior.
