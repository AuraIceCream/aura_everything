# Study-pack answer quality: focused repair

## Observed failure

The stable 17-question run (`pack_20261011_qwen_remaining17_fixed_v3`)
retrieved all expected units, but delivered only 2 of its 7 answerable questions.
The other 10 questions were absent-topic controls, correctly refused; counting
all 15 refusals as failures would be misleading. Delivery decisions are not
independent correctness scores.

Saved drafts exposed four problems:

- Citation normalization consumed newlines and moved punctuation into the next bullet.
- A harmless introductory sentence was treated as an unsupported factual claim.
- Unconditional visual/OCR policy caused native-text answers to invent visual provenance.
- Revisions expanded the explanation instead of retaining its supported facts.

## Changes and safety boundaries

Claim splitting now preserves line boundaries and citation ownership. Only a
closed, non-factual introduction is exempt: arbitrary notes, conclusions and
sentences beginning with "Based on" remain subject to checking.

Generation receives visual/OCR/user-annotation instructions only for methods
present in the selected evidence. All uploaded material and previous drafts
remain untrusted data; source-only answering and inline citations are required.

Repairs carry a bounded list of supported cited statements from the preceding
draft. These are preservation hints, not a whitelist: the resulting answer
still passes through the normal verifier and optional critic. Unsupported
statements are not included in that preservation list.

A complete, cited native-text sentence can survive a neutral semantic score
as a **degraded transcription**, not as independently verified truth. Matching
does not discard negation, qualifiers, numbers or unit case, borrow uncited
sources, or promote OCR/VLM/user annotations. Explicit retraction wording
disables this fallback; confident semantic contradictions remain blocking.
The learned semantic thresholds are unchanged.

## Evaluation

The fresh full-bank run uses `pack_20261011_qwen_answer_quality_v4`, the same
30 frozen questions and source generation, exact `qwen3.5:4b`, hybrid retrieval,
reranking, two drafts and normal scoped verification/revision. The optional
external critic stays off, as in the comparison run. The low-memory runtime
uses CPU threads 1, reranker batch 2, generator batch 64 and cache-disabled
Ollama on port 11435. See [runtime recovery](ollama-runtime-recovery.md).

No earlier answers are copied into the fresh run. Gold answers remain offline;
only the question enters the answering pipeline. Unit-test results establish
regression coverage, not model accuracy. Review answer correctness and all
absent controls before claiming an accuracy improvement.

## Compound-question and repair follow-up (2026-10-12)

The unchanged v4 run completed 30 questions after resuming with memory telemetry:
16 of 20 answerable questions were accepted and all 10 absent-topic controls
were refused. These are delivery decisions, not independently reviewed accuracy.
No reranker batch reduction was needed for that completed run.

Four saved refusals exposed distinct paths: compound-query evidence was retrieved
but dropped by whole-question-only reranking; an otherwise correct calculation
used prose/LaTeX instead of the source-arithmetic checker's supported format;
and revision of an NLI-flagged extra summary invented a replacement count.

Study reranking now scores the existing explicit question variants and named
steps in a literal acronym chain. Every candidate remains eligible; the same
cached model, batch size, relevance floor and citation checks are retained.
No answer-key terms or generated hypotheses enter retrieval. The prompt exposes
the checker's literal `Derived: expression = result [n]` format, discourages
unrequested counts, and repairs ask to remove rejected statements or use exact
source wording rather than inventing alternatives. Contradictions still block.

The separate v5 development retest contains the four failures and the ten frozen
absent controls. It does not replace v4 or establish held-out accuracy, and no
earlier answers are copied into it. Live results must be checked before calling
the four refusal paths resolved. This is a text-pack evaluation, not figure
description or visual-answer evaluation.
