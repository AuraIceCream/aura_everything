# Visual study packs — design

Status: implementation approved by the user's “Yeah Do it” and executed locally
on 2026-10-07. See the implementation plan and `docs/study-packs.md` for actual
verification. Approval did not authorise model downloads, GPU inference or
private hosted uploads; no live VLM/Groq quality evaluation was run.

## Intent and scope

Help a student study their own documents, including biology pathways, graphs,
gels, micrographs, structures and image tables. Keep the original image available
and distinguish its native text, OCR transcription, model interpretation and user
annotation. Extend the existing isolated study-pack flow; do not replace retrieval
or modify the original biology corpus, its indexes or its question banks.

This release includes image intake, PDF page/region rendering, manual crops,
checkpointed OCR, explicit figure-description jobs, optional hosted descriptions,
provenance-aware retrieval/answering, source UI, editable annotations and a frozen
figure evaluation. It is an architectural addition, not an OCR-only release.

Ask-with-image is a subsequent, separately scoped milestone. Visual embeddings,
Mermaid/chart generation, legacy PPT conversion, full PowerPoint rendering,
handwriting/math recognition guarantees and clinical interpretation are excluded.

## Non-negotiable requirements

1. A provenance field (`native_text | ocr | vlm | user_annotation`) is carried
   through units, chunks, evidence, citations and the verifier. A VLM passage must
   never count as verification of itself.
2. Figure selection includes rendered page regions and manual crops, not only
   embedded images. Text-heavy pages cannot be excluded merely for having text.
3. One structured call per figure is the normal path, with schema validation and
   bounded repair. JSON validity is not factual correctness.
4. Explicit visual-job start, per-figure checkpoints, visible failures and no
   silent provider or model switching.
5. Per-page OCR timeouts replace the 180-second document deadline for the PDF/OCR
   path. OCR-derived numbers remain unverified.
6. Freeze a figure evaluation bank with hallucinated-label and unsupported-question
   controls before tuning prompts; never pass answer keys to serving code.

## Global constraints

- Windows-native, local-first; preserve the existing dirty checkout and unrelated edits.
- No commits or pushes. Planning and unit tests do not authorise GPU inference, model downloads or external uploads.
- Keep all private originals, renders, crops, OCR, descriptions, annotations, checkpoints and evaluation outputs inside their pack.
- Retain original bytes and checksums; never overwrite originals or execute document/image instructions, macros or model-generated code.
- Keep existing upload limit 50 MiB, Office expansion limit 200 MiB, page/slide limit 2,000 and extracted-text limit 10 million characters.
- Image decode limit: 25 million pixels; accept single-frame PNG/JPEG only, check signatures, apply EXIF orientation and strip metadata from derived preview/upload images.
- PDF rendering ceiling: 200 DPI and 12 million pixels per page; process one page at a time. Visual-asset budget: 512 MiB per document, with visible partial coverage when exhausted.
- OCR timeout: 60 seconds per page/image, configurable 5–300 seconds. Page rendering/native PDF extraction timeout: 60 seconds per page. No 180-second outer deadline may kill this multi-page path.
- Keep the existing 180-second parser deadline for non-PDF Office/text parsing; subsequent OCR of embedded images uses its own per-image deadline.
- VLM defaults: one image/request, longest-edge resize preserving aspect ratio within 1 million pixels, `num_ctx=4096`, `num_predict=1024`, temperature 0 and thinking disabled where supported. These are starting resource limits, not quality guarantees.
- VLM timeout: 120 seconds per figure, configurable 30–600 seconds; at most one model-assisted structural repair, two provider attempts total per figure.
- One visual inference worker; at most 20 selected figures per default job, configurable 1–200. Show exclusions and allow another explicit job for the remainder.
- Native ingestion and cached CPU hybrid indexing/reranking retain their existing automatic behaviour. VLM work is never an automatic side effect of upload, search or asking.
- External processing requires per-pack permission and an explicit job preview/start. API keys come from environment variables and never enter pack records or logs.

## Existing foundation and implementation boundaries

Reuse `study/schema.py`, `storage.py`, `jobs.py`, `chunking.py`, `indexing.py`,
`searcher.py`, `prompts.py`, `verification.py`, the study API and the source UI.
The existing source-preserving text/hybrid pipeline already works. Its current
chunks/evidence do not retain extraction-method metadata, so adding descriptions
without the provenance changes below is unsafe.

Use focused visual modules under `study/visual/`; keep providers behind one small
interface. Do not introduce a service, message broker or new vector store. Existing
core-corpus API shapes remain unchanged; new fields apply to study-pack objects.

## Data and provenance

`SourceMethod` has exactly the four required values. Append `provenance` and
`provenance_details` to study units/chunks/evidence. Details include source unit,
asset/figure ID, revision ID, content checksum, source locator and method-specific
engine/provider/model/prompt/config metadata. Preserve per-span provenance where
one chunk contains several source units. Chunk grouping separates methods and
roles: never blend native passages with interpretations or annotations.

Existing schema-1 native parser units may migrate as `native_text`, because this
release never produced OCR/VLM units. Unexpected derived roles or invalid methods
fail closed; do not silently treat them as native. Version the index manifest and
let old native-only generations remain readable with explicit rebuild guidance.

Figure records contain immutable `figure_id`, parent unit/document, source asset,
original content hash, kind of selection, locator, bbox, coordinate space and
render transform. Each page/slide occurrence is retained even when its pixels are
deduplicated. Cache reuse includes crop, OCR, nearby context, provider/model digest,
prompt and config hashes, not just the image hash.

Bboxes use `(x0,y0,x1,y1)`, top-left origin, normalised to the upright preview,
with `0 <= x0 < x1 <= 1` and `0 <= y0 < y1 <= 1`. Coordinate spaces are explicit:
`page_normalized` or `asset_normalized`. Keep original dimensions, units, rotation,
scale and crop offsets for invertible source mapping. PPTX images remain linked
to slide/shape and original EMU placement; do not pretend an image crop is a full
slide rendering. Old locators remain valid without bbox fields.

Descriptions and user annotations are immutable revisions. A new active revision
replaces the old one in the next search generation, not in historical citations.
Store derived revisions separately from native extraction; do not call the current
whole-document `publish_extraction` to append a figure description, since it deletes
existing units/assets. Source previews can resolve retained revision IDs.

## Evidence policy

| Provenance | Permitted use | Never claim |
|---|---|---|
| `native_text` | Normal pack claim support, subject to the existing checks | That NLI proves the original author is factually correct |
| `ocr` | Labelled transcription and retrieval | OCR-derived measurements/numbers are certified |
| `vlm` | Labelled model interpretation with an image citation | The description verifies the image or itself |
| `user_annotation` | Labelled user correction/comment | A user edit is automatically verified source evidence |

At claim level, independently supporting native evidence can earn normal support;
merely retrieving a native passage beside a VLM passage cannot. Figure-only claims
remain `Support.UNVERIFIABLE`, with `verification_kind=interpreted`, and a correctly
labelled answer may be delivered as `degraded`, not falsely accepted as verified.
OCR-only claims use `verification_kind=ocr_transcribed`; annotations use
`verification_kind=user_annotated`. Absent support, invented facts and contradictory
native evidence still trigger revision/insufficient evidence. Preserve the core
decision vocabulary and keep interpretation separate from a missing-stage warning.

`StudyReport` carries claim-level provenance/basis alongside existing claims.
VLM consistency checks may detect conflicts but cannot increase verified grounding
or numeric certification. `grounded_fraction` counts independently supported native
claims; report interpreted/transcribed coverage separately. Derived-only results
must not be thrown away just because their native-grounding fraction is zero.
Native lexical fallback remains `native_unverified`/degraded when semantic support
is unavailable; a provenance label alone never earns a verified badge.

Numeric checks can report conditional arithmetic correctness while keeping OCR/VLM
inputs unverified. Derived text cannot supply certified numeric inputs to biology
tools or the external critic. Scientific labels such as BRCA1/IL-6 are not numeric
measurements merely because they contain digits. No annotation silently promotes a
value to certified. Confidence remains an explicitly non-calibrated heuristic.

## Intake, figure selection and OCR

Validate/decode PNG/JPEG in a bounded worker. Preserve the original, create an
upright sanitised preview and retain the inverse orientation transform.

For PDFs, expose per-page extraction/rendering instead of wrapping OCR in the
current whole-document parser deadline. Retain good native text. Detect empty or
obviously garbage text layers (replacement characters, control characters or long
split-letter runs) and offer/perform CPU OCR for the affected page; retain both
raw versions with warnings. Do not trigger OCR merely because of Greek symbols,
short scientific labels or unfamiliar words. Provide an explicit forced OCR action.

Use installed Tesseract TSV through a cancellable, bounded subprocess for words,
confidence and boxes. English plus orientation data are currently installed; other
languages are selectable only when installed. Record engine/language/version,
reading order, transform and per-word confidence. OCR may miss handwriting/math;
report low quality rather than inventing a correction.

Figure candidates include PPTX embedded raster assets, PDF images, caption/drawing
anchored rendered regions and manual crops of pages/images/assets. A vector-only
figure on a prose-heavy page must remain discoverable. If automatic region bounds
are uncertain, expose a page candidate for manual selection, not an exact invented
figure bbox. Preserve panels/legends and nearby captions; classify mixed/unknown
figures explicitly. Skip tiny decorative/repeated logos heuristically with visible
reasons and a manual override. Recurrence alone is not a reason to discard a diagram.

Text-only pages do not automatically incur VLM cost, but manual selection is always
available. Record candidate coverage and exclusions; heuristics are not a guarantee
of finding every figure. Blank/image-only documents retain assets and an explicit
visual-only state even if OCR finds no text; they do not falsely become text-ready.

## Jobs and provider interface

`FigureDescriber.describe(FigureInput, *, timeout_seconds) -> FigureDescription`
returns a validated record with kind, visible labels, axes/units, relations,
summary and uncertainties. Kind is one of `pathway`, `micrograph`, `gel`, `graph`,
`structure`, `table_image`, `mixed`, `unknown`. Output also records raw response,
provider/model identity and token/time usage. Hints from OCR/captions are marked as
hints, not proof that a label is visible. Require `unreadable`/uncertainty instead
of guessing. Disable tool execution and external URL/image fetching.
The common describer owns validation/repair; provider adapters implement
`VisionBackend.complete(FigureInput, *, repair, timeout_seconds) -> ProviderResponse`
and return raw text plus actual provider metadata/usage. This keeps bounded repair
consistent instead of nesting provider-specific retry loops.

A single type-aware structured prompt performs classification and description.
Validate JSON and field bounds: at most 64 labels, 4 axes, 64 relations, 32
uncertainties, 1,500 summary characters and 64 KiB raw response. Unknown fields,
invalid bboxes, malformed/truncated responses and extra instructions fail validation.
First apply deterministic JSON parsing; if structural repair is needed, allow one
additional call to the same frozen provider/model. Do not silently change scientific
content or retry a factual disagreement. A request timeout with unknown completion
is a visible failure, not an automatic duplicate upload.

Use local Ollama by default. Inspection on 2026-10-07 confirmed installed
`qwen3.5:4b` advertises vision; its quality and peak memory have not been measured.
Probe it only after explicit GPU permission. Pin its actual digest at job start.
Another model is a new explicit configuration/job, never an automatic fallback.
Check availability/capabilities/licence before a real job. An opt-in managed model
swap may unload only AURA's generator, never unrelated applications/models. GPU
preflight is advisory; a busy GPU blocks/pauses the job. OOM preserves checkpoints
and existing pack indexes. CPU offload is not an unannounced substitute.

Optional Groq uses the same schema and currently documented `qwen/qwen3.8-27b`.
Require permission for selected crop bytes, OCR hints and adjacent text; show the
payload categories before start. No private-image URL hosting. The key stays in
`GROQ_API_KEY`. Record the provider-returned model/revision if available; do not
invent a digest for an opaque hosted model. Limit one image per request, disable
thinking, use JSON mode, enforce a configured per-job token budget (default 50,000)
and account for every attempted call/repair. Consume usage/rate-limit headers.
On 429 pause with resume time; on exhausted budget pause. No scheduled resume or
provider fallback without explicit user action. Do not promise a free-tier capacity.
Local purge cannot erase remote retention; disclose that distinction.

Persist page and figure checkpoints before advancing. States include queued,
running, paused, failed, partial, completed and cancelled, plus per-item status,
attempt count, safe error and timestamps. The job snapshot pins sources, crops,
provider/model/config/prompt and budget. Restart interrupts the running item;
explicit resume skips identical completed items. A changed snapshot requires a new
job. Failed VLM work leaves native/OCR indexes usable; image-only packs stay visibly
unanswerable until some usable text/description is indexed.

Publish completed derived revisions and a new atomic index generation at completion
or explicit pause/cancel with retained partial results; report indexing failure
separately. Existing queries keep their immutable snapshot. Purge/deactivation
cancels new work and prevents stale checkpoint commits. Do not hold a purge-blocking
lease for an entire multi-hour job; acquire bounded per-item/publish leases.

## Frontend and private lifecycle

Extend Study material with image uploads, candidate review/manual crop selection,
explicit Start visual pass, local/hosted permission controls, per-item progress,
pause/cancel/resume and visible skipped/failed reasons. Show original crop/page,
source locator, OCR-confidence flags, provider/model and model-described/user-edited
badges in citation previews. Highlight only bboxes whose transform/frame is known.

Keep the model response and user override as distinct revisions. Re-describe never
overwrites a user annotation or original; expose which revision is active. Update
the index after edits and invalidate active answer caches while retaining immutable
historical references. Private bytes/answers stay out of browser localStorage;
previews use owned IDs, escaped content and no-store responses.

Hard purge includes renders, crops, descriptions, raw responses, annotations,
checkpoints, indexes, traces, evaluation results and local caches. Test race/restart
behaviour on temporary fixtures only, never delete the supplied PDFs or corpus.

## Frozen evaluation and acceptance

Before prompt tuning, create 20 clearly labelled project-authored figures and 40
manually keyed questions: 16 label-reading, 12 relationship, 6 value-reading and 6
unsupported controls. Include absent/invented labels, unanswerable visual quantities,
misleading caption/OCR hints and a prose-heavy vector figure. Balance pathways,
graphs, gels, micrographs, structures and image tables. Synthetic images are teaching
fixtures, not real experimental results. Private professor material is an additional
pack-local bank, never copied into tracked fixtures without permission.

Split by source figure into 12 development and 8 held-out figures, retaining 24/16
questions. Freeze bank, split, source checksums and reviewer keys before modifying
describer prompts. Development results may inform tuning; held-out results may not.
Version changes explicitly; do not rewrite keys to match the model or use Groq as
ground truth. Serving/describer modules must never load/import the gold bank or
its evaluator-only modules; test the dependency boundary and the outgoing inputs.

Measure label recall, hallucinated-label rate, relation accuracy, abstention on
unsupported questions, locator/crop correctness, numerical certification violations,
latency, memory and provider token use. Compare OCR hints on/off and local/hosted
only when resource/privacy permission is separately granted. Manually reviewed
quality metrics are null until reviewed; report denominators, errors and sample size.

Acceptance gates: provenance survives every boundary; no VLM self-verification or
OCR/VLM numeric certification; vector/manual figures work; one normal call/two
maximum; large OCR jobs exceed 180 seconds safely in fake-clock tests; checkpoints
survive restart/OOM/429; old packs/core tests pass; purge removes all derived data.
Run installed CPU OCR integration separately from fake-provider unit tests. Real
VLM results are a later explicit hardware/evaluation run, not implied by unit tests.

## Delivery roadmap and references

Implement provenance/frozen-bank foundation, then safe assets/selection, checkpointed
OCR, job control/providers, verification/retrieval, API/UI, and final safety/regression
verification. Keep Ask-with-image and image embeddings as follow-up plans rather
than expanding the first release indefinitely.

- [Existing study-pack documentation](../../study-packs.md)
- [Implementation-plan draft](../plans/2026-10-07-visual-study-packs.md)
- [Ollama Qwen3.5](https://ollama.com/library/qwen3.5:4b)
- [Tesseract TSV](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html)
- [pypdfium2 rendering](https://pypdfium2.readthedocs.io/en/stable/readme.html)
- [Groq vision](https://console.groq.com/docs/vision), [limits](https://console.groq.com/docs/rate-limits), [data policy](https://console.groq.com/docs/your-data)
