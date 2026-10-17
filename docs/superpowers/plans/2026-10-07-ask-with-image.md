# Temporary Ask-with-Image Implementation Plan

Approved inline execution 2026-10-08 with the spec's one-click Ask and
question-aware amendment. It supersedes separate-click wording in Tasks 4–5:
the UI binds question/source/config intent, starts processing only on Ask,
waits for indexed evidence, then answers; errors/expiry/cancellation stop it.
Hosted/model-unload consent remain separate. Question context is bounded to
4,000 characters and is included in config/cache/provenance. Empty-question
figure-bank prompts are unchanged. No live GPU trial until separately authorised.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Inline execution is recommended to minimise token use; await the user's plan/execution approval. No commits or pushes.

**Goal:** Ask about a temporary image, optionally using one saved study pack as context, with honest image provenance, exact citations and reliable expiry/deletion.

**Architecture:** Extend existing pack storage with temporary retention and a small attachment lifecycle service. Reuse image extraction and explicitly started visual jobs; combine attachment/context index snapshots through a private composite searcher. Existing core and single saved-pack requests remain compatible.

**Tech Stack:** Existing Python/FastAPI/SQLite, Pillow, study BM25/dense/RRF/reranker pipeline, React/TypeScript/TanStack Query, unittest and Vitest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-07-ask-with-image-design.md` (approved 2026-10-07).

## Global Constraints

- Work in the current dirty checkout; preserve unrelated work. No commits or pushes.
- Do not change the original biology corpus, its indexes or benchmark banks.
- Do not run GPU inference, pull models or send private content to a hosted provider as part of implementation/testing. Use real safe asset/storage code and fake providers.
- Inherit existing 50 MiB upload, 25-million-pixel decode and single-frame PNG/JPEG validation limits, EXIF correction, sanitised previews and bounded worker decoding.
- Inherit provenance, numerical-verification restrictions, structured VLM schema, one normal call/one repair maximum, provider identity pinning and visible failures.
- Upload performs validation/extraction only. OCR/vision is an explicitly started job, and answering is a separate explicit action after usable evidence is indexed.
- Use existing local-origin protections, owned IDs, no-store responses and escaped previews. No arbitrary file paths, remote image fetching, generated-code execution, private browser localStorage/sessionStorage or private global trace persistence.
- One image, one optional saved context pack, 3,600-second absolute default expiry; deployment TTL range 300–86,400 seconds. Maximum 20 temporary packs; sweep every 60 seconds and on private-service startup.
- Reserve up to two nonempty attachment chunks inside the final passage/character budget. No usable attachment evidence means no image answer.
- VLM and answering run as separate explicit stages. No automatic model/provider switches, GPU retries or unrelated process/model unloading.

## Review Focus

1. An indexing worker holding an old Pack snapshot finishes after promotion: it must not restore temporary retention or an old name/deadline (Task 1).
2. Cleanup encounters an in-flight source stream or provider call: immediately deny new reads, return pending status without blocking the sweeper, then retry after release (Tasks 1–2).
3. UI navigation/removal races an upload response: a late server attachment must be deleted or left with bounded expiry, never mounted into the next question (Task 5).
4. Saved context is purged during/after image answering: deny publication/replay and clear browser state without deleting the image or the other saved pack (Tasks 3–5).
5. Temporary packs hidden from user lists become invisible to workers/restart recovery: enumerate them internally and keep automatic extraction/indexing and explicit visual resume working (Tasks 1–2).

## Preparation and file boundaries

The executor records a task checklist, runs read-only Git/workspace checks and follows applicable skill/user instructions. Do not create a worktree without consent: this feature depends on the existing uncommitted visual code. Do not stage or install anything as an automatic setup step. Run the relevant existing model-free study/visual tests as the baseline before product edits.

New files each have one responsibility:

- `aura_bio_system/src/aura_bio/study/attachments.py`: owned temporary upload, status, cleanup and promotion.
- `aura_bio_system/src/aura_bio/study/composite.py`: private two-pack retrieval and attachment evidence reservation.
- `aura_bio_system/src/aura_bio/api/study_attachments.py`: HTTP attachment adapters and lifecycle service access.
- `frontend/src/components/ask-image.tsx`: upload/preview, explicit processing and retention controls.

Modified areas: study schema/storage/jobs/runtime, existing visual jobs' lifetime guards, API run/cache/middleware/lifespan, pipeline's optional private evidence-selection hook, frontend types/API/run hook/AskPage and private trace guards. Do not broadly restructure these modules.

All Python commands below run from `G:\aura_llm` with existing project imports/dependencies configured; use the existing `.cache/verification-deps` overlay only if required. Fake-clock/fake-provider tests do not depend on Tesseract, Ollama, external keys or any GPU/model download.

---

### Task 1: Common retention guards and bounded purge

**Files:** Modify `aura_bio_system/src/aura_bio/study/{schema,storage,jobs}.py`, `aura_bio_system/src/aura_bio/study/visual/jobs.py`; create `aura_bio_system/tests/test_attachment_storage.py`.

**Interfaces:**

- Extend `Pack` with `retention: str = 'saved'`, `expires_at: float | None = None`, `lifecycle_schema: int = 1`.
- Extend `StudyStore.__init__(root: Path, limits: Limits | None = None, *, clock: Callable[[], float] = time.time)`.
- Extend `StudyStore.create_pack(name: str, domain: str = 'general', *, retention: str = 'saved', expires_at: float | None = None) -> Pack`; reject invalid retention/deadline combinations.
- `StudyStore.list_packs(*, include_temporary: bool = False) -> list[Pack]`; public default hides temporary packs; all ingestion/job lookup/recovery internals opt in.
- Internal `_pack_record(pack_id: str) -> Pack` reads validated catalog metadata for cleanup/migration only. Public `get_pack` and `assert_available` deny expired temporary data with `StudyError('attachment_expired', ...)`.
- `StudyStore.promote_pack(pack_id: str, name: str) -> Pack` atomically checks expiry/purge and updates retention/name under the existing lock. Ordinary `update_pack` preserves the latest lifecycle fields and promoted name from the catalog, rather than overwriting them from a worker snapshot.
- Extend `StudyStore.purge(..., confirmation: str, wait_seconds: float | None = None) -> PurgeResult`; None preserves existing behaviour. Zero records/blocks a pending purge and returns `deleted=False` if leased; it must not wait indefinitely or skip containment checks. Cleanup can read expired records internally, never through a public bypass.

- [ ] **Write failing tests:** legacy payloads default saved; deadlines never renew on access; expiry blocks originals/assets/search/jobs/start/resume/publication; default lists hide temporary packs while internal workers discover them. Saved packs never expire. `test_stale_index_update_cannot_undo_promotion` asserts saved/name/expiry-null after an old worker update. `test_expired_purge_with_reader_returns_pending_then_completes` asserts no blocked caller, denied new lease, retained leased bytes and subsequent deletion.
- [ ] **Verify RED:** `python -m unittest discover -s aura_bio_system/tests -p test_attachment_storage.py -q` fails for the missing lifecycle behaviours.
- [ ] **Implement interfaces:** guarded public reads plus narrow raw catalog access; migration defaults do not rebuild indexes. Ensure all final native/visual/index writes recheck lifetime, and safe metadata failure reporting does not resurrect purged records. Worker enumeration includes temporary packs and skips expired/purge-pending work cooperatively.
- [ ] **Verify GREEN and regressions:** rerun the new file and existing `test_study_storage.py`, `test_study_jobs.py`, `test_visual_jobs.py`. Assert no fake-provider invocation occurs merely from upload/list/access.

### Task 2: Owned attachment lifecycle and private HTTP API

**Files:** Create `study/attachments.py`, `api/study_attachments.py`, `tests/test_attachments.py`, `tests/test_attachment_api.py` under the existing package/test roots. Modify `api/{study_packs,app}.py` lifecycle, error mapping, private middleware and bounded-upload path matching.

**Consumes:** Task 1's retention-aware store, leases/purge/promotion; existing `add_document`, StudyJobs and visual/source routes.

**Produces:**

- `AttachmentService(store: StudyStore, *, clock: Callable[[], float] | None = None, ttl_seconds: int = 3600, invalidate: Callable[[str], None] | None = None)`; clock defaults to the store clock.
- `upload(filename: str, stream: BinaryIO) -> dict`: owned image-only Pack/Document/Job records. `status(attachment_id: str) -> dict`, `promote(attachment_id: str, name: str) -> Pack`, `delete(attachment_id: str) -> PurgeResult`, `sweep() -> list[dict]`, `start() -> None`, `stop() -> None`.
- Create catalog `image_attachments` records linking attachment/pack ID to exactly one document ID and safe cleanup status. Keep the record on promotion to resolve old references, remove it on completed purge. This distinguishes a promoted attachment from an arbitrary saved pack without altering source IDs.
- Status fields: `attachment_id`, `pack`, `document`, `job`, `usable`, `pending_cleanup`, `cleanup_error`; raw private exceptions never become error text. Usable requires an active nonempty indexed OCR/VLM/user-annotation revision, not merely an image asset or pack state.
- `POST /api/v1/study-attachments` (multipart file, 202); `GET /api/v1/study-attachments/{attachment_id}`; `POST .../{attachment_id}/save` with `{name}`; `DELETE .../{attachment_id}` with `{confirmation: attachment_id}`. Save returns the retained Pack. Delete rejects saved/promoted packs; detach does not delete saved material.
- Deployment variable `AURA_ATTACHMENT_TTL_SECONDS`, validated 300–86,400; invalid settings fail clearly, not silently. No client-controlled retention fields.

- [ ] **Write failing tests:** valid PNG/JPEG upload creates only hidden temporary ownership; disguised/multiframe/oversize/path names fail without orphan originals/catalog packs. A 21st temporary pack is rejected. Fake-clock restart sweep, failed cleanup retry, zero-wait pending reader, exact confirmation and save/expire lock-order races preserve other packs byte-for-byte. Saved/promoted attachment deletion is refused. Existing origin/middleware limits apply; 410 before cleanup/404 afterwards. Public IDs cannot bypass lifetime through regular study/visual APIs.
- [ ] **Verify RED:** run `test_attachments.py` and `test_attachment_api.py` individually using unittest discover.
- [ ] **Implement lifecycle/API:** hold ownership/quota lock through publication; rollback failed intake through the validated temporary target. Persist only bounded safe cleanup diagnostics. Sweep before worker recovery when private storage is first opened; start one stoppable 60-second sweeper, no sleeping inside requests. Do not open storage or models at unrelated API import. Shut down the sweeper before closing/replacing the store, without circular service initialisation.
- [ ] **Implement common private protection:** add the attachment prefix to no-store/nosniff/origin and multipart receive limits; map expired to 410 and quota/purge-pending to explicit safe errors. Reuse existing figure/crop/visual APIs, never duplicate providers or allow arbitrary uploaded hints from context packs.
- [ ] **Verify GREEN/regressions:** new files plus existing `test_study_api.py`, `test_visual_api.py`, `test_study_safety.py`, `test_visual_assets.py`; patch the core runtime/provider preflight to raise if an upload or GET calls them.

### Task 3: Composite retrieval and bounded primary-image evidence

**Files:** Create `study/composite.py`, `tests/test_attachment_retrieval.py`; modify `study/runtime.py`, `pipeline.py`, `api/mapping.py`; extend `tests/test_visual_grounding.py` and `tests/test_retrieval_isolation.py`.

**Consumes:** Task 1 store, existing StudySearcher/StudyEvidence, pack prompt/router/verifier, reranker and final evidence budget.

**Produces:**

- `CompositeStudySearcher(store: StudyStore, attachment_id: str, context_pack_id: str, *, dense_encoder: Any = None)` implements `search(query, top_k, candidate_k)`, `neighbors(hits, radius=1, limit=16)`, `close` and context-manager methods. Constructor closes earlier snapshots on later failure. Context must be a distinct saved, available, ready pack.
- Per-pack `generations: dict[str, int]`, `source_modes: dict[str, str]`, `runtime_warnings`, `pipeline_stages`; `generation` remains the attachment's integer for existing consumers, `mode` is sparse if both sparse, hybrid if both hybrid, mixed otherwise. Mapping displays mixed honestly rather than claiming BGE on every source.
- Merge each source's ranked results with equal-weight RRF `1/(60+rank)` using `(pack_id, chunk_id)` identities and deterministic ties. Never compare SQLite/dense raw scores across packs. Dense availability/model mismatch is reported per source; core runtime is not involved. Bound each source to the existing 200-candidate ceiling.
- `finalize_evidence(query: str, selected: Sequence[StudyEvidence], candidates: Sequence[StudyEvidence], *, max_passages: int, max_chars: int) -> list[StudyEvidence]`: put up to two highest-ranked nonempty attachment candidates first, deduplicate, then fill selected context within the supplied passage/character limits. Preserve locators/provenance when trimming. Reservation is not verified support.
- Add an optional searcher hook at the pipeline's existing evidence-selection boundary, only for pack-only requests. Use the full retrieved pool even if standard reranking truncates candidates. Attachment limits are `min(route.rerank_k, 6)` passages and 14,000 characters in either accuracy mode; existing non-attachment behaviour is unchanged.
- Extend `build_pack_pipeline(store, pack_id, *, use_critic=False, context_pack_id: str | None = None)`; `pack_id` is primary attachment when context is supplied. Reuse pack-only generation and verification, private trace root under the attachment, and no biology false-premise checks for general material.

- [ ] **Write failing tests:** real sparse pack indexes containing different keyed facts return correctly owned evidence from both, even with colliding manually constructed chunk IDs. Fake dense encoders plus actual index machinery expose mixed readiness accurately. Neighbours never cross source documents/packs; failed second-open closes the first. Standard/robust post-rerank selection retains attachment chunks within budgets, without exceeding passage limits. Empty attachment evidence blocks rather than returning context-only results.
- [ ] **Add grounding/control tests:** relevant native context may independently support a claim; unrelated native text cannot launder VLM-only claims or certify OCR/VLM numbers. Unsupported questions refuse; image-borne “ignore instructions” text remains untrusted. Outgoing prompts/providers never receive evaluator keys or unsolicited core passages.
- [ ] **Verify RED:** run `test_attachment_retrieval.py`, then the added named grounding/isolation tests.
- [ ] **Implement composition and private selector:** selection never marks reserved evidence native/verified. Close all snapshots and generator trace resources on failure. Keep hierarchy/decomposition dispatch through the composite neighbours contract, and preserve distinct source generations in traces/citation mapping.
- [ ] **Verify GREEN/regressions:** run the new tests plus existing study retrieval/reranking/pipeline and core retrieval-isolation tests with fake generators and CPU fixtures only.

### Task 4: Attachment-aware runs, expiry and source dependency invalidation

**Files:** Modify `api/app.py`, `api/mapping.py`, `api/study_packs.py`; create `tests/test_attachment_runs.py`.

**Consumes:** AttachmentService status, composite runtime, existing private run cache/SSE and purge invalidation.

**Produces:**

- RunRequestModel adds `attachment_id: str | None = None`, `context_pack_id: str | None = None`. An image run requires `evidence_scope='pack_only'`, `pack_id == attachment_id`; optional context is distinct and saved. Context without attachment, core+attachment, multiple/invalid IDs are rejected. Existing ordinary requests remain valid.
- `run_source_pack_ids(request: RunRequestModel) -> tuple[str, ...]` returns distinct sorted primary/context IDs. Persist `source_pack_ids` on private run metadata/summary and both generations on the private trace.
- Acquire source leases in sorted ID order using ExitStack for answer execution/publication and SSE/replay. Recheck all lifetimes/blocked states after generation and immediately before cache publication; do not publish a fresh result when expiry/purge wins. Never hold the global storage lock over inference.
- `forget_pack_runs(pack_id: str)` invalidates runs depending on either source; ordinary private runs remain covered. HTTP fetch/replay/list checks all dependencies rather than only request.pack_id.
- Require attachment usable status and no queued/running visual job before answer start; busy GPU blocks actual local inference visibly. No automatic model pull, swap or retry fallback. For attachment runs the configured local generator is exact and explicit; unavailable local model is a visible error, not a silent extractive substitute. An explicitly configured extractive generator remains allowed and labelled.
- External critique defaults off and is allowed only through this request's explicit `allow_external_critic`; disclosure covers both source sets, independent of hosted-vision approval.

- [ ] **Write failing tests:** fake generator advances clock or starts purge during execution; no run publication/history/SSE escapes. Purging saved context invalidates dependent runs without deleting attachment; removing attachment leaves saved context unchanged. Streams hold/release both leases and revalidate on events; duplicate/malformed IDs or context-alone requests fail. Provider job running, empty evidence, missing exact generator and busy local GPU return safe visible failures without invoking a fallback. Explicit extractive mode does not load/probe a GPU model.
- [ ] **Verify RED:** `python -m unittest discover -s aura_bio_system/tests -p test_attachment_runs.py -q`.
- [ ] **Implement guarded runs:** share dependency validation between create/read/list/replay; connect the expiry/delete invalidation callback to this helper. Keep private errors out of logs and private traces out of global stores. Adapt sparse/mixed trace labels without changing ordinary core mapping.
- [ ] **Verify GREEN/regressions:** rerun new file plus study API/visual grounding/pipeline tests. Fake-provider consent test proves global external-critic settings alone never permit an image request upload.

### Task 5: Ask-page image flow and safe browser lifecycle

**Files:** Create `frontend/src/components/ask-image.tsx` and `.test.tsx`; modify `frontend/src/{types.ts,lib/api.ts,hooks/use-run.ts,pages/AskPage.tsx,styles.css}`, associated tests and `lib/trace-store.test.ts`.

**Consumes:** HTTP attachment status/save/delete APIs, existing StudyVisualManager/StudySourcePreview, RunRequest attachment fields and dependency metadata.

**Produces:**

- Types: Pack retention/lifecycle fields; `ImageAttachment` mirrors Task 2 status; RunRequest attachment/context fields; private run `source_pack_ids`.
- `api.attachments.upload(file: File, signal?: AbortSignal) -> Promise<ImageAttachment>`, `.status(id)`, `.save(id, name)`, `.remove(id, confirmation)`. Add a typed `ApiError` retaining HTTP status/safe code for reliable 410/404 handling, without exposing raw response bodies. Keep current callers' Error.message behaviour compatible.
- `AskImage` props: `attachment: ImageAttachment | null`, `onChange`, `disabled`, `onUnavailable`; handles the upload, preview, deadline/status and save/remove controls. Reuse StudyVisualManager for explicit OCR/vision rather than rebuilding job logic. Only derive a blob preview from the selected file until the sanitised server preview is ready; revoke it on replacement/unmount. Uploaded original remains obtainable only through existing owned URLs.
- AskPage retains its selected saved pack as context when an attachment exists; submit sets primary `pack_id`/`attachment_id` to the attachment ID and optional `context_pack_id` to the selected saved pack. No attachment keeps the current core/single-pack request shape. Switching sources clears prior answer/citation state, not user-saved material.
- Show filename/original-image preview beside the submitted question, interpreted/transcribed badges, countdown and source-specific citation drawer. User annotations/figures are never presented as verified image truth. Promotion retains image/citation IDs but stops expiry; removing a promoted attachment only detaches it locally and never calls deletion.
- Explicit external-critic checkbox defaults false on attachment/context changes with both-source disclosure. Submit requires nonempty question, usable image evidence, ready optional context and no running visual job; generation status remains visible and cannot start from polling.
- `useRun` stores all private source dependencies in memory; purge/expiry from either source aborts and clears the active run. Keep private archives disabled even after attachment promotion. Never place image metadata, question, answers or blob bytes in localStorage/sessionStorage.

- [ ] **Write failing frontend tests:** upload does not start vision/answer; extraction/empty index blocks submit; explicit processing and original preview appear; correct combined request/consent; source change/purge/expiry clears output and drawer. Timer is absolute and paused network polling cannot extend it. Save preserves IDs and list refresh; remove after save never deletes retained material. Keyboard/file controls and narrow viewport do not overflow.
- [ ] **Add async race tests:** late successful upload after remove/navigation is not mounted; attempt bounded cleanup of the returned temporary ID and rely on server TTL if unreachable. Abort cannot guarantee the server never accepted bytes. Revoke blob URLs and clear relevant TanStack private query data; ignore stale polls and late run events by request/attachment identity. Invalid upload/410/404 has a specific visible safe message. Both-source purge clears useRun; trace-store spies prove no private archive writes.
- [ ] **Verify RED:** `npm --prefix frontend test -- src/components/ask-image.test.tsx src/pages/AskPage.test.tsx src/hooks/use-run.test.ts src/lib/trace-store.test.ts` fails for absent behaviours.
- [ ] **Implement using existing visual styles/components:** scoped styles only; no visual redesign or generated assets. After successful save, update status/list without silently persisting temporary answers or changing external permissions. Do not let a retained pack become an automatic delete target.
- [ ] **Verify GREEN/build:** rerun named tests, full `npm --prefix frontend test`, and `npm --prefix frontend run build`. Inspect desktop/narrow Ask UI using CPU synthetic fixtures; do not launch an actual provider job.

### Task 6: End-to-end model-free regression, documentation and review

**Files:** Create `aura_bio_system/tests/test_attachment_regressions.py`; update `docs/study-packs.md`, `frontend/README.md` only where the shipped flow needs instructions; update this plan's checkboxes and a compact execution ledger under `.superpowers/sdd/2026-10-07-ask-with-image/`.

**Consumes:** Tasks 1–5 and the approved design acceptance checklist.

- [ ] **Write/run RED integration controls before final fixes:** real image upload → CPU extraction → fake OCR/VLM revision → atomic sparse/fake-hybrid index → fake-generator question with saved context → exact image/text citations → save or expiry. Assert independent support labels, held IDs, clean restarts and no original-corpus writes. Failures cover busy GPU/429/unknown-timeout checkpoints, pending purge and missing optional engines without a silent provider/model switch.
- [ ] **Finish only in-scope fixes and rerun GREEN:** authored synthetic fixtures only; do not modify the frozen figure-bank prompts/keys to obtain better metrics. No private attachment content belongs in tracked fixtures or review artifacts.
- [ ] **Run fresh CPU verification:** all `test_attachment*.py`, relevant `test_study*.py`/`test_visual*.py`, then full `python -m unittest discover -s aura_bio_system/tests -q` only with model loaders patched/CPU-offline safe configuration. Existing tests must not opportunistically download or load GPU models; inspect the selected test setup first and report any excluded live integration cases explicitly. Run `python -m unittest discover -s corpus_pipeline/tests -p test_retrieval.py -q`, full frontend tests/build and `git diff --check`.
- [ ] **Document actual behaviour:** one image/one context pack, on-disk temporary storage, absolute TTL, deletion/pending errors, save-versus-detach, explicit processing/inference, separate hosted consent, interpreted numbers and unsupported refusal. Document deployment setting and fake test coverage separately from unmeasured live quality.
- [ ] **Request focused code review:** reviewer inspects only this feature's changed files/test evidence against the approved spec, particularly Review Focus and deletion targets. Do not include private source files, keys or unrelated dirty changes. Do not commit for review. Fix important findings with failing regression tests and fresh verification.
- [ ] **Handoff:** report completed code/test evidence and limitations; no claims of VLM accuracy, 4 GB fit or retrieval accuracy improvement. Provide the later GPU run as a safe optional next step, not an automatically started task. No commit/push.

## Plan self-review and execution gate

Reviewed against every approved design section: Task 1 covers migration/common
guards, Task 2 lifecycle/private API, Task 3 independent snapshots/evidence,
Task 4 dependency/privacy/resource enforcement, Task 5 UX/browser lifecycle,
Task 6 integration/docs/review. Each Review Focus input has an owning failing
test. Interfaces and IDs are consistent: attachment ID is its pack ID; one
registry-owned document; context stays separate and saved; promotion preserves
source IDs; delete never targets promoted or context material.

Execution completed inline after approval, with focused independent review and
regression fixes. The execution ledger is
`.superpowers/sdd/2026-10-07-ask-with-image/progress.md`; it records actual task
completion and verification rather than treating this original checklist as a
test-results log. Live model quality/4 GB fit remain unmeasured while the GPU is
occupied. The combined Windows backend test process hit a native access
violation; isolated-file coverage is reported separately, not as a full-suite
pass. No commits or pushes were made.
