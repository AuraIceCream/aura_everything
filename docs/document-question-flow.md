# Studying a document: question-aware flow

The study path supports several question families, not just a figure-description
demo: definitions and facts, ordered procedures, comparisons, supported arithmetic,
source-backed explanations, excerpt summaries and practice questions. It remains
pack-only: the original corpus and general model memory are not substitutes for
missing document evidence.

## Using it

Upload material into a saved study pack and wait for its text index. Select that
pack on Ask. Examples:

- `Explain the procedure in Fig. 5`.
- `Compare Figs. 5a and 6(b) in lecture.pdf`.
- `Explain pages 2-4`.
- `Compare the two methods described in this document`.
- `Calculate the dilution using the stated inputs`.
- `Make practice questions from this PDF, with cited answers`.

For images, attach or paste one PNG/JPEG, type the question and click Ask. Upload
alone performs CPU extraction, not model inference. Ask explicitly starts the
visible visual-processing, indexing and answering stages. Cancellation or a failed
stage prevents a subsequent answer from silently using incomplete preparation.

`Enable local model thinking` is optional and off by default. It is request-scoped
for both vision and answering. Thinking uses larger bounded output/deadline
budgets; it does not change retrieval, evidence provenance or verification. It
can be much slower and can still exhaust its budget. Internal reasoning is not
treated as source evidence.

## Source selection

Figure/table identity comes from native caption anchors, not the model's guess
or an earlier prose mention of that number. Figure and table numbers are distinct.
Page/slide references, bounded ranges and numeric figure lists are supported;
panel-qualified requests select the parent figure for question-focused inspection.
When a number occurs in multiple documents, specify the filename. Missing and
ambiguous references produce visible errors; another numbered crop is never
substituted.

New PDF ingestion records caption geometry. Where geometry can associate drawings
with a caption, the automatic region keeps that figure's panels and caption
together. An identified page view or manual crop remains useful when automatic
selection cannot isolate the figure. Old packs are not silently re-ingested.
Caption lines on the same baseline are separated at column gutters; adjacent
body prose must not widen a caption's figure crop.

Figure questions retain the requested interpretation and caption, while ordinary
hybrid retrieval/reranking can find relevant native procedure text elsewhere in
the identified document. Explicit page constraints stay strict. Merged chunks
are trimmed to the selected source units so an adjoining page cannot leak into a
page-specific answer. Different derived revisions/crops/questions are never
merged into one chunk. Validated figure descriptions remain atomic within the
64 KiB JSON contract, keeping labels, connections and uncertainties together.
If a complete description cannot fit the answer's context budget it is omitted
with a trace warning, never cut mid-JSON; inspect fewer figures in that case.
Malformed or oversized archived descriptions still use bounded windows.

Broad summaries combine ranked evidence with spaced document coverage. They are
bounded excerpt summaries, not an exhaustive read of every page. The prompt and
trace disclose this limitation; larger materials should be studied section by
section. Ordinary topical questions continue through hybrid retrieval and the
configured cached reranker.

## Visual processing and grounding

The local Ask flow uses the explicitly configured production vision model
`qwen3.5:4b`, without downloads, hosted uploads or implicit model/provider swaps.
A question-focused structured call records up to 32 labels, 4 axes, 24 visible
connections, a 600-character summary and 8 uncertainties. Endpoints must name
declared labels; connections are visible arrows/lines, not invented biological
causality. One bounded same-provider structural repair is allowed; timeouts and
truncated output fail visibly rather than being silently duplicated.

The answer API independently checks that the selected, question-compatible
visual revisions exist in its ready index generation. The frontend also waits
for this readiness. Answering pins immutable revisions and reserves inference
against competing visual jobs. No caption-only answer is allowed merely because
a newer visual job has finished before indexing.
Visual-answer requests release their own model after each completion so a held
answer model cannot occupy the GPU needed by the next explicit vision request.
No unrelated process or model is unloaded, and GPU-busy checks are unchanged.

`native_text`, `ocr`, `vlm` and `user_annotation` remain distinct through units,
chunks, evidence, citations and verification. A visual interpretation cannot
verify itself. Pixel/OCR numbers remain unverified, even when arithmetic on those
inputs is correct. Relevant native text can provide independent support only
for the claims it actually establishes.

## Limits and validation

This is broad question handling, not a promise to answer every possible question
correctly. Complex math, illegible scans, dense/rotated tables, tiny labels and
ambiguous diagrams can require OCR, manual crops, user corrections or additional
material. Scanned-only packs still require an explicit OCR/vision pass to create
searchable evidence before ordinary pack answering. Non-numeric named sections
and equation references use topical retrieval, not a dedicated reference resolver.

CPU regression tests cover source selection, cross-page context, index readiness,
question/crop isolation, thinking, structured output, provenance and Ask-stage
failure/cancellation. Frontend tests/build check integration contracts. These do
not establish real-model answer accuracy; the frozen figure bank and independently
reviewed real-document answers remain the quality checks.

See [study-pack setup and privacy](study-packs.md) and
[answer-quality experiments](study-answer-quality.md).

## Verification on 2026-10-12

The final backend regression run passed all 669 tests (318.553 seconds).
Frontend verification passed 30 tests and the production TypeScript/Vite build;
the corpus retrieval regression passed 18 tests. Regression-first development
and independent review caught stale-index acceptance, wrong crop substitution,
mixed question/crop chunks and structured-description truncation.

A separate local production smoke used a fresh copy of R1.pdf, its native
Fig. 2 caption/crop, hybrid retrieval, the cached reranker, robust two-draft
answering and normal verification with `qwen3.5:4b`. External critique was off.
The initial run refused its answer; inspection exposed a missing reserved
caption, split figure JSON and an inappropriate arithmetic scaffold. These
were corrected without changing verifier thresholds. Fresh extraction also
separated adjacent PDF columns. The second visual pass completed in 86.3
seconds with one call, and the missing-Fig. 99 control rejected substitution.
GPU-busy deferrals retained that checkpoint without repeating vision inference.
The second answer still refused (229.7 seconds): it contained uncited factual
headings, strengthened qualifiers and unsupported citations. Its trace also
exposed bold numeric list markers being split into standalone claims. The marker
parser now preserves the actual heading for verification and leaves decimal
values intact; it does not exempt bold factual statements. Answer/repair prompts
now require individually cited prose, preserve qualifiers and cover up to twelve
rejected claims rather than letting early formatting mistakes consume the repair
budget. Regression tests cover these cases without changing support thresholds.
The final checkpointed answer test after those fixes also refused (202.1 seconds).
Correct figure/caption evidence was present, but drafts still introduced unsupported
pathway counts/causal wording and citation/Markdown patterns that the checker did
not handle well. The code-contract regression gate passes; the real-figure answer
quality gate does **not**. No positive accuracy claim is made from these trials.
Next quality work should address structured claim/citation delivery and audit
verifier false rejections on a diverse frozen sample, not relax support thresholds
or repeatedly tune this one figure. Previous outputs are retained separately in
the local smoke directory; no original study pack or corpus was rewritten.
This one-document smoke is not a benchmark or evidence of universal accuracy.
