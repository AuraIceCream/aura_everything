# Visual Study Packs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native implementation task-by-task. Subagent-driven-development is an alternative only if the user explicitly selects delegation. Steps use checkbox syntax. No commits or pushes.

**Goal:** Add image/figure understanding to isolated study packs without confusing model interpretation or OCR with independently verified evidence.

**Architecture:** Extend the existing modular study subsystem with bounded visual workers and provider adapters. Carry provenance across immutable index generations and claim-level checking; keep original images and interpretation revisions independently inspectable. Local text ingestion stays automatic; visual model jobs require explicit start.

**Tech Stack:** Existing Python dataclasses/SQLite/FTS5/FAISS/FastAPI, Pillow, pypdfium2, Tesseract TSV, Ollama HTTP, optional Groq HTTP; existing React/TypeScript/Vitest frontend and unittest backend.

**Spec:** [2026-10-07-visual-study-packs-design.md](../specs/2026-10-07-visual-study-packs-design.md)

**Status:** Approved and implemented in-place on 2026-10-07. Tasks 1–9 have code, regression coverage and documentation; final results are recorded in `docs/study-packs.md` and the ignored execution ledger. No commits/pushes, live VLM/Groq quality run or private hosted uploads. Native execution and author self-review were used; no independent agent was dispatched.

### Execution summary

- [x] Four-method provenance contracts and frozen 20-figure/40-question synthetic bank.
- [x] Safe image intake, PDF page rendering, crop/rotation transforms and source-region selection.
- [x] Explicit OCR/vision jobs, immutable revisions, checkpoints, cancellation and manual resume.
- [x] One-call structured descriptions, bounded repair, isolated transport deadlines and fixed local/hosted providers.
- [x] Provenance-preserving retrieval/citations and non-circular numeric/semantic checking.
- [x] Private API, source/crop/annotation controls, durable job history and desktop/mobile inspection.
- [x] Evaluation harness, documentation and offline regression verification.
- [ ] Separately authorised live VLM quality/GPU-fit evaluation and manual review (not part of code implementation).

The detailed task checklists below preserve the original test-first work orders,
including illustrative test names. They are not a second pending implementation
queue: actual test names, RED/GREEN evidence and limitations are in the execution
ledger. Coverage was consolidated rather than creating every illustrative test
as a separate function.

## Global Constraints

The linked spec is normative. Its Global constraints apply to every task unchanged:

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

## Review Focus

1. A 200-slide deck repeats logos and a scientifically useful diagram: deduplicate pixels/calls, retain occurrences, expose exclusions and manual overrides (Tasks 3, 5, 8).
2. A VLM invents labels, or copies misleading OCR/caption hints: schema validation must not certify content and native neighbours must not launder unsupported claims (Tasks 1, 6, 7).
3. GPU becomes busy/OOM, provider returns 429, or the server restarts after a completed figure: preserve checkpoints/indexes, require explicit resume, never switch models (Tasks 5, 6).
4. A rotated PDF/manual crop changes geometry: correct source region must be highlighted; reject cross-pack/out-of-bounds references (Tasks 2, 3, 8).
5. Purge/deactivation races a visual job or annotated revision: stop stale writes and remove all local private derivatives without touching other packs/corpus (Tasks 5, 8, 9).

## Requirement-to-task map

| User requirement | Implemented by | Proof |
|---|---|---|
| Four-method provenance through verifier/citations; no VLM self-verification | 1, 7, 8 | Round-trip, high-scoring fake-NLI self-verification and mixed-source regressions |
| Rendered regions and manual crops | 2, 3, 8 | Prose-heavy vector-only PDF and rotated/manual-crop fixtures |
| One structured call, schema validation, bounded repair | 6 | Normal=1 call; invalid response<=2 calls; visible failure |
| Explicit start/checkpoints/failures/no silent switch | 5, 6, 8 | No inference during upload; restart/OOM/429/digest-change fixtures |
| Per-page timeout replacing 180-second OCR document limit; unverified OCR numbers | 4, 5, 7 | Fake clock >180 seconds total; page timeout; conditional numeric checks |
| Frozen figure bank before tuning | 1, 9 | Source/bank/split hashes; holdout isolation and gold leakage tests |

## File and interface map

Create focused modules under `aura_bio_system/src/aura_bio/study/visual/`:
`schema.py` (visual records), `assets.py` (decode/render/geometry), `selection.py`
(candidates/crops), `ocr.py` (TSV adapter/page policy), `storage.py` (immutable
derived revisions/checkpoints), `jobs.py` (explicit scheduler), `description.py`
(JSON contract/one-call orchestration), `ollama.py`, `groq.py`, `evaluation.py`.
Keep the new `study/provenance.py` independent of providers. Existing native
`study/storage.py` delegates visual ownership/lifecycle rather than growing a
second unrelated database. Every visual table lives in pack metadata SQLite.

Shared records (exact names; define them in Tasks 1–2 before consumers):

- `SourceMethod`: `native_text | ocr | vlm | user_annotation`.
- `ProvenanceDetails`: source unit, asset/figure/revision IDs, content checksum and method-specific metadata; no secrets or external paths.
- `ClaimBasis`: claim index, supporting provenance records, `verification_kind` and `inputs_verified` boolean.
- `NormalizedBox`: `(x0,y0,x1,y1)` in the spec's upright coordinate frame.
- `SourceTransform`: original dimensions/units, rotation, render dimensions/scale and crop offset; `to_display(box) -> NormalizedBox`, `to_original(box) -> tuple[float,float,float,float]`.
- `RenderedAsset`: owned asset ID, dimensions, checksum, transform and safe preview MIME.
- `FigureCandidate`: immutable figure ID, parent unit/asset/document IDs, locator/bbox/frame, selection reason, optional exclusion reason and context hash.
- `OcrResult`: raw text, word text/boxes/confidence, engine/language/version, transform, warnings.
- `VisualJobConfig`: frozen provider/model identity, source/crop/OCR/context/prompt hashes, timeouts, resource and token/figure budgets, explicit consent record; no API key.
- `VisualCheckpoint`: job/item ID, source/config hashes, state, attempts, result revision, safe error, timestamps and optional resume time.
- `FigureInput`: candidate, owned image bytes, marked OCR/caption hints and config.
- `ProviderResponse`: raw text, actual provider/model identity, token usage and timing; no schema-validation or retry side effects in adapters.
- `FigureDescription`: validated structured fields, raw response, actual provider/model identity, prompt/config hashes, usage and timing.

Every task uses RED -> GREEN -> targeted regression verification. Capture a real
failing assertion, not just a runner failure. Leave all changes uncommitted; record
completion in an ignored execution ledger. Execution is now recorded under
`.superpowers/sdd/2026-10-07-visual-study-packs/`.

For CPU/offline regression commands from `G:/aura_llm`, reuse the installed runtime:

```powershell
$env:PYTHONPATH = 'G:/aura_llm/.cache/study-deps;G:/aura_llm/.cache/verification-deps'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:AURA_DEVICE = 'cpu'
$env:AURA_NLI_DEVICE = 'cpu'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:USE_TF = '0'
$env:AURA_STUDY_INDEX_MODE = 'sparse'
```

Hybrid-specific tests supply fake CPU encoders or explicit cache-only test settings.
Use fake clocks/backends to test timeouts, GPU states and provider limits; unit tests
must not accidentally start an answering/VLM model or upload a private image.

### Task 1: Provenance contracts and frozen evaluation foundation

**Files:** Create `study/provenance.py`, `study/visual/__init__.py`, `study/visual/schema.py`, `benchmarks/figure_bank.py`, `benchmarks/figure_fixtures/`, `benchmarks/figure_bank.jsonl`, `benchmarks/figure_sources.json`; modify `study/schema.py`; test `tests/test_study_provenance.py`, `tests/test_figure_bank.py` (all backend paths relative to `aura_bio_system/`). Paths beginning `study/` resolve under `src/aura_bio/`; `tests/` and `benchmarks/` resolve under `aura_bio_system/`.

**Interfaces:** Produce `SourceMethod`, `ProvenanceDetails`, `ClaimBasis`, visual records listed above, and evaluator-only `benchmarks/figure_bank.py::validate_figure_bank(bank_path: Path, manifest_path: Path) -> dict`. Append provenance fields to `Unit`/`StudyChunk`; old valid native records load unchanged.

- [ ] Write failing tests: `test_four_provenance_values_roundtrip` asserts the exact four values and rejects others; `test_legacy_native_units_load_without_derived_promotion` accepts old native units but rejects a missing-method derived role.
- [ ] Write `test_figure_bank_frozen_before_prompt_tuning`: assert 20 figures, 40 questions, 24 development/16 held-out questions on disjoint 12/8 figures, hashes for every source/bank/split, and label/relationship/value/absent counts 16/12/6/6. Alter a temporary bank/source and assert validation fails.
- [ ] Run `python -m unittest discover -s aura_bio_system/tests -p test_study_provenance.py -v` and the same command with `test_figure_bank.py`; observe failing assertions/imports before implementation.
- [ ] Implement records and safe legacy defaults. Author deterministic teaching figures and independently keyed controls, including misleading hints and vector drawings; keep private supplied material out of tracked fixtures. Freeze/hash them before Task 6 prompt work. An executor may not proceed to Task 6 with an unfrozen bank.
- [ ] Re-run both suites; expect PASS. Record the frozen manifest digest in the ledger, not in serving prompts.

### Task 2: Safe image intake, PDF rendering and invertible geometry

**Files:** Create `study/visual/assets.py`, `study/extractors_image.py`; modify `study/validation.py`, `study/extractors.py`, `study/extractors_pdf.py`, `study/schema.py`, `aura_bio_system/pyproject.toml`; test `tests/test_visual_assets.py`, existing extraction/safety tests.

**Interfaces:** `decode_image(path: Path, limits: Limits) -> RenderedAsset`; `render_pdf_page(path: Path, page: int, limits: Limits) -> RenderedAsset`; `extract_pdf_page(path: Path, document: Document, page: int, limits: Limits) -> Unit`. Produce the shared `SourceTransform`; no model calls.

- [ ] Write RED tests for `test_decompression_bomb_rejected` (>25M pixels), `test_signature_mismatch_rejected`, `test_multiframe_rejected`, `test_exif_rotation_applied`, and `test_bbox_roundtrips_through_transform` (0/90/180/270 degrees, error<=1 original pixel or point). Assert 200-DPI/12M-pixel ceilings and unchanged original checksum.
- [ ] Run `python -m unittest discover -s aura_bio_system/tests -p test_visual_assets.py -v`; observe RED.
- [ ] Implement page-at-a-time rendering/decode in bounded workers, signature checks, sanitised derivative metadata and original retention. Introduce per-page native PDF extraction; preserve old whole-document function for compatible direct tests but do not wrap the new PDF/OCR worker in its 180-second deadline. Declare optional visual dependencies without installing them.
- [ ] Re-run assets plus `test_study_extraction.py`/`test_study_safety.py`; expect PASS. Missing renderer yields an actionable error, never false OCR/vision readiness.

### Task 3: Figure discovery and manual source crops

**Files:** Create `study/visual/selection.py`; modify `study/extractors_pptx.py`; test `tests/test_figure_selection.py`.

**Interfaces:** `select_figures(units: list[Unit], assets: list[RenderedAsset], *, limit: int) -> list[FigureCandidate]`; `create_crop(candidate: FigureCandidate, bbox: NormalizedBox) -> FigureCandidate`. PDF drawing/caption-region extraction uses Task 2 rendering; PPTX manual crops target embedded image assets, not fictional full-slide renders.

- [ ] RED: `test_vector_figure_on_text_heavy_page_selected`, `test_manual_crop_validated_in_source_frame`, `test_repeated_logo_skipped`, `test_repeated_diagram_keeps_all_occurrences`, `test_text_only_page_not_sent`, `test_uncertain_region_exposes_manual_page_candidate`. Assert retained source/page/slide/shape locators, visible skip reasons and manual override.
- [ ] Run `python -m unittest discover -s aura_bio_system/tests -p test_figure_selection.py -v`; observe RED.
- [ ] Implement embedded-image and drawing/caption-anchored region candidates with conservative whole-page/manual fallback. Preserve panels/legends; deduplicate asset bytes while retaining occurrence/context identity. Do not exclude a page solely for high text density. Enforce spec budgets without silently hiding uncovered figures.
- [ ] Re-run selection/assets/extraction suites; expect PASS including a 200-slide repeated-logo fixture with no model calls.

### Task 4: Per-page OCR with visible transcription uncertainty

**Files:** Create `study/visual/ocr.py`; modify `study/extractors_pdf.py`, `study/jobs.py`, `study/schema.py`; test `tests/test_visual_ocr.py`.

**Interfaces:** `needs_ocr(native_text: str) -> bool`; `TesseractOcr.read(asset: RenderedAsset, *, language: str, timeout_seconds: float) -> OcrResult`; `ocr_unit(parent: Unit, result: OcrResult) -> Unit` sets `provenance=ocr` and immutable revision metadata. Task 5 consumes this adapter.

- [ ] RED: `test_garbage_text_layer_triggers_ocr`, `test_greek_and_gene_labels_do_not_trigger_garbage_rule`, `test_page_timeout_is_bounded`, `test_tsv_boxes_and_confidence_preserved`, `test_missing_language_or_engine_fails_visibly`, `test_ocr_numbers_marked_unverified`.
- [ ] Run `python -m unittest discover -s aura_bio_system/tests -p test_visual_ocr.py -v`; observe RED.
- [ ] Implement TSV parsing and bounded subprocess cancellation; default 60 seconds/page, range 5–300. Retain native/raw OCR separately; support explicit forced OCR. No dictionary guessing or confidence-to-truth conversion. Split existing PDF processing into page steps so the parent document's 180-second timeout cannot terminate it.
- [ ] Re-run OCR/extraction/jobs suites; expect PASS. Add a separately labelled real installed-Tesseract CPU smoke test using a project-authored image; skip visibly if absent, and never represent fake TSV tests as OCR quality results.

### Task 5: Immutable revisions, explicit jobs and checkpoints

**Files:** Create `study/visual/storage.py`, `study/visual/jobs.py`; modify `study/storage.py`, `study/jobs.py`; test `tests/test_visual_jobs.py`, `tests/test_visual_storage.py`, existing purge/restart tests.

**Interfaces:** `VisualStore.upsert_checkpoint(checkpoint: VisualCheckpoint) -> None`; `publish_revision(unit: Unit, *, expected_source_hash: str) -> str`; `activate_revision(figure_id: str, revision_id: str) -> None`; `VisualJobs.start(pack_id: str, figure_ids: list[str], config: VisualJobConfig) -> Job`; `pause(job_id: str)`, `cancel(job_id: str)`, `resume(job_id: str, config: VisualJobConfig) -> Job` and `run_once() -> bool`. Use existing pack metadata/leases; no global private database.

- [ ] RED: `test_upload_does_not_start_vlm`, `test_ocr_job_can_exceed_180_seconds_total` (four fake-clock pages, each 50 seconds), `test_crash_resumes_after_last_completed_item`, `test_changed_digest_requires_new_job`, `test_partial_results_keep_previous_index`, `test_purge_rejects_late_checkpoint`, `test_deactivate_cancels_queued_work`, `test_annotation_revision_survives_redescribe`.
- [ ] Run `python -m unittest discover -s aura_bio_system/tests -p test_visual_jobs.py -v` plus `test_visual_storage.py`; observe RED.
- [ ] Implement short per-item/publish leases, immutable revisions/checkpoints and frozen job snapshots. Retain native extraction: do not append via destructive `publish_extraction`. Restart marks unfinished work interrupted, not automatically resumed. Timed-out pages/figures are visible failures; explicit retries retain successes. Publish/queue atomic indexes on completion or explicit pause/cancel with partials.
- [ ] Enforce byte/figure budgets and distinguish visual-only/partial/ready states. Extend deactivation/purge to every visual artifact and cached answer. Assert one job cannot process another pack's IDs.
- [ ] Re-run visual jobs/storage plus `test_study_jobs.py`, `test_study_storage.py`, `test_study_safety.py`; expect PASS, with no fixture deletion outside temporary roots.

### Task 6: One-call structured descriptions and fixed providers

**Files:** Create `study/visual/description.py`, `study/visual/ollama.py`, `study/visual/groq.py`; test `tests/test_figure_description.py`, `tests/test_vision_providers.py`.

**Interfaces:** `VisionBackend.complete(input: FigureInput, *, repair: str | None, timeout_seconds: float) -> ProviderResponse`; `OllamaVisionBackend`/`GroqVisionBackend` implement this raw-response protocol. `FigureDescriber(backend: VisionBackend).describe(input: FigureInput, *, timeout_seconds: float) -> FigureDescription` owns one-call orchestration and the single allowed repair; `validate_description(raw: str) -> dict` lives in `description.py`. `VisualJobs` consumes the common describer; test injection uses fake HTTP/backends.

- [ ] Confirm Task 1's frozen manifest before creating/tuning any prompt. RED tests assert valid output=1 provider call; malformed output<=2 calls; second malformed output fails visibly; limits 64 labels/4 axes/64 relations/32 uncertainties/1,500 summary chars/64KiB raw response. Assert labelled hint text cannot be promoted to an observed label by validation alone.
- [ ] Add RED provider tests: `test_vlm_absent_leaves_native_pack_usable`, `test_busy_gpu_defers_without_switch`, `test_oom_preserves_checkpoint`, `test_429_pauses_for_explicit_resume`, `test_hosted_requires_crop_and_hint_consent`, `test_no_provider_or_model_fallback`, `test_secrets_excluded_from_records`, `test_unknown_timeout_not_automatically_reuploaded`.
- [ ] Run discovery for `test_figure_description.py` and `test_vision_providers.py`; observe RED.
- [ ] Implement one combined classification/description prompt, strict schema validation and at most one same-provider/model structural repair. Disable tools/URL fetching; require uncertainty for unreadable content. Record raw response, identity/digest where available, prompt/config/source hashes and every attempt/usage.
- [ ] Local adapter defaults to configured installed `qwen3.5:4b`, pinned at explicit start; preflight capability/availability and resource permission. Use spec pixel/context/output/time limits. Unloading AURA's generator requires explicit managed-swap approval; never touch unrelated models/apps.
- [ ] Groq adapter reads `GROQ_API_KEY` only at request time, sends approved owned bytes/hints, JSON mode/thinking off, default 50,000-token job budget, headers/usage-aware pause. Missing key/model/permission is visible failure, not local fallback. Do not hardcode free-tier quotas or claim an opaque hosted digest.
- [ ] Re-run both fake-provider suites; expect PASS. No live Ollama generation/Groq requests in unit tests; these results do not establish figure quality or 4GB fit.

### Task 7: Provenance-preserving retrieval and non-circular verification

**Files:** Modify `study/chunking.py`, `study/indexing.py`, `study/searcher.py`, `study/prompts.py`, `study/verification.py`, `study/runtime.py`, `aura_bio_system/src/aura_bio/generation/selection.py`, `aura_bio_system/src/aura_bio/api/mapping.py`; test `tests/test_visual_grounding.py`, existing study pipeline/retrieval/reranking tests.

**Interfaces:** Homogeneous-method chunks retain provenance plus per-span details. `StudyEvidence` carries these unchanged. `StudyReport` exposes `claim_basis: list[ClaimBasis]`; pack-only `as_dict()` enriches claims/citations, while core API output stays unchanged. `verification_kind` is `native_verified | native_unverified | ocr_transcribed | interpreted | user_annotated | unsupported`.

- [ ] RED: `test_provenance_survives_index_search_citation_roundtrip`, `test_chunks_do_not_merge_methods`, `test_vlm_passage_never_verifies_itself` (fake NLI returns 1.0), `test_unrelated_native_passage_does_not_launder_figure_claim`, `test_independent_native_support_can_verify`, `test_native_lexical_fallback_not_certified`, `test_figure_only_answer_delivered_interpreted_not_refused`, `test_ocr_number_not_certified`, `test_calculation_preserves_unverified_inputs`, `test_gene_label_digit_not_measurement`, `test_user_edit_not_promoted`, `test_old_native_generation_readable`.
- [ ] Run `python -m unittest discover -s aura_bio_system/tests -p test_visual_grounding.py -v`; observe RED.
- [ ] Add manifest migration and revision-aware active indexing. Keep same CPU BM25/dense/RRF/reranker/selection path and original source text. Missing/invalid provenance on unexpected derived records fails closed.
- [ ] Extend pack prompts with `[model-described figure]`, `[OCR transcription]`, `[user annotation]` distinctions. Native passages only verify claims they independently support; non-native-only claims remain UNVERIFIABLE with explicit basis, not SUPPORTED through NLI agreement. Correctly labelled interpretations return degraded; true unsupported claims still revise/refuse. Separate interpreted coverage from native grounding and keep candidate ranking from dropping all useful interpretations merely to chase native coverage.
- [ ] Conditional arithmetic may be checked without certifying visual inputs. Prevent biology tools/critic from laundering them. Map any delivered non-native claim to an interpreted/transcribed/annotated UI status, never verified. Core-corpus behaviour and response shapes remain unchanged.
- [ ] Re-run visual grounding, study pipeline/retrieval/reranking and core pipeline/API suites; expect PASS with all four provenance methods intact in private traces.

### Task 8: Private API, visual management and source citation UI

**Files:** Create `aura_bio_system/src/aura_bio/api/study_visual.py`, `frontend/src/components/study-figure.tsx`, `frontend/src/components/study-crop.tsx`; modify API `app.py`/`study_packs.py`, frontend `types.ts`, `lib/api.ts`, `pages/StudyPacksPage.tsx`, `components/study-source.tsx`, `components/quality-panels.tsx`, `styles.css`; test `tests/test_visual_api.py`, frontend `StudyPacksPage.test.tsx`, `study-figure.test.tsx`, `study-crop.test.tsx`.

**Interfaces:** Under `/api/v1/study-packs/{pack}/documents/{doc}`, `GET /figures`, `POST /figures/crops`, `GET /figures/{figure}/revisions`, `POST /figures/{figure}/annotations`. Under `/api/v1/study-packs/{pack}`, `POST /visual-jobs` (explicit selected IDs/config/consent), `GET /visual-jobs/{job}`, `POST /visual-jobs/{job}/pause|cancel|resume`. Existing owned asset routes serve previews; no arbitrary paths/remote fetches. Add provenance/basis/frame/revision fields to study frontend types only.

- [ ] RED API tests assert invalid/cross-pack IDs, crop bounds, origin checks, no-store bytes, explicit permission, secrets absent, job failures and original checksum preservation. Add temporary-fixture purge assertions covering images/OCR/raw output/annotations/checkpoints/history and race/restart recovery.
- [ ] RED UI tests assert Start visual pass is explicit; missing/busy model is visible; hosted payload disclosure and permission; figure progress/retry; escaped malicious description; manual crop keyboard/numeric controls; rotated highlights; OCR confidence/model-described/user-edited badges; immutable old citation preview after edit; no browser localStorage/private remote image requests.
- [ ] Run backend `test_visual_api.py`; frontend `npm run test -- --pool=threads --maxWorkers=1`; observe actual failing assertions before implementation.
- [ ] Implement API/UI using Tasks 2–7 interfaces. Show exclusions/partial coverage and one worker's actual stage. User annotation creates its own revision; re-describe preserves it. Source drawer shows upright original/crop plus correct bbox, method/model and uncertainty. Do not draw highlights when coordinates are unknown. No fabricated pixel-perfect PPTX rendering.
- [ ] Re-run backend/frontend tests and `npm run build` in `frontend`; expect PASS. Inspect desktop/mobile crop and citation screens with the existing browser runtime; do not install a browser or expose a network service silently.

### Task 9: Evaluation harness, integration checks and handoff

**Files:** Create `study/visual/evaluation.py`, `benchmarks/run_figure_eval.py`, `tests/test_figure_evaluation.py`; modify `docs/study-packs.md`, `aura_bio_system/README.md`, `frontend/README.md` only where needed for visual setup/status.

**Interfaces:** `evaluate_figure_run(records: list[dict], bank: list[dict]) -> dict`; CLI consumes frozen bank/manifest/config hashes and explicit pack/model/provider flags. Outputs go only to pack-owned `traces/evaluation`. Serving/provider code cannot import gold keys.

- [ ] RED tests assert manifest mismatch rejects resume; completed/error/review denominators remain honest; unreviewed relation/answer metrics are null; hallucinated labels count as errors; unsupported controls require abstention; numeric certification violation count is independent of value-reading accuracy; dev/holdout isolation; no gold leakage.
- [ ] Run `python -m unittest discover -s aura_bio_system/tests -p test_figure_evaluation.py -v`; observe RED.
- [ ] Implement label recall, hallucinated-label rate, relation accuracy, unsupported abstention, locator/crop correctness, certification violations, latency/memory/token usage and manual-review reporting. Keep original outputs when rescoring. Frozen development/holdout splits precede prompt tuning; later real OCR-hint on/off and local/Groq comparisons require separate compute/privacy approval and are not unit tests.
- [ ] Document installed-dependency discovery, limits, explicit starts, failure/resume, provenance meanings and remote-retention caveat. Missing dependencies remain actionable; no install/download side effects. Old native-pack workflows remain supported.
- [ ] Run backend `python -m unittest discover -s aura_bio_system/tests -q`; corpus retrieval `python -m unittest discover -s corpus_pipeline/tests -p test_retrieval.py -q`; frontend single-worker tests/build; `git diff --check`. Expect zero failures; record counts/warnings and unavailable smoke checks truthfully. Use CPU/offline cache settings for regressions, not a real answering/VLM benchmark.
- [ ] Check original corpus/banks untouched and all private visual files inside packs. Self-review against the six-row map and five Review Focus cases; request independent review only if separately authorised. Link verification records and leave the dirty checkout uncommitted.

## Later milestones — deliberately not executed under this plan

- **Ask-with-image:** after Tasks 1–9, design ephemeral ownership/expiry and explicit model swap. Reuse `FigureDescriber` plus provenance-aware pack retrieval; an image is not a verified fact. No implicit retention or hosted upload. This needs its own short spec/plan before code.
- **Visual retrieval:** evaluate page-image embeddings only if the frozen bank shows caption/description retrieval misses; do not add a second retrieval stack pre-emptively.
- **Visual output:** source annotations first, then safe Mermaid/SVG and verified-data charts. Never execute arbitrary LLM Python/JS. Generated illustrations stay conceptual, not evidence.

## Review and execution handoff

The linked design was approved and executed natively, task-by-task, because the
interfaces share pack lifecycle/provenance and the user requested minimal token
usage. Source changes and regression results are recorded in the execution ledger.
Real GPU inference, a different model download and hosted private uploads remain
separate explicit approvals even after code execution is approved.
