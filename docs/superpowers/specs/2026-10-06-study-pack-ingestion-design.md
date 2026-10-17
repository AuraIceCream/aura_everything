# Document-aware study-pack ingestion

Status: implemented inline after user approval; self-reviewed. See the implementation plan and `docs/study-packs.md` for verification and deferred work.
No commits, pushes, model downloads, GPU jobs or benchmark runs are authorised by this document.

## Purpose and constraints

A student can upload their course material, inspect what AURA extracted, ask
targeted questions and follow citations to the exact slide, page or cells.
Specialised books and lecture decks must retain their structure and identity.
An answer is better grounded when it uses relevant source detail accurately;
verbosity, citation count and confident prose are not correctness measures.
Perfect extraction, retrieval or factual support is not promised.

The original biology corpus, indexes, paths, benchmark banks and default query
behaviour remain unchanged. Study packs are local, persistent and separately
indexed. Extraction does not call Ollama, an external API or a GPU. Parsing is
format-neutral; selected packs use neutral routing and source-only prompts, with
biology checks enabled only by the explicit biology adapter.

## Approach

Recommended: a sidecar study-pack store with format adapters and a searcher
compatible with the existing pipeline's evidence interface. Reuse orchestration,
reranking, verification, revision and tracing; do not create a weaker alternate
answering shortcut. Request-specific configuration must not mutate the shared
core runtime or another request's searcher.

Alternatives considered:

- Merge uploads into the existing corpus: conflicts with isolation and safe removal.
- Send entire files directly to the LLM: simpler for tiny decks, but unsuitable
  for long books, selective retrieval and reliable source locations.

## First-release formats and document awareness

| Format | Preserved structure | Citation location and limitations |
|---|---|---|
| PDF | File identity/title, text per physical page, available page labels and headings | File + physical page; printed label where supplied. Scanned/image-only pages need OCR; complex reading order may be imperfect. |
| PPTX | Original slide order/number/title, text boxes and bullet levels, grouped text, tables, speaker notes separately identified, embedded image assets and shape coordinates | File + slide + optional shape/table/notes locator. No claim to interpret diagrams, animations or unsupported SmartArt. |
| XLSX | Workbook/sheet identity, non-empty rows/cells, headers as source content, units as written, merged-cell information, formulas separately from cached values | File + sheet + cell range. No formula execution or guarantee that cached values are current. Hidden sheets are reported and excluded in this release. |
| TXT/Markdown | Encoding-validated text, headings and original line ranges | File + section/lines. Raw HTML is never executed in previews. |

Legacy PPT/XLS, DOCX, standalone images, OCR and vision interpretation are later
adapters, not silently advertised as supported. Unsupported shapes/charts and
empty pages/slides produce coverage warnings. Keep original files byte-for-byte;
never open and save them over their uploaded originals.

Initial parser dependencies are pypdf, python-pptx and openpyxl. PPTX support
needs an optional dependency not currently installed; dependency installation
and version checks belong to the approved implementation plan. Retain pypdf for
this release rather than assuming a different parser fixes every layout. Show a
reading-order warning for complex PDFs. A document with no usable text fails
with an actionable OCR-required message; mixed documents preserve all physical
page numbers and explicitly mark pages with no extracted text as uninterpreted.
Do not infer that every empty page is scanned. OCR is not run automatically.

## Storage and extraction model

Add an `aura_bio.study` package for schema, extraction adapters, storage,
indexing and the pipeline-compatible searcher. Add API routes separately under
`api/study_packs.py`; existing core queries must not depend on this store.

Proposed local storage root: `G:/aura_llm/.local/study-packs`, overridable by
`AURA_STUDY_ROOT`. Keep it ignored by Git; never write inside the core data roots.

- Pack: stable ID, name, creation time, document list and index generation.
- Document: generated ID, original filename, byte checksum, detected format,
  parser version, extraction state, coverage counts and warnings.
- Unit: original page/slide/sheet-row identity, ordering, heading/breadcrumb,
  typed source locator, extracted text/table content and asset references.
- Chunk: stable ID, unit/document/pack IDs, exact locator and inherited context.
  Split within meaningful units; overlapping chunks must not lose provenance.
- Asset: generated ID, checksum, type, source unit and safe local access route.
  Image retention is not evidence that its pixels have been interpreted.

Use SQLite for metadata and FTS5, plus a separate dense index/map per pack.
Deduplicate identical bytes within a pack; filenames alone are not identities.
Short adjacent units may merge toward a 450-token target, but never across files,
worksheet boundaries or different section/notes roles. Every merged chunk keeps
all contributing unit IDs, original text spans and locators. Headers added for
retrieval are labelled context rather than misrepresented as original cell text.
XLSX formulas without cached values remain formula text, with a warning; no
value is invented and no workbook formula is executed or recalculated.

Recoverable deactivation rebuilds only the pack's active search snapshot; original
material and historical citation previews remain available and the UI says so.
An additional, explicitly confirmed hard purge removes the chosen original,
assets, units, chunks, affected index snapshots and private traces. Document purge
invalidates that pack's old snapshots and history, then rebuilds from its remaining
active documents; pack purge removes the entire pack. Core data is never touched.
Private traces and failures live under the pack, not in the core trace database or
JSONL mirror. Private pack answers are not archived in browser localStorage.
Deletion also clears server run caches and any matching browser entries. It does
not promise forensic erasure from SSDs, backups, user downloads or another browser.

## Processing and retrieval

1. Create/select a study pack; stream a bounded upload to a generated path.
2. Validate format/container and checksum; enqueue isolated CPU extraction.
3. Publish structured units, original-file references and an extraction report.
4. Build FTS5. Build dense vectors separately with the existing cached embedding
   model; CPU execution is supported and GPU indexing is an explicit later action.
5. Atomically publish a complete index snapshot. Show sparse-only/dense-ready
   states accurately; never label sparse retrieval as a completed hybrid stage.
6. Search only the selected pack before reranking. Preserve document/section
   context and neighbouring source-unit relationships for deeper retrieval.
7. Pass selected evidence through the existing generation/check/revision/trace
   flow, carrying source locators into the returned citations and preview links.

Extraction jobs are persistent and distinguish queued, extracting, extracted,
indexing, sparse-ready, hybrid-ready and failed states. A restart marks unfinished
jobs interrupted and permits retry; a partly built index cannot become ready.
Each search pins one published generation. Pack search supplies a neighbour-fetch
interface backed by its own SQLite: deeper retrieval expands around matched units,
not merely the first chunks of a document. Expansion failure is traced explicitly.
The core sibling-fetch implementation remains the fallback for core searches only.
Pack evidence selection disables both per-source and per-document count caps;
relevance, duplicate filtering, passage-count and prompt budgets still apply.

The manifest lets users browse a whole document, but targeted top-k retrieval
must not be described as having read every page. Whole-pack summaries, automatic
flashcard generation and exhaustive revision packs require a later coverage-aware
generation workflow; they are not automatic ingestion-time model calls.

## Answer scope, citations and privacy

Existing requests default to `evidence_scope=core` and preserve their behaviour.
New study requests specify `pack_id` and `evidence_scope=pack_only`. The UI defaults
to uploaded materials only when a pack is selected. Combined pack/core retrieval
is a later explicit option, not an implicit fallback in this release.

Pack-only answering uses a separately constructed prompt set (including repairs),
not the core system prompt with an extra flag. No memory-enrichment directives,
ontology false-premise hint or candidate-pool vocabulary checklist enter it.
Uploaded instructions are quoted source data, not authority over the assistant.
It retrieves even when
the tutor route would otherwise skip retrieval. Unsupported claims trigger repair
or an explicit insufficient-support/degraded result, not a claim of verification.
Check factual inline citations against the selected source and retain all existing
numeric/contradiction checks. Computed results must be identified as derived,
with source inputs cited where those inputs came from a document.

Skip the biology entity lexicon and learned 18-subdomain router in pack-only mode.
Use a neutral study route with the declared learner level/style/depth and mandatory
retrieval. General packs retain citation, scoped entailment, delivery and applicable
safe numeric/unit checks, but do not run biology terminology/process/pathway checks.
Biology tools require an explicitly selected biology adapter; never infer that
importing a domain-neutral Python library makes its biology-specific rules general.
Numeric inputs must be present in the question or cited units, not invented from
memory. Report each enabled, skipped or unavailable checker honestly. Token overlap
alone cannot certify semantic support; missing semantic checking yields a degraded
result, not a claim that every cited statement is proved. This policy uses the
existing orchestration, candidate selection, critique and bounded-repair flow.

Citation payloads retain existing fields and add optional document ID and typed
locator fields. Source previews show the actual cited text and original unit;
PPTX/Excel text previews are not presented as pixel-perfect Office rendering.

Uploaded text is untrusted evidence, never instructions. No macros, embedded
scripts, external workbook links or uploaded hyperlinks are executed/fetched.
Originals/previews are local by default. External critique remains opt-in, with
a warning that selected private excerpts would be sent to the chosen provider.

## API and UI boundary

API supports pack creation/list/detail, upload/job status, document/unit preview,
pack-scoped search, recoverable document deactivation and confirmed hard purge.
Extend run requests
with validated optional pack/scope fields; reject missing/unknown/not-ready packs
instead of silently answering from the core corpus.

The interface adds study-pack management/upload, extraction coverage/warnings,
document navigation and a pack selector in Ask. Keep existing corpus dashboards
and queries intact. Source links resolve through validated document/asset IDs,
not arbitrary filesystem paths supplied by clients.

## Safety and failure handling

Proposed configurable defaults: 50 MiB per file, 200 MiB expanded ZIP content,
2,000 pages/slides, 200,000 workbook cells, and one extraction worker with a
180-second document timeout. Fail with an actionable limit message rather than
silently truncating material. Upload and parser limits are checked before
indexing, including ZIP expansion and XML external-entity protections.

Generated paths must remain under the resolved study root on Windows. Validate
IDs and signatures rather than trusting extensions or filenames. Reject encrypted
documents requiring credentials and macro-enabled formats in this release.
Extraction/index failures preserve originals, report the affected document and
leave the prior usable index snapshot intact.
Serialize extraction/index promotion and purge per pack. Stop/cancel pending work,
block new readers, close file/index handles and wait for active request leases
before deleting. A failed purge remains pending and retryable, never reports
success or serves stale private snapshots. Study endpoints do not initialise the
core runtime, alter core manifests or load models during upload/preview.
Keep the server loopback-bound by default. Private pack endpoints reject browser
origins outside the configured local UI allowlist, despite the legacy core API's
wildcard CORS policy; uploaded material is not a network-sharing feature.

## Acceptance checks

- PDF/PPTX/XLSX/TXT/Markdown fixture extraction preserves locations, tables,
  notes, ordering, Unicode and blank-unit numbering; cached formulas are labelled.
- A query requiring two source units retrieves both with correct locators;
  repeated requests do not mutate cached scores or leak across packs.
- Citations to a wrong slide/page/cell or unsupported passage cannot qualify as
  grounded. Retrieval misses and unavailable semantic checks remain visible.
- Original-file and core-index checksums do not change after upload, indexing,
  failure, retry or document deactivation. Core API regression tests still pass.
- Test traversal/reserved filenames, duplicate bytes, malformed/encrypted files,
  ZIP expansion limits, interrupted jobs and not-ready/unknown packs.
- Test single-document packs with more than four useful passages, pack-only
  invented lecture acronyms, memory-policy leakage, neighbour expansion at both
  deeper levels, absent formula caches and purge during an active job/request.
- Upload/preview tests need no GPU, Ollama, model downloads or paid API calls.
  Run real hybrid/full-pipeline and manually checked book/deck questions later,
  when the user's GPU is available; unit tests do not prove answer accuracy.

## Pack evaluation, prepared before performance claims

Prepare a separate frozen 30-question bank, without editing the biology bank:
20 supported questions (including at least eight requiring multiple units) and
10 controls whose answers are common knowledge but absent from the pack. Keys
include expected units/locators and support/abstention expectations; the runtime
must never read these keys. Include an authored synthetic lecture fixture with
novel course-local names/values, clearly marked synthetic. A manually checked,
permitted real-textbook chapter remains future evaluation work. Private documents may still contain familiar
facts; the model's actual pretraining membership is not knowable from this test.

OpenStax Biology 2e chapter 6 was considered, then excluded: its current
attribution requires prior permission for AI ingestion in addition to its
CC BY-NC-SA 4.0 licence. No chapter was downloaded or used. The source manifest
records the exclusion; the frozen 30-question bank uses two original fictional
fixtures only. Any later external-source acquisition must be permitted, preserve
attribution and remain separate from the project's source licence; never fetch
it silently during ingestion. Report retrieval recall, multi-unit coverage, citation/locator correctness,
abstention and manually reviewed grounded accuracy separately. Run model-based
evaluation only after the user frees the GPU; do not optimise against the keys.

## Parser references

- [python-pptx notes](https://python-pptx.readthedocs.io/en/latest/user/notes.html)
- [python-pptx tables](https://python-pptx.readthedocs.io/en/stable/user/table.html)
- [openpyxl formula/cached-value loading](https://openpyxl.readthedocs.io/en/3.1/tutorial.html)
- [pypdf text-extraction limitations](https://github.com/py-pdf/pypdf/blob/main/docs/user/extract-text.md)
- [OpenStax Biology 2e preface and licence](https://openstax.org/books/biology-2e/pages/preface)
