# Document-aware study packs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Native implementation is recommended; do not spawn agents without authorisation.

**Goal:** Ingest local course documents, preserve their structure and answer through the existing pipeline using only a selected pack, with inspectable citations and real deletion.

**Architecture:** A separate `aura_bio.study` store owns originals, SQLite units, immutable search generations and private traces. Format adapters and a pack searcher feed the existing pipeline through an explicit pack-only policy. Core requests retain their current routing, prompts, stores and defaults.

**Tech Stack:** Python >=3.11, SQLite/FTS5, existing pypdf/BGE/FAISS, optional python-pptx/openpyxl/python-multipart/defusedxml, FastAPI, React/TypeScript, unittest/Vitest.

**Spec:** `docs/superpowers/specs/2026-10-06-study-pack-ingestion-design.md`

## Execution status — 2026-10-06

- [x] Tasks 1–4: isolated storage, real format extraction, immutable retrieval generations, bounded jobs and retryable confirmed purge.
- [x] Tasks 5–6: strict pack-only orchestration, general/biology adapters, API and private source previews.
- [x] Tasks 7–8: study-material UI, frozen 30-question authored bank, evaluation harness and setup documentation.

The detailed checklists below preserve the approved implementation recipe, not a
claim that every original instruction was followed unchanged. The execution
ledger at `.superpowers/sdd/2026-10-06-study-pack-ingestion/progress.md` records
actual tests, deviations and final results. Initial frontend RED assertions were
not observed because the runner failed to start; later security/regression tests
did exercise RED→GREEN. OpenStax was excluded after checking its AI-use terms.
No independent agent review, inference benchmark, training, commit or push ran.

## Global Constraints

- Work in the existing dirty checkout; preserve unrelated edits. No commits or pushes.
- Original biology corpus, indexes, paths, benchmark banks and default query behaviour remain unchanged.
- No GPU jobs, model downloads, inference benchmarks, external search or training during this implementation pass. Dependency installation, if needed, is reported separately; missing optional parsers produce actionable errors.
- Default root is `G:/aura_llm/.local/study-packs`, overridden by `AURA_STUDY_ROOT`. Add `.local/` to Git ignore before any private file is stored. Reject roots overlapping core corpus/index roots.
- Formats: PDF, PPTX, XLSX, TXT/Markdown. No legacy PPT/XLS, DOCX, OCR, visual interpretation or automatic exhaustive study-guide generation.
- Limits: 50 MiB/file, 200 MiB expanded ZIP, 2,000 pages/slides, 200,000 workbook cells; one extraction worker, 180-second document timeout. Fail rather than silently truncate.
- Extraction/preview use no Ollama, external API, GPU or core runtime initialisation. Dense indexing is explicit, CPU/cache-only in this pass; sparse-ready and hybrid-ready remain distinct.
- `evidence_scope=core` stays the default; selected packs use `pack_only`. No implicit core fallback, memory enrichment or uploaded-instruction execution.
- Pack selection keeps passage/prompt budgets, relevance and deduplication, but disables both source and document count caps. Neighbours come from the pack SQLite.
- Private traces stay inside their pack and are not browser-archived. Hard purge requires explicit target confirmation and cannot promise forensic removal from backups/SSDs/user exports.
- Private endpoints are local-only: keep the server's loopback default and reject foreign browser origins. Default UI allowlist covers localhost/127.0.0.1 ports 5173, 4173 and 8000; `AURA_STUDY_ALLOWED_ORIGINS` can explicitly override it. Core CORS behaviour is outside this change.
- Tests use temporary packs, fake models and fake embeddings. Full existing suites may load cached CPU models offline; defer real model evaluation until the GPU is free.

## Review Focus

1. A single deck needs five distinct slides: no four-passage source cap or two-passage document cap (Task 5).
2. Generic facts absent from a pack and plausible invented acronyms: no memory answer or biology false-premise correction (Tasks 5, 8).
3. Formula cells have no cached values, and short units merge: preserve formula text and every contributing locator (Tasks 2, 3).
4. Purge races a worker, query or SSE replay: no stale private files, snapshots or cached answers become available after successful purge (Tasks 4, 6, 7).
5. A crash interrupts indexing or a PDF has no usable text: retain the old generation and report interruption/OCR-required, never ready with incomplete coverage (Tasks 2, 4).

## File boundaries and interfaces

New backend modules are under `aura_bio_system/src/aura_bio/study/`: `schema.py` (records), `storage.py` (persistence/path lifecycle), `validation.py` (bounded container checks), `extractors.py` (adapter dispatch), `extractors_pdf.py`, `extractors_pptx.py`, `extractors_xlsx.py`, `extractors_text.py` (format structure), `chunking.py`, `indexing.py`, `searcher.py`, `jobs.py`, `routing.py`, `prompts.py`, `verification.py`, `runtime.py` (scoped pipeline factory). Include `__init__.py` without eager parser/model imports.

Storage types are defined in Task 1, extraction types in Task 2 and `StudyEvidence` in Task 3. Only Task 5 changes shared orchestration; Tasks 6 and 7 expose the tested backend, and Task 8 establishes evaluation artefacts. All paths below are relative to `G:/aura_llm`.

### Task 1: Isolated storage and lifecycle records

**Files:** Create `study/schema.py`, `study/storage.py`, `study/validation.py` under the backend directory above; create `aura_bio_system/tests/test_study_storage.py`; modify `.gitignore` and `aura_bio_system/pyproject.toml`.

**Interfaces:** Define frozen `Limits`, `Pack(pack_id, name, domain, created_at, generation)`, `Document(document_id, pack_id, filename, checksum, kind, active, state, warnings)`, `Job(job_id, pack_id, document_id, state, error)` and `PurgeResult(pack_id, document_id, deleted, invalidated_history)`. `domain` is `general|biology`, default `general`; IDs are UUID hex, filenames are display metadata only. `StudyStore(root: Path, limits: Limits)` exposes `create_pack(name: str, domain: str = 'general') -> Pack`, `list_packs() -> list[Pack]`, `get_pack(pack_id: str) -> Pack`, `add_document(pack_id: str, filename: str, stream: BinaryIO) -> tuple[Document, Job | None]`, `documents(pack_id: str) -> list[Document]`, `job(job_id: str) -> Job`, `deactivate(pack_id: str, document_id: str) -> Job` and `close() -> None`. Duplicate active bytes return the existing document without a new extraction job. Define `StudyError(code: str, detail: str)` and centralise validated contained paths.

`Limits` fields: `max_upload_bytes=50*1024**2`, `max_expanded_bytes=200*1024**2`, `max_pages_or_slides=2000`, `max_workbook_cells=200000`, `workers=1`, `timeout_seconds=180`.

Primary contract test (test setup provides a temporary store/pack):
```python
def test_duplicate_bytes_do_not_enqueue_again(self):
    first, _ = self.store.add_document(self.pack.pack_id, 'lesson.txt', BytesIO(b'Lesson'))
    second, job = self.store.add_document(self.pack.pack_id, 'copy.txt', BytesIO(b'Lesson'))
    self.assertEqual(second.document_id, first.document_id)
    self.assertIsNone(job)
```

- [ ] Write failing tests for untouched core-root sentinel checksums; duplicate bytes/different filenames; traversal, Windows reserved filenames and root overlap; streamed file exceeding `50 * 1024**2`; duplicate archive entries, XML entity declarations and `200 * 1024**2` expansion. Assert `StudyError.code`, retained metadata and no partial upload promotion.
- [ ] Run `python -m unittest discover -s aura_bio_system/tests -p test_study_storage.py -v`; expect failure on missing implementation, not unrelated environment errors.
- [ ] Implement per-pack SQLite plus root catalogue, generated storage paths, atomic original promotion and rollback on failure. Keep original bytes unchanged. ZIP preflight validates required OOXML parts, total expansion, external entities/macros/encryption; never extract arbitrary member paths. Add optional `study` dependencies with reviewed supported version bounds, not `latest`; no automatic installation/download.
- [ ] Rerun the targeted command; expect all assertions passing and `.local/` ignored. Commit nothing.

### Task 2: Format-aware extraction and honest coverage

**Files:** Create the five `study/extractors*.py` modules; extend `study/schema.py`; create `aura_bio_system/tests/test_study_extraction.py` and `aura_bio_system/tests/study_fixtures.py` (small generated fixtures, no private uploads).

**Interfaces:** Define `Locator(kind, page, page_label, slide, shape_id, sheet, cell_range, start_line, end_line, role)` with optional fields and `as_dict() -> dict[str, Any]`; `Unit(unit_id, document_id, ordinal, role, title, breadcrumb, text, locators, metadata, asset_ids)`; `Asset(asset_id, unit_id, mime_type, content: bytes, coordinates)`; `Extraction(units: list[Unit], assets: list[Asset], warnings: list[str], coverage: dict[str, int], parser_version: str)`. `extract_document(path: Path, document: Document, limits: Limits) -> Extraction` dispatches to identical `extract(...)` signatures in each adapter. Parsers are lazy optional imports.

XLSX row units use `metadata['cells'][address]` with `formula` and `cached_value` fields. Primary fixture test:
```python
def test_formula_without_cache_is_not_a_value(self):
    result = extract_document(self.formula_xlsx, self.document, Limits())
    cell = result.units[-1].metadata['cells']['A3']
    self.assertEqual(cell['formula'], '=SUM(A1:A2)')
    self.assertIsNone(cell['cached_value'])
    self.assertTrue(result.warnings)
```

- [ ] Write failing tests: PDF blank middle page retains physical numbering; no usable text raises `ocr_required`; mixed pages warn without claiming scanned-page interpretation. PPTX preserves grouped bullets/levels, tables, separate notes, empty slide numbers and image coordinates. XLSX keeps merged ranges and original headers; formula `=SUM(A1:A2)` without cache has `cached_value=None`, unchanged formula text and a warning; hidden sheets are counted/excluded. TXT/MD preserve Unicode/headings/line ranges and reject invalid encodings. Assert limits fail instead of truncating and original SHA-256 remains unchanged.
- [ ] Run `python -m unittest discover -s aura_bio_system/tests -p test_study_extraction.py -v`; confirm expected red tests. If an optional parser is absent, record that limitation; do not count skipped format tests as verified extraction.
- [ ] Implement pypdf page text/labels with explicit layout limitations; python-pptx shape/table/notes traversal; openpyxl dual read-only formula/cached-value views without save/recalculation/external fetch; UTF-8/UTF-8-BOM text/Markdown extraction. Give all units stable document-scoped IDs and report unsupported assets/charts rather than claiming interpretation.
- [ ] Rerun; expect passing installed-parser tests and explicit remaining dependency blockers. No GPU or model imports.

### Task 3: Provenance-preserving chunks and pack retrieval generations

**Files:** Create `study/chunking.py`, `study/indexing.py`, `study/searcher.py`; extend `study/storage.py`; create `aura_bio_system/tests/test_study_retrieval.py`.

**Interfaces:** Define `StudyChunk(chunk_id, document_id, unit_ids, locators, spans, text, token_count, ordinal)` and `StudyEvidence(Evidence)` with additional `pack_id`, `unit_ids`, `locators` and `generation` fields; `as_dict()` retains all inherited retrieval fields and adds these. `chunk_units(units: Sequence[Unit], target_tokens: int = 450, overlap_tokens: int = 60) -> list[StudyChunk]`. `StudyIndexer(store: StudyStore).build(pack_id: str, *, dense_encoder: Any | None = None) -> int` returns the promoted generation. `StudySearcher(store: StudyStore, pack_id: str, *, dense_encoder: Any | None = None)` exposes existing `search(query: str, top_k: int, candidate_k: int) -> list[StudyEvidence]`, `neighbors(hits: Sequence[Any], radius: int = 1, limit: int = 16) -> list[StudyEvidence]`, `close() -> None` and `mode: str` (`sparse|hybrid`). Stored/query embedding manifests must agree on model, dimension, normalisation and the existing BGE query-only prefix.

Extend store with `publish_extraction(document_id: str, extraction: Extraction) -> None`, `units(pack_id: str, document_id: str) -> list[Unit]`, `original_path(pack_id: str, document_id: str) -> Path` and `asset_path(pack_id: str, document_id: str, asset_id: str) -> Path`; every lookup validates ownership. Primary same-section/body-role fixture test:
```python
def test_short_slides_keep_every_locator(self):
    chunks = chunk_units(self.five_short_slides)
    self.assertEqual(len(chunks), 1)
    self.assertEqual({loc.slide for loc in chunks[0].locators}, {1, 2, 3, 4, 5})
    self.assertEqual(len(chunks[0].unit_ids), 5)
```

- [ ] Write failing tests: five short slides merge yet retain all five locators/spans; no file/sheet/section/notes-role crossover; oversized units split with offsets/overlap; original numeric text retained. FTS queries return only active pack documents. Adjacent units, not document beginnings, are fetched; no cross-pack neighbours. Fake dense encoder verifies prefix only on queries; hybrid and sparse mode flags are truthful; repeated fusion does not mutate prior results.
- [ ] Run `python -m unittest discover -s aura_bio_system/tests -p test_study_retrieval.py -v`; confirm red assertions.
- [ ] Implement immutable generation directories containing SQLite/FTS5, optional FAISS/map and manifest; use shared safe tokenisation and weighted rank fusion without core-index writes. Preserve every unit/spanned locator after merging/compression. Build/publish through a temporary generation and atomic manifest replacement; never lazy-download an encoder. A missing dense dependency leaves usable sparse retrieval with an explicit warning.
- [ ] Rerun; expect all fake-encoder/SQLite tests passing, no core checksum differences.

### Task 4: Persistent bounded jobs, snapshot integrity and real purge

**Files:** Create `study/jobs.py`; extend `study/storage.py`, `study/indexing.py`; create `aura_bio_system/tests/test_study_jobs.py`.

**Interfaces:** `StudyJobs(store: StudyStore)` exposes `start()`, `stop()`, `retry(job_id: str) -> Job`, `request_dense_index(pack_id: str) -> Job`. `StudyStore.lease(pack_id: str) -> ContextManager[int]` pins a readable generation; `purge(pack_id: str, document_id: str | None = None, *, confirmation: str) -> PurgeResult` requires confirmation equal to the selected target ID. Lifecycle operations serialize per pack; purge must cancel/wait for its job and request leases. States include queued/extracting/extracted/indexing/sparse-ready/hybrid-ready/failed; interruption is a failed job with an explicit retryable reason.

Primary purge fixture test (with a materialised generation/private trace):
```python
def test_pack_purge_removes_private_storage(self):
    folder = self.store.root / self.pack.pack_id
    result = self.store.purge(self.pack.pack_id, confirmation=self.pack.pack_id)
    self.assertTrue(result.deleted)
    self.assertTrue(result.invalidated_history)
    self.assertFalse(folder.exists())
    self.assertEqual(self.core_sentinel.read_bytes(), b'unchanged')
```

- [ ] Write failing tests: a spawned extraction child times out at injected short test timeout; queued jobs survive restart and running jobs become interrupted; failed promotion leaves the previous generation searchable. Purge waits for a reader, prevents new leases, cancels queued work, closes Windows handles and deletes originals/assets/all old generations/private traces/JSONL. Document purge rebuilds remaining documents, pack purge leaves no pack directory/catalogue entry; unrelated pack/core bytes remain identical. A failed deletion records purge-pending, does not report success and cannot serve stale data.
- [ ] Run `python -m unittest discover -s aura_bio_system/tests -p test_study_jobs.py -v`; confirm controlled failures.
- [ ] Implement one persistent queue dispatcher and one isolated spawned extraction process at a time; open SQLite connections inside their owning process. Parent validates returned extraction before one transaction/promotion. Separate explicitly requested cache-only CPU dense work; never auto-start GPU indexing. Implement recoverable deactivation and confirmed purge with retryable cleanup, closed handles and generation invalidation. Purge is actual scoped deletion, not merely changing an `active` flag.
- [ ] Rerun; expect lifecycle/race tests passing without live models. Document filesystem-deletion limitations accurately.

### Task 5: Pack-only policy through the complete existing orchestration

**Files:** Create `study/routing.py`, `study/prompts.py`, `study/verification.py`, `study/runtime.py`; modify `aura_bio_system/src/aura_bio/pipeline.py`, `routing/schema.py`, `retrieval/strategies.py`, `retrieval/reranker.py`, `api/generation.py`, `critique/external.py`; create `aura_bio_system/tests/test_study_pipeline.py`. Do not change core prompt content/defaults.

**Interfaces:** Define frozen `AnswerPolicy(evidence_scope: str = 'core', pack_id: str | None = None)` in the pipeline, accepted as the final optional constructor argument. Add default `domain='biology'`, `evidence_scope='core'` to `Route`; existing calls remain compatible. `StudyRouter(domain: str).route(query: str, learner_level: LearnerLevel | str | None = None, teaching_mode: TeachingMode | str | None = None, context_level: int | None = None) -> Route` uses a neutral `user_material` subdomain and mandatory depth >=1. `build_study_prompt(route: Route, evidence: Sequence[Any], instructions: Sequence[str], coverage_pool: Sequence[Any] = (), unknown_entities: Sequence[str] = (), previous_answer: str = '') -> Prompt` matches the generator's six-argument builder contract but ignores coverage_pool/unknown_entities; never invoke core `build_prompt` or `coverage_terms`. Add optional constructor `prompt_builder: Callable[..., Prompt] | None` to `OllamaGenerator` and `PromptedGenerator`; default keeps core behaviour. `StudyVerifier(domain: str = 'general').verify(answer: str, evidence: Sequence[EvidencePassage], route: Route | None = None, question: str | None = None) -> VerificationReport` retains the existing verifier contract. `build_pack_pipeline(store: StudyStore, pack_id: str, *, use_critic: bool = False) -> AuraBioPipeline` constructs request-scoped policy/searcher/store without replacing shared core components. `per_source_cap`/`per_document_cap` accept `None` to disable caps; defaults stay 4/2. Add optional `neighbor_fetch: Callable[[Sequence[Any], int, int], list[Any]] | None` to retrieval strategy dispatch and propagate through fused/deep expansion.

Primary cap test (five non-redundant relevant passages from one document):
```python
def test_pack_evidence_is_not_source_capped(self):
    self.assertEqual(len(select_evidence(self.five_passages, 5, per_source_cap=None)), 5)
    selected = select_diverse_evidence(self.query, self.five_passages, 5,
                                      per_source_cap=None, per_document_cap=None)
    self.assertEqual(len(selected), 5)
```

- [ ] Write failing tests for both standard/robust pack selection retaining five useful single-file passages within budget; depth 3/4 invokes the pack neighbour callback after query fusion. Assert core selector/router/prompt outputs unchanged. Pack entity checks never call the GO/MeSH lexicon; general packs never load the learned bio router or enable physiology/pathway rules. Biology adapters are explicit and recorded.
- [ ] Add prompt/repair leakage tests: no memory-completeness/checklist directives; malicious slide instructions remain quoted evidence; draft/candidate text cannot promote itself to an instruction. With fake semantic results, every factual claim must cite a supporting selected passage, not merely one claim per answer. Wrong-page/unrelated citations, missing claims and NLI contradiction stay blocking. Lexical-only fallback is degraded, not certified support. Missing evidence/unsupported final drafts return an insufficient-support response while retaining raw drafts/checks in the trace.
- [ ] Add calculation tests: cited document inputs and explicit question premises are required; pack-only generated numbers cannot be approved by finding any matching number in unrelated text. General numerical checks use bounded arithmetic/unit conversions only; ambiguous formulas stay unverified. Biology calculations keep existing contradiction/numeric gates and never bypass pack grounding. No model-produced Python or workbook formulas execute.
- [ ] Run `python -m unittest discover -s aura_bio_system/tests -p test_study_pipeline.py -v`; confirm red tests.
- [ ] Implement neutral routing, separately authored grounded draft/repair/critic prompts, strict claim-to-cited-passage checks and honest checker status. Reuse existing generation, candidate verification, external-critic excerpt handling, selection, bounded revision, delivery and trace production. Put private `TraceStore` under the pack and annotate scope/pack/generation in traces. General numeric support uses an AST whitelist of finite literals and `+ - * /` (no names/calls/attributes; at most 256 characters/32 nodes and absolute values <=1e12) plus Pint conversion of source-backed values; reject ambiguous bindings instead of guessing. Retain biology adapter checks only when selected. Avoid core calculation-render citation exemptions in pack-only mode.
- [ ] Rerun targeted tests and existing pipeline/strategy/reliability/final-quality tests; expect unchanged core assertions. Trace skipped/unavailable features rather than calling sparse/unchecked execution complete hybrid verification.

### Task 6: Local API, source previews and privacy lifecycle

**Files:** Create `aura_bio_system/src/aura_bio/api/study_packs.py`; modify `api/app.py`, `api/mapping.py`; create `aura_bio_system/tests/test_study_api.py`.

**Interfaces:** `/api/v1/study-packs`: POST `{name, domain?}`, GET list; `/{pack_id}` GET detail and DELETE with `{confirmation}`; `/{pack_id}/documents` POST multipart upload, GET list; `/{pack_id}/documents/{document_id}` GET detail and DELETE confirmed purge; `.../{document_id}/deactivate` POST; `.../{document_id}/units` GET paginated; `.../{document_id}/units/{unit_id}` GET original text/locators; `.../{document_id}/original` GET attachment; `.../{document_id}/assets/{asset_id}` GET safe image; `/{pack_id}/search` POST `{query, mode}`; `/{pack_id}/index` POST `{dense: bool}`; `/api/v1/study-jobs/{job_id}` GET and `/retry` POST. Existing run/search models gain `pack_id: str | None` and `evidence_scope: Literal['core', 'pack_only']='core'`. Add `forget_pack_runs(pack_id: str) -> None` to remove scoped `_RUNS` and `_RUN_ORDER` entries after confirmed purge. Citation payloads add optional `pack_id`, `document_id`, `unit_ids`, `locators`, `generation` and validated `preview_url`.

Add `assert_study_origin(request: Request) -> None` for all private pack, scoped run/search/preview/event endpoints; reject foreign Origin headers with 403 and permit origin-less local CLI requests. Primary API fixture test:
```python
def test_unknown_pack_never_uses_core(self):
    response = self.client.post('/api/v1/runs', json={
        'query': 'Explain the lesson', 'evidence_scope': 'pack_only', 'pack_id': 'f' * 32})
    self.assertEqual(response.status_code, 404)
    self.core_runtime.assert_not_called()
```

- [ ] Write failing contracts: intake works with `get_runtime` patched to raise and fake model/network functions disabled; core defaults unchanged. Invalid scope/IDs ->422, missing pack ->404, not-ready/purge-pending ->409, limits ->413, invalid containers ->422, unsupported format ->415. Preserve intended HTTPException in `create_run`, not its current broad-exception-to-500 behaviour. Unknown pack never falls back to core; requesting unavailable dense mode does not silently claim hybrid.
- [ ] Add preview tests for exact unit/cell/slide, inactive historical citations and no arbitrary path access; raw HTML/macro/script attachments are never executed. Confirm purge clears cached answers and SSE access; streams hold a pack lease so purge cannot race a retained local replay object. Default external critique is off; explicit opt-in records private-excerpt disclosure. Paged APIs avoid dumping entire books.
- [ ] Run `python -m unittest discover -s aura_bio_system/tests -p test_study_api.py -v`; confirm red assertions.
- [ ] Implement router/lifespan worker startup/shutdown without model initialisation. Validate run scope before choosing core versus pack factory; maintain the existing event/answer contract. Original downloads use attachment disposition; previews show escaped structured content, safe image MIME types and validated IDs. Return purge history invalidation so the frontend can clear matching state; do not put private error excerpts in server logs.
- [ ] Rerun new contracts plus `test_api.py`; expect all installed-dependency assertions passing. Keep core trace/database paths untouched by pack operations.

### Task 7: Study-material navigation, upload and citation inspection

**Files:** Create `frontend/src/pages/StudyPacksPage.tsx`, `frontend/src/pages/StudyPacksPage.test.tsx`, `frontend/src/lib/trace-store.test.ts`; modify `frontend/src/types.ts`, `lib/api.ts`, `lib/trace-store.ts`, `hooks/use-run.ts`, `pages/AskPage.tsx`, `components/ui.tsx`, `components/layout.tsx`, `app.tsx` and `styles.css`. Reuse existing UI styling; do not redesign unrelated pages.

**Interfaces:** Add typed Pack/Document/Job/Locator responses matching Tasks 1/2/6. `api.studyPacks` exposes create/list/detail/upload/status/unit/deactivate/purge/search/index methods using the Task 6 URLs. Add `/study-packs` navigation and a pack selector in Ask. `clearPackArchive(packId: string) -> void` removes any matching browser records; `archiveRun` and `archiveSummary` skip all new pack-only runs.

Primary browser-storage fixture test:
```typescript
it('does not archive private pack runs', () => {
  localStorage.clear();
  archiveRun(privatePackRun);
  expect(localStorage.length).toBe(0);
});
```

- [ ] Write failing Vitest tests: upload progress is byte transfer only; extraction/index states and warnings are separate; sheet/slide/page navigation preserves blank numbering and multiple merged locators. Choosing a pack sends `pack_only` and prevents submission before ready; deselecting restores core. Source drawer opens the actual unit, not just a 600-character snippet. Verify accessible labels, keyboard controls and original downloads.
- [ ] Add privacy tests: pack answers never enter localStorage; purge requires a target-specific confirmation, clears visible private answers/history and invokes `clearPackArchive`; failed purge retains its warning rather than claiming deletion. External-critic opt-in requires the private-excerpt warning. Generic uploaded prompts render as text, not executable markup; core archives and corpus dashboard remain unchanged.
- [ ] Run `npm --prefix frontend test -- src/pages/StudyPacksPage.test.tsx src/lib/trace-store.test.ts`; confirm expected red assertions.
- [ ] Implement management/document outline/coverage/warnings and source previews in the existing design system, with no new chart/Office renderer dependency. Clearly label uninterpreted images and non-pixel-perfect text previews. Do not store private query/answer text in settings or browser archives; discard pending scoped UI data and matching React Query caches after successful purge.
- [ ] Rerun targeted tests, then `npm --prefix frontend test` and `npm --prefix frontend run build`; expect passing tests and TypeScript/Vite build. Perform browser/UI verification when available without loading GPU models.

### Task 8: Frozen pack evaluation and handoff evidence

**Files:** Create `aura_bio_system/benchmarks/study_pack_bank.jsonl`, `aura_bio_system/benchmarks/study_pack_sources.json`, `aura_bio_system/benchmarks/run_study_pack.py`, project-authored fixtures under `aura_bio_system/benchmarks/study_fixtures/`, `aura_bio_system/tests/test_study_evaluation.py`, `docs/study-packs.md`; modify README links and `.gitignore` for locally acquired external evaluation files/results only.

**Interfaces:** Each bank record has `id`, `question`, `expected_answer`, `expected_units`, `answerable`, `multi_unit` and `fixture_id`; exactly 30 IDs, 20 supported, 10 absent controls, at least 8 multi-unit. `evaluate_pack_run(records: Sequence[dict[str, Any]], bank: Sequence[dict[str, Any]]) -> dict[str, Any]` produces separate retrieval recall@k, all-unit coverage, locator accuracy, citation correctness, abstention and reviewed-grounded-answer results; unverifiable/manual-unreviewed metrics are null, not fabricated scores. CLI supports `--pack-id`, `--model`, `--bank`, `--retrieval-only`, `--tag`, with immutable config/source/code hashes and resumable JSONL outputs. Keys are loaded only by this evaluation module, never searcher/generator/pipeline.

Primary bank test:
```python
def test_bank_has_supported_and_absent_controls(self):
    self.assertEqual(len(self.bank), 30)
    self.assertEqual(sum(q['answerable'] for q in self.bank), 20)
    self.assertEqual(sum(not q['answerable'] for q in self.bank), 10)
    self.assertGreaterEqual(sum(q['multi_unit'] for q in self.bank), 8)
```

- [ ] Write failing tests asserting the exact bank counts, disjoint question IDs, complete source locators, absent controls with empty expected units, no keys in prompt traces and correct zero/null denominator handling. Fake two-unit runs test coverage separately from concept recall; incorrect locator/citation cannot count as support. Verify unchanged biology bank/core sentinel checksums.
- [ ] Run `python -m unittest discover -s aura_bio_system/tests -p test_study_evaluation.py -v`; confirm red assertions.
- [ ] Prepare manually checked keys against the original authored fixtures. The OpenStax chapter was excluded because its current terms require prior permission for AI ingestion; no chapter was acquired. A permitted real-textbook evaluation remains future work. Include novel synthetic lecture values and clearly label their fictional status. Freeze the bank before future accuracy tuning.
- [ ] Implement the fake/retrieval-only-compatible harness and document parser setup, paths, privacy, deletion, sparse versus hybrid readiness, extraction limitations and test evidence. Do not start a real model benchmark now. Once the GPU is available, compare the same questions/source snapshot with baseline and pack-only complete pipelines and manually audit correctness; no claim of unknown pretraining membership or guaranteed accuracy uplift.
- [ ] Rerun targeted tests; then run `python -m unittest discover -s aura_bio_system/tests -q` offline on CPU, the existing corpus retrieval tests, frontend tests/build and `git diff --check`. Record actual passes/skips/failures and dependency blockers; unit tests do not establish answer accuracy. Leave all changes uncommitted.

## Verification environment

PowerShell, before Python test commands:

```powershell
$env:PYTHONPATH = 'G:/aura_llm/.cache/study-deps;G:/aura_llm/.cache/verification-deps'
$env:AURA_DEVICE = 'cpu'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:USE_TF = '0'
```

Use a temporary study root inside each test; never point test purges at real user data. Corpus check: `python -m unittest discover -s corpus_pipeline/tests -p test_retrieval.py -q`. If dependency installation is required, report the exact missing packages/command before claiming all-format verification. Do not replace real failures with mocks in integration tests.

## Separate core-accuracy work, not completed by this plan

See `docs/accuracy-boosting.md`, older-review reconciliation. Best-of-N, MMR-style selection, compact prompts, bounded multi-query and BGE instructions already exist. Explicit memory-first enrichment, RAFT, held-out RRF tuning, stronger-reranker comparison and shallow compression remain experiments, not completed improvements. Do not quietly change frozen core defaults while implementing pack-only grounding. RAFT needs a separate approved data/training plan; no training run is included here.

## Self-review and execution checkpoint

Spec coverage: storage/safety (Tasks 1/4), formats/locators (2/3), pack caps/prompts/router/neighbours/checks (5), API/private deletion (6/7), evaluation/documentation (8). All five Review Focus cases have explicit owner tests. Interfaces are defined before consumers; core defaults and no-commit/GPU constraints are retained.

Status: implemented inline and self-reviewed. Final verification results are recorded in the execution ledger and `docs/study-packs.md`. Initial frontend runner limitations and the OpenStax exclusion are disclosed above. Any independent agent review still requires separate authorisation. All changes remain uncommitted.
