# Local document-aware study packs

Open **Study material** in the web interface. Create a general or biology pack,
upload course files, inspect the extraction report, then select that pack under
**Answer from** in Ask. Selection uses only that pack, never an implicit memory
or core-corpus fallback. The original corpus and benchmark banks are unchanged.

## Setup

From the checkout root, install the optional parser/API dependencies:

```powershell
python -m pip install -e "./aura_bio_system[api,study,visual]"
```

This checkout also has a locally installed python-pptx 1.0.2 in the ignored
`.cache/study-deps` directory. To use it with the existing verification runtime
without another install:

```powershell
$env:PYTHONPATH = 'G:/aura_llm/.cache/study-deps;G:/aura_llm/.cache/verification-deps'
python -m aura_bio.api.server
```

Use the existing frontend/launcher commands. API upload routes require
python-multipart (now part of the API extra). Missing format parsers produce an
actionable failed job, not a false ready state. Intake, outlines and previews do
not initialise the core runtime or call a model. A single CPU worker starts
lazily when private storage is first used and shuts down with the API.

Storage defaults to `.local/study-packs` relative to the checkout. Set
`AURA_STUDY_ROOT` to an absolute directory to relocate it. Roots overlapping
the original corpus/index directories and symlink/junction-owned paths are
rejected. Keep the API on its default `127.0.0.1` binding; this is a single-user
local tool, not an authenticated network file-sharing service.

## What is retained

| Format | Source navigation | Current limits |
|---|---|---|
| PDF | Physical page/printed label, geometry-extracted text, upright page preview, drawing/caption region or manual crop | Per-page extraction/rendering; scans retain previews in visual-only state. Explicit OCR/vision passes produce separately labelled derived units. Columns/math remain imperfect. |
| PPTX | Slide/shape, nested bullet levels, tables, separate speaker notes, embedded raster assets/coordinates | Text preview is not pixel-perfect PowerPoint rendering. SmartArt/charts/animations and image pixels are not interpreted. |
| XLSX | Sheet/row/cell range, original formula, separately labelled cached value, merged ranges | Hidden sheets excluded with warnings. No formula recalculation, macro execution or external-link fetching; cached values may be stale or absent. |
| TXT/Markdown | UTF-8 text, headings and exact source line ranges | No executable HTML/script preview. |
| PNG/JPEG | Upright single-frame image, original checksum, manual crop | Signature/pixel checks and EXIF orientation; derived previews/uploads strip metadata. Explicit OCR or vision, not automatic interpretation. |

Original bytes/checksums remain unchanged. Short adjacent units merge for
retrieval while retaining every unit, locator and original character span.
Chunk windows use offline Unicode lexical token estimates, not exact model
tokens. Maximums: 50 MiB/upload, 200 MiB expanded Office ZIP, 2,000 pages/slides,
200,000 visited workbook cells, 10 million extracted text characters and 180
seconds for Office/text extraction. PDF extraction/rendering has a separate
60-second deadline and durable checkpoint per page, with no 180-second outer
PDF deadline. The workbook rectangle includes blank cells: move
far-away sparse content into a smaller workbook if it exceeds the limit.

Legacy PPT/XLS, DOCX, full-slide pixel rendering and reliable handwriting/math
recognition are not supported. Exhaustive study guides/flashcards/whole-book
summaries need a later coverage-aware workflow; top-k retrieval does not read
every page. Unsupported structures and empty units remain visible in reports.

## Retrieval and answering

Uploads progress through queued → extracting → extracted → indexing. By default,
indexing loads the cached `BAAI/bge-base-en-v1.5` encoder on CPU and atomically
publishes FTS5 plus normalized FAISS vectors (**hybrid-ready**). Queries use
BM25/dense reciprocal-rank fusion, then cached CPU `BAAI/bge-reranker-base` pair
scoring. No model is downloaded and no GPU is used by these pack stages.
`AURA_STUDY_INDEX_MODE=sparse` opts out of automatic embedding for new sparse
packs; ordinary reindexing preserves existing hybrid capability. A missing
encoder produces an explicit **sparse-ready** fallback with a job/document
warning. Explicit dense requests fail rather than falsely succeeding. The UI's
**Build cached dense index (CPU)** button remains a retry/rebuild action.

Pack query stopwords exclude grammatical filler, not scientific identifiers or
negation. Search-only Unicode/Greek-letter aliases and line-break dehyphenation
are shared by embeddings and FTS5 (`porter unicode61` stemming). Cited chunk
text, every source-unit span and original bytes are not rewritten by this search
normalization. PDF units additionally retain the basic extraction as metadata.
PDF spacing is checked at narrow/wide tolerances against the basic extraction;
the candidate with fewer obvious split-letter/merged-word artifacts is retained.
This heuristic does not spell-correct domain terms and cannot solve every layout.
Older indexes stay readable but advertise a rebuild warning; PDFs extracted
before the geometry fix need re-extraction, not just an index rebuild.

Reranking explicitly applies sigmoid and rejects scores below
`AURA_STUDY_RERANK_MIN_SCORE` (default `0.1`, the existing evidence selection
policy's absolute relevance floor). A rigid `0.5` cutoff lost secondary supporting
passages in the real-material development probe, so it is not the default.
This is a configurable relevance heuristic, not calibrated confidence
or proof of answerability; per-claim verification remains necessary. Dense nearest
neighbours alone do not establish support. Actual search mode, models, rerank
report and skipped-stage warnings appear in search responses and answer traces.
Missing query models are explicitly reported. Failed index jobs retain previous
snapshots; interrupted jobs can be retried. Document purge removes its content
immediately with a sparse rebuild, then queues normal hybrid reindexing.

Explicit comparisons (including “compare X with Y”) expand the question's own
subjects, score each separately and reserve a positive evidence anchor per
subject before filling the remaining passage budget. Reports record the actual
query parts and score floor. This improves multi-source coverage without adding
facts or answer keys; unsupported subjects are not supplied invented evidence.

The same orchestration performs retrieval, optional reranking, evidence
selection, generation, verification, optional critique, bounded revision and
tracing. Pack-specific differences are intentional:

- Neutral routing and mandatory retrieval; biology tools only with the explicit
  biology adapter. No core ontology false-premise hints or memory-completeness
  prompt. Upload text/drafts are quoted untrusted data.
- Source/document count caps disabled, while relevance, deduplication, passage
  and context budgets remain. Deeper levels expand neighbours in pack SQLite.
  Robust pack selection allows at most six passages and 14,000 characters;
  the core's separate 9,000-character robust budget is unchanged. These are
  bounded estimates, not exact tokenizer guarantees for every external model.
  Pack prompts keep each selected chunk intact; the core's sentence compression
  is not applied to packs, so it cannot drop qualifiers while retaining their
  source-unit locators. Passage-count/chunk-size limits still bound context.
- Each factual claim needs its own relevant inline citation. Semantic NLI is
  cache-only; without it, lexical checking produces **degraded**, not verified.
  Failed support/repair yields insufficient evidence. This is not a guarantee
  that a classifier always understands a claim correctly.
- General arithmetic/unit checks accept explicitly marked `Derived:` equalities
  with literal inputs in the question/cited source. They use bounded AST
  arithmetic/Pint, not arbitrary model-generated Python or workbook formulas.
  Unrecognised calculations are not advertised as numerically verified.

Generation uses the configured local Ollama model (`AURA_OLLAMA_MODEL`); without
one, labelled extractive source snippets remain available, not a pretend tutor.
`AURA_ACCURACY_MODE` defaults to robust for packs, `AURA_DRAFT_CANDIDATES` defaults
to 2, `AURA_STUDY_NUM_PREDICT` to 768, and `AURA_STUDY_SEED` to 42. Reranking is
enabled by default if cached; `AURA_STUDY_RERANK=0` disables it. If unset, this
setting respects an explicit `AURA_RERANK` value. Missing reranker weights produce
a visible warning, not a network fetch. Critique is off
unless explicitly requested; the UI warns that the question, draft and private
excerpts would leave the device. Internet search is not added here.

## Visual passes (2026-10-07)

Inspect a document, select figures, then choose **Start visual pass**. Native
ingestion/search/asking never starts a VLM. Figure discovery includes rendered
PDF drawing regions, conservative whole-page candidates, embedded slide images
and manual upright crops. Skip reasons (tiny/repeated logos, text-only pages,
selection limits) remain visible and can be overridden explicitly. Identical
crop pixels **and** identical hints/model/config reuse a description; every
occurrence keeps its own locator and immutable revision. A PPTX crop refers to
its embedded image, not a fabricated full-slide render.
PDFs ingested before this addition keep their existing native-text workflow;
figure discovery does not silently re-render them. For visual testing, upload
the original PDF into a new study pack so the new page-rendering intake runs.

Local prerequisites: optional Pillow/pypdfium2, an installed vision-capable
Ollama model and accessible `nvidia-smi`. Default local model is the existing
`qwen3.5:4b`; no pull occurs. Start pins its reported digest and checks free
VRAM/GPU activity. Busy/missing/OOM states are visible; unrelated models/apps
are never unloaded. The optional managed swap unloads only
`AURA_STUDY_MANAGED_GENERATOR` (default `aura-bio:v0`) with explicit approval.
This resource check is conservative and **does not establish 4 GB fit**.
Use the `visual` extra alongside the existing `study` extra for these Python
dependencies. Without the optional PDF renderer, native text ingestion remains
usable with a visible preview warning; scans without text/previews fail clearly.
The adapter respects `AURA_OLLAMA_HOST` (or `OLLAMA_HOST`) only on loopback HTTP.

For OCR, install Tesseract separately and its desired language data. Set
`AURA_TESSERACT` to the executable if it is not on PATH/the standard Windows
location. The engine consumes PNG bytes via stdin, outputs word/confidence/box
TSV and has a 60-second per-image deadline (configurable 5–300 seconds). Missing
engine/languages or garbage native text are visible, not silently corrected.
Select the OCR pass explicitly; garbage/empty native text is detectable with
`needs_ocr`, not permission to run an answering model. OCR confidence is not a
truth score. Forced OCR preserves native text separately.

Limits: 25M decoded image pixels; PDF previews <=200 DPI/12M pixels; 512 MiB
visual asset budget per document with partial-coverage warnings. Vision crops
<=1M pixels; one image/request; default context 4096/output 2048, temperature 0,
thinking off by default. Ask uses output 2048/deadline 180 seconds for the visual
pass, or output 4096/deadline 600 seconds when local thinking is explicitly enabled.
The live schema allows 32 labels and 24 visible connections, with bounded summaries
and uncertainties; archived descriptions remain readable. One structured description normally takes one provider call;
one structural repair at most (two attempts total), within the figure deadline.
Table descriptions use headers and row associations in the summary, not arrows
or graph axes. Structural repair pins recognizable prior figure kind and labels,
even when another JSON field is missing or oversized; it cannot add labels to
justify a dangling connection. Truncated outputs remain visible failures, not
repair inputs. Explicitly supplied budgets/deadlines are still honored.
Default figure deadline is 300 seconds (30–600 configurable), one visual worker,
20 selected figures/job by default (1–200 via the API). Schema validation is
**not** factual verification. Raw outputs, actual identities, hashes, usage,
uncertainties and failed attempts stay in the pack.

`native_text`, `ocr`, `vlm`, `user_annotation` survive units, homogeneous chunks,
evidence, private traces and citations. Independent relevant native support can
earn `native_verified`; lexical-only native support is `native_unverified`.
Figure-only answers are **interpreted**, OCR-only answers **transcribed**, edits
**user-annotated**, never verified by NLI agreeing with their own generated text.
Unrelated native neighbours cannot launder figure claims. Conditional arithmetic
can be correct while its visual/OCR inputs remain unverified. Gene identifiers
such as IL6 are not automatically treated as measured numbers.

Jobs checkpoint every figure/page. Restart pauses unfinished visual jobs;
**Resume unfinished figures** is explicit and skips completed matches. Provider,
model digest, prompt, source/crop/OCR/context or configuration changes require a
new job. A 429/depleted rate-limit header pauses until reset; it never schedules
an upload automatically. Partial results queue the existing atomic CPU index
worker; the previous generation stays usable until publication succeeds. Pause,
cancel, deactivation and purge reject late writes. Annotations are immutable
separate revisions; re-description never silently replaces an active user edit.
Earlier citation previews keep their exact revision.
The document's **Visual job history** reopens durable jobs after a page reload;
opening history/status never starts or resumes inference. Real transports run in
a spawned process, so the figure deadline also bounds slow HTTP/preflight work;
a killed transport has unknown completion and is never automatically re-uploaded.

Groq is opt-in: enable per-pack external permission, preview the selected
owned crops and OCR/caption hints, then approve that exact payload and Start.
`GROQ_API_KEY` is read only from the server environment, never pack records,
browser storage or a `VITE_` variable. There is no silent local/hosted fallback.
Default hosted job token budget is 50,000, with usage/rate-limit headers recorded;
each initial/repair upload reserves a conservative image/prompt/output allowance
before sending. Reported usage settles the allowance; failures without usage
retain it, including across restart. This is a client planning limit, not a
guarantee of a provider's changing billing/token accounting.
No fixed free-tier capacity is promised. Local purge cannot remove hosted logs
or change the provider's retention policy. Adapter contracts follow the
[Ollama chat API](https://docs.ollama.com/api/chat) and
[Groq vision API](https://console.groq.com/docs/vision).

### Frozen figure evaluation

Label accounting v2 separates exact target-label recall from unmatched reported
text. Titles, legends and value annotations may be visible while absent from the
frozen node-label key, so `unmatched_label_rate` is not a hallucination rate.
`hallucinated_label_rate` stays null until complete per-figure manual review:
on a reviewed copy of the records, use `review.label_review_complete=true` and
`review.hallucinated_labels` listing reported strings actually absent from the
source image (an empty list explicitly confirms no inventions). Duplicate
question records for the same description must have consistent label reviews.
The rate uses reported labels from reviewed figures only; pending-figure counts
make partial review visible. Original records and the frozen bank stay unchanged.

Rescore an existing run without inference or overwriting its historical summary:

```powershell
python aura_bio_system/benchmarks/rescore_figure_labels.py PATH_TO_RUN/records.jsonl --split dev
```

This writes `summary.label_accounting_v2.json`, with input/scorer/bank hashes and
`inference_rerun=false`. An existing output is rejected; use `--out` with a new
filename for a separately reviewed revision. Relation/value/abstention review is
still required independently of label accounting.

The evaluator-only `figure_sources.json`/`figure_bank.jsonl` freezes 20
project-authored **synthetic teaching figures**, 40 independently keyed questions:
16 label, 12 spatial relationship, 6 exact printed value, 6 unsupported controls.
Splits are figure/source-disjoint: 12 development figures/24 questions and
8 held-out figures/16 questions. Misleading hints and absent labels/values are
explicit controls. This is an initial synthetic bank, not a real biology-figure
accuracy claim; more difficult gels/micrographs and real licensed material remain
necessary before claiming scientific visual understanding.

`benchmarks/run_figure_eval.py --help` documents the explicit harness. Choose an
existing pack, generated 32-hex run ID and exactly one split. Real model calls
require `--allow-inference`; hosted calls additionally require pack permission
and `--approve-external`. This harness records descriptions, not pretend scored
LLM answers. Run/config/source/prompt and pinned local model-digest hashes reject mismatched resume; outputs
stay in `pack/traces/evaluation/<run-id>/`. Error records remain visible, not
automatically rerun. Manual answer/relation/value/abstention/locator review stays
null until a reviewer supplies it. Keep original records and score a reviewed
copy; do not overwrite original model output. Unit tests and the installed CPU
Tesseract smoke check do not establish VLM quality. No live VLM/Groq evaluation
has been run as part of this implementation.

Ask-with-image, visual embeddings, Mermaid/charts and generated illustrations
remain separate later milestones; none runs implicitly with this feature.

## Privacy, deactivation and permanent deletion

Private originals, assets, source units, search generations, traces and evaluation
outputs live inside their pack. Pack answers do not enter the core TraceStore or
new browser localStorage archives. Source previews use generated IDs, safe raster
MIME types and escaped text, not arbitrary client paths. Original downloads are
attachments. Foreign browser origins are rejected; origin-less local CLI calls
are allowed. `AURA_STUDY_ALLOWED_ORIGINS` overrides the localhost/127.0.0.1 UI
allowlist (ports 5173/4173/8000).

**Deactivate** retains originals and historical citation previews but removes
that document from active retrieval. **Permanent deletion** requires typing
the exact target ID. Document purge removes that document's originals/assets/
units and invalidates the **whole pack's** old indexes, trace/evaluation history
and cached answers, then rebuilds remaining active material. Pack purge removes
the entire pack. Active workers/queries/SSE replays hold leases; purge blocks new
readers and waits for existing handles. Failed cleanup stays blocked and its
persistent journal permits retry after metadata removal or restart. Select
**Retry failed cleanup** to confirm the same original target; retrying a
document cleanup does not require permission to delete the whole pack.

Deletion clears this server's cached runs and matching records/caches in the
current browser. It does not erase information already downloaded/displayed in
another browser, user exports, backups or forensic SSD remnants. Do not put
secrets in a shared checkout or deliberately expose this local API to a network.

## Frozen grounding evaluation

The separate [bank](../aura_bio_system/benchmarks/study_pack_bank.jsonl) contains
30 questions: 20 supported, 10 common-knowledge-but-absent controls and 8
multi-unit items. Upload both exact project-authored files from
`aura_bio_system/benchmarks/study_fixtures/` into a general pack. Their invented
names/values are clearly fictional, not scientific results. Keys are checked
against these files and loaded only by the evaluator, never the prompt/runtime.

OpenStax chapter 6 was excluded: its current attribution explicitly requires
prior permission for AI ingestion. No external chapter was downloaded or used.
The source/hash manifest records this decision. A permitted real textbook/deck
evaluation remains future work; the synthetic bank alone cannot establish
real-world extraction quality or accuracy uplift.

Retrieval-only (cached CPU embedding/reranking models, no answering LLM), when desired:

```powershell
python aura_bio_system/benchmarks/run_study_pack.py --pack-id PACK_ID --retrieval-only --tag pack_retrieval_v1
```

Retrieval-only uses the pack's actual hybrid index and configured cached reranker;
it does not run generation or verification. Use `--sparse-only` for an explicitly
labelled BM25-only diagnostic. Model names, score floor and actual retrieval mode
are recorded in resume metadata; unavailable configured models fail the benchmark
instead of silently replacing the requested stages.

Once the GPU is free, a separate explicit full scoped run:

```powershell
$env:AURA_GENERATOR = 'ollama'
$env:AURA_RERANK = '1'
python aura_bio_system/benchmarks/run_study_pack.py --pack-id PACK_ID --model llama3.2:1b --tag pack_llama_v1
```

The harness refuses silent model substitution. `--critic` is a separate explicit
private-excerpt opt-in; requested/enabled components are recorded separately.
Outputs stay under the pack's `traces/evaluation/`. Matching tags resume only
with identical model/source/code/bank/config hashes; changed setup needs a new
tag. Error rows are reported, not secretly rerun under a different configuration.

Metrics distinguish selected-unit recall/coverage, exact locator validity,
absent-question abstention, and manually reviewed answer/citation correctness.
Recall uses selected evidence in full mode and top-10 hits in retrieval-only
mode. Unreviewed citation/grounded-answer metrics are **null**, not invented
scores. Add `manual_review: {"grounded_answer_correct": true/false,
"citation_correct": [true/false, ...]}` to audited rows before rescoring with
`evaluate_pack_run`; retain originals and document the reviewer. Passing unit
tests or high token overlap is not an accuracy result.

Implementation decisions and verification are recorded in the
[plan](superpowers/plans/2026-10-06-study-pack-ingestion.md). No model benchmark,
training, core-bank tuning, commits or pushes are part of this implementation.

## Implementation verification — 2026-10-06

- Backend: `python -m unittest discover -s aura_bio_system/tests -q` —
  361 tests passed in 123.883 seconds, no skips. Cached CPU models/offline mode;
  no Ollama generation benchmark or GPU work.
- Corpus retrieval: 18 tests passed in 15.986 seconds, using temporary fixtures.
- Frontend: 13 tests across 5 files passed; TypeScript/Vite production build passed.
- `git diff --check` passed; tracked biology JSONL/text banks have no changes.
- Real parser fixtures exercise pages/OCR detection, grouped slide text/notes/
  images, sheet formulas/merged cells/date caches and text source ranges.
  Lifecycle tests cover extraction timeout, restart, leased query/SSE purge,
  partial deletion retry, failed index publication and cross-pack isolation.
- Desktop and 390px mobile UI screenshots inspected with existing headless
  Playwright; no horizontal mobile overflow or core health initialization on
  private workspace navigation. In-app browser verification was unavailable
  because its provider failed to initialise; no browser was installed.

Review was author self-review, not an independent agent review. Initial frontend
RED assertions were not observed because the first test worker failed to start;
later privacy/restart regression tests did exercise failing assertions before
fixes. Existing Requests dependency, sklearn CachedEncoder, SapBERT pooling and
Torch deprecation warnings remain; passing tests do not resolve those warnings.
All changes remain uncommitted in the pre-existing dirty checkout. Execution
logs/decisions are retained in the ignored
`.superpowers/sdd/2026-10-06-study-pack-ingestion/` directory.

## Visual implementation verification — 2026-10-07

- Backend: 464 tests passed in 146.081 seconds, CPU/offline configuration.
- Corpus retrieval: 18 tests passed in 16.536 seconds, temporary fixtures only.
- Frontend: 18 tests across 8 files passed; TypeScript/Vite production build passed.
- Installed Tesseract CPU smoke passed on a project-authored figure; no live VLM
  generation, Groq call, private hosted upload, GPU benchmark or model download.
- Frozen figure manifest remains SHA256
  `d81695bd8633ca163fc2f764dde74a8147b99fdae8e85641edafd83b4a7dfe65`.
- Browser inspection used loopback servers and synthetic fixtures: desktop source
  preview/crop controls, escaped descriptions and mobile layout; no horizontal
  overflow. Temporary servers and browser tab were stopped after inspection.
- Test-first self-review caught and fixed rotated/CropBox region alignment,
  unrelated native citations certifying question-only arithmetic inputs, exact
  figure/asset anchoring, unknown hosted completion reservations, pinned-digest
  evaluation resume, and slow HTTP transport deadlines.
- `git diff --check` passed using the repository's normal line-ending settings.
  Tracked JSONL banks have no changes; no corpus/index mutation or commit/push.
  Existing Requests/sklearn/SapBERT/Torch warnings remain unresolved.

Author self-review only; passing fake-provider/schema tests does not establish
real figure understanding, scientific validity, unsupported-question behaviour
or 4 GB GPU fit. The initial bank is explicitly synthetic. Live model evaluation
and manual review remain separate work. Verification logs/screenshots are in
`.superpowers/sdd/2026-10-07-visual-study-packs/`; implementation decisions are in
the [visual plan](superpowers/plans/2026-10-07-visual-study-packs.md).

## Ask with an image

Attach one PNG/JPEG on Ask, type a question, and optionally select one saved
context pack. The original biology corpus is never mixed into an image answer.
Upload performs bounded CPU extraction only. One explicit **Ask** runs the
selected OCR/vision pass, indexes the resulting evidence, then starts answering;
the visible stages stop on failure, missing models or a busy GPU. No automatic
model pull, provider switch or answer-model fallback is attempted. Clicking Stop
cancels browser intent and requests visual-job cancellation; an already accepted
provider request may still finish, but cannot mount into the next question.

Figure inspection, manual crops, user annotations, checkpoints and explicit
resume reuse the study-material controls. Vision receives the bound question as
untrusted focus context in its existing structured call; question-specific
descriptions are not reused for another question. Generic and question-focused
jobs share the versioned schema; changed prompts/configuration require a new run,
not mixed-profile resume. OCR/VLM/user-annotation provenance survives retrieval,
citations and verification: an interpretation never verifies itself, and
arithmetic using pixel-derived inputs remains conditional. Relevant native
context can provide independent support, not blanket approval of the image.

Images are temporary **on-disk** packs, hidden from the saved-material list.
Their absolute deadline defaults to one hour, unchanged by polling or retries.
`AURA_ATTACHMENT_TTL_SECONDS` may be 300–86400. At most 20 temporary images are
retained. The server denies expired reads/work immediately and retries cleanup
every minute/on startup; active readers or file locks can delay physical deletion.
Remove reports pending cleanup when needed. Local deletion cannot erase hosted
provider logs. Save as study material removes the deadline without changing
source/citation IDs; detaching a saved image never deletes its retained pack.

Hosted vision still requires pack permission, exact crop/hint/**question** payload
preview and separate approval. External critique defaults off independently and
discloses both the image and optional private context. Private questions, image
metadata and answers are not archived in browser storage, including after Save.
Expiry or removal of either source clears dependent runs; leases protect active
readers, not a right to publish after expiry. Temporary storage is local, not
encrypted or memory-only.

Verification uses authored fixtures and fake providers. Live scientific figure
quality, hallucination/value-reading performance and 4 GB fit still require the
frozen figure-eval pass with a real model; unit tests do not establish those.

Deploy this flow with one API worker. The inference reservation coordinates
jobs within that process, not other API workers or unrelated Ollama clients.

For numbered PDF figures, broader study questions, optional thinking, caption
geometry and index-readiness guarantees, see the
[document question flow](document-question-flow.md). Existing packs and the original
biology corpus are not rewritten by this addition.

CPU/offline verification covered 107 attachment tests, 26 frontend tests, the
frontend build, two mocked desktop/mobile browser flows and 18 corpus retrieval
tests. The backend's 572 discovered cases were covered using isolated test-file
runs and refreshed focused checks. The combined Windows test process crashed
with a native access violation; it is not recorded as a passing full-suite run.
