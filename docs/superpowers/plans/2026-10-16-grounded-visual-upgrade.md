# Grounded Visual Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make source-figure inspection, relationship diagrams and scientific plots useful, source-faithful and measurable before adding newly illustrated figures.

**Architecture:** Keep the existing local retrieval, claims-first delivery, visual jobs and declarative renderers. Replace fragile quote copying with an immutable evidence registry; build source inspection, graph layouts and plot semantics on checked records. New wire contracts are versioned and old artifacts remain readable.

**Tech Stack:** Python/unittest/FastAPI/SQLite, existing Ollama model, React/TypeScript/Vitest/Playwright, locally bundled Mermaid, Recharts and trusted SVG generation. No new runtime dependency is required by this plan.

**Spec:** [Approved design](../specs/2026-10-16-grounded-visual-upgrade-design.md).

Status: implementation plan awaiting user review and execution-method selection.
Spec approved by the user's subsequent “Do it”; no implementation is implied by this plan's existence.

## Global Constraints

- No commits, pushes, Git resets/stashes, cloud uploads, model/provider switches, downloads or application redesign.
- Preserve original uploads/core corpus, old index snapshots, unrelated changes and frozen banks/results. Explicit derived pack processing may publish a new atomic generation, never overwrite historical snapshots.
- Keep Off/Auto/manual visual choices and optional thinking. Figure understanding requested by the question is separate from displaying answer visuals.
- No model-authored Python, JavaScript, SVG, HTML or Mermaid execution. A visual cannot verify itself or replace a checked text answer.
- Keep `native_text`, `ocr`, `vlm`, `user_annotation` and their checking statuses separate. VLM/OCR-only numbers are not certified plot inputs.
- Registry maximum: 256 fragments, further bounded by the selected model's remaining prompt allowance. No silent context increase or dependency-dropping truncation.
- Focused reading: at most two provider calls total per question including repair, across at most two regions; shared deadline 300 seconds, 600 only with explicit thinking. Any new overview inference counts against that budget.
- Standalone ingestion keeps explicit per-figure configuration. Crop original owned renders before the existing one-megapixel per-input cap.
- Layout proposal: one call, 3072 output tokens, 300 seconds, no repair/fallback; reject length stops. Resource/model-phase guards remain active.
- Preserve existing 64 KiB wire limit and v1 bounds. V2 bounds below are equally explicit, not permission to truncate unsupported content.
- Preserve original 12-case gate: 7/9 manually valid positives, one per kind, all 3 fixture controls rejected. Extension gate: 20 positives/10 controls, at least 3/4 positives per kind and all controls correct; pending reviews never pass.
- Execute heavyweight suites/model checks sequentially. Independent failures continue; dependent or resource-blocked stages pause visibly. No system/pagefile changes or unrelated model/app unloading.
- Newly illustrated anatomical figures, biological drawing-component libraries, raster generation, fine-tuning, internet search and calculated/simulated plots are deferred.

## Review Focus

1. Repeated labels in two documents or two table rows: binding must retain exact occurrence and document ownership (Tasks 2–3).
2. PDF rotation/cropping plus a shared legend outside the panel: focused reading must preserve context and highlight the original upright location (Tasks 4–6).
3. Conditional inhibition inside a feedback cycle: preserve direction/modality; allow mechanism cycles but not circular procedure ordering (Tasks 7–8).
4. Different groups at adjacent times, missing cells and undefined uncertainty: never manufacture a trajectory, zero or confidence interval (Tasks 9–10).
5. Purge/cancel/new question while crop interpretation or rendering is pending: never publish late private results or attach them to the next answer (Tasks 5–6, 11).

---

## File and interface map

New focused backend units under `aura_bio_system/src/aura_bio/`:

- `visual_outputs/registry.py`: immutable exact source-fragment identity and resolution.
- `visual_outputs/diagnostics.py`: bounded public reason codes/private failure records.
- `visual_outputs/relations.py`: checked relationship records; no layout code.
- `visual_outputs/observations.py`: scoped numeric records and series/uncertainty validation.
- `study/visual/details.py`: versioned panel/table observations and conflict detection.
- `study/visual/focus.py`: owned region selection, crop context and shared call/time budget.

Existing integration points:

- `visual_outputs/{planner,schema,grounding,source,context,evaluation}.py`;
  `study/visual/{description,schema,jobs,storage,selection,assets}.py`;
  `api/{study_visual,mapping}.py` and existing tracing ownership hooks.
- `frontend/src/{types.ts,lib/api.ts,lib/prepare-document-question.ts}`;
  `frontend/src/lib/visual-diagram.ts`, `components/answer-visuals/*`.
  Do not change Ask page design/layout.

New frontend units:

- `frontend/src/lib/visual-plot.ts`: pure chart geometry/series rules shared by renderers and exports.
- `frontend/src/components/answer-visuals/HeatmapVisual.tsx`: bounded native SVG heatmap.
- `frontend/src/components/answer-visuals/DistributionVisual.tsx`: source-bin/sample distribution view.

Existing v1 types/functions keep their behavior. V2 public discriminated unions
are added explicitly; never widen all v1 validators to accept arbitrary fields.
Tests below live under `aura_bio_system/tests/` unless a frontend path is given.

## Stage A — measurable baseline and reliable binding

### Task 1: Freeze the extension bank and production-parity baseline

**Files:** Create `aura_bio_system/benchmarks/run_visual_upgrade.py`, `tests/test_visual_upgrade_runner.py`; use unchanged `benchmarks/run_visual_output_eval.py`, `run_figure_eval.py` and `data/visual_output_bank_v1.*`.

**Interfaces:** New `run_case(case: dict, runtime, output: Path) -> dict` and
`validate_manifest(manifest: dict, bank_bytes: bytes) -> list[dict]` in the new
runner. Runtime is the existing production adapter, not a fake manually asserted
claim context for real cases. Records contain ID, mode, case/source hashes,
attempt/config identity, status, reasons, stage timings and raw private traces.

- [ ] Write `test_hash_change_refuses_before_inference`, `test_gold_and_proposals_never_enter_model_inputs`, `test_independent_failure_continues`, `test_unknown_completion_is_not_resubmitted` and `test_resource_deferred_is_not_pass`. Assert unchanged hashes, no gold fields in captured inputs, second independent case attempted, one timeout request and explicit pending state respectively.
- [ ] Run `python -m unittest test_visual_upgrade_runner -v`; confirm each new behavior fails for its intended reason.
- [ ] Pin assertions in the tests: `self.assertEqual(provider.calls, 1)` after timeout; `self.assertNotIn('gold', captured_input)`; `self.assertEqual(second_record['id'], second_case['id'])`; `self.assertFalse(summary['release_passed'])` for a deferred required case.
- [ ] Implement manifest checking, per-case checkpoint/resume identity, preflight, production invocation and separate fixture/model modes. Never overwrite an output directory or copy old answers into a new run.
- [ ] Author/freeze `.local/visual-upgrade-20261016/bank.jsonl`, `manifest.json` and private `keys.json`: 4 positive cases each for source, diagram, comparison, procedure and plot; 10 controls. Record real-source grouping/disjointness, crop hashes and conditions; keys stay evaluator-only. Include the observed dense-panel/table cases, qualified/branched/cyclic diagrams, multi-series/missing/error-bar/heatmap/distribution data and ambiguity/injection/provenance controls. Distinguish malformed-layout controls from genuinely unsupported live questions. Native plot data must actually exist in its source; do not invent a real-PDF numeric bank.
- [ ] Verify source checksums and manually inspect the frozen question/key/source mapping before tuning. Run the unchanged old bank and the existing full document preparation/Ask path on real cases as the baseline. Preserve unsupported-new-feature outcomes as failures, not silently substitute hand-authored output. Record memory deferrals honestly.
- [ ] Rerun the runner tests; expected all pass. Save baseline command/config/hash provenance. No commit.

### Task 2: Build immutable source-fragment registry

**Files:** Create `visual_outputs/registry.py`, `tests/test_visual_registry.py`; use `visual_outputs/context.py` unchanged as the retained-claim authority.

**Interfaces:** Frozen `EvidenceFragment(id, cite_id, claim_ids, start, end,
text, provenance, source_hash, generation, locator)` and `EvidenceRegistry(context_hash,
fragments, omitted_claim_ids)`; `build_registry(context: VisualContext, question: str,
*, max_fragments: int = 256, prompt_byte_budget: int) -> EvidenceRegistry`;
`resolve_fragment(registry, fragment_id: str, context) -> dict` returns the existing
`{cite_id,start,end}` binding after context/source-identity checks.

- [ ] Write `test_duplicate_cells_keep_distinct_offsets`, `test_foreign_or_stale_id_rejected`, `test_removed_claim_never_enters_registry`, `test_limit_reports_omitted_dependencies` and `test_registry_does_not_upgrade_provenance`. Use `visual_output_fixtures.context()` and repeated original text; assert distinct starts, ValueError on changed context/citation, missing removed claim, explicit omissions and unchanged OCR/VLM status.
- [ ] Run `python -m unittest test_visual_registry -v`; confirm RED.
- [ ] Pin duplicate ownership with `self.assertNotEqual(first.start, second.start)` and `self.assertEqual(source[first.start:first.end], first.text)`; use `with self.assertRaises(ValueError)` for foreign/stale contexts and `self.assertLessEqual(len(registry.fragments), 256)`.
- [ ] Implement stable request-scoped IDs from context hash plus exact citation/span identity. Candidate spans come from source sentence boundaries, exact retained claim subphrases, numbers/units and source-owned structured cells. Rank by question relevance with dependencies retained; enforce 256 fragments and a conservative UTF-8 byte allowance within remaining context. No fuzzy quote repair, extra model call or evidence certification.
- [ ] Run `python -m unittest test_visual_registry test_answer_visual_grounding test_core_visual -v`; expected PASS and unchanged old grounding behavior. No commit.

### Task 3: Use fragment IDs in constrained proposals and retain rejection causes

**Files:** Create `visual_outputs/diagnostics.py`, `tests/test_visual_registry_proposals.py`; modify `visual_outputs/{planner,schema,grounding}.py`; preserve `quotes.py` for legacy consumers and its regression tests.

**Interfaces:** `registry_schema(schema: dict, registry: EvidenceRegistry) -> dict`
and `resolve_registry_proposal(raw: str, schema: dict, registry, context) -> str`
in `registry.py`; new proposal binding is exactly `{fragment_id: str}`. Resolution
returns existing v1 bindings before grounding where possible. New `failure_record(stage:
str, code: str, *, private_detail: str = '') -> dict` never puts private detail in
the public `VisualResult.metadata`.

- [ ] Write `test_plot_and_comparison_select_ids_without_recopying_quotes`, `test_auto_uses_same_registry`, `test_valid_id_cannot_swap_group_values`, `test_one_call_no_repair_or_fallback`, `test_failure_reason_visible_private_text_absent` and `test_v1_quote_and_offset_archives_still_readable`. Assert exact resolved offsets, swapped values rejected and one local call. Public metadata carries safe `stage`/`reason_code`, not raw source/provider text.
- [ ] Run `python -m unittest test_visual_registry_proposals -v`; confirm RED.
- [ ] Pin compatibility/safety with `self.assertEqual(result.status, 'ready')` for valid IDs, `self.assertNotEqual(swapped.status, 'ready')`, `self.assertEqual(len(sent), 1)` and `self.assertNotIn(private_source_text, json.dumps(result.metadata))`.
- [ ] Route new local proposal decoding through registry IDs. Compute prompt allowance from existing `num_ctx` minus instruction/output reservation; if no safe allowance exists, return a recorded limit rather than increase context. Keep 3072/300/retries=0 and exact selected model identity. Distinguish generation/schema/identity/grounding failures; private raw outputs remain in existing private tracing, never global public archives.
- [ ] Run `python -m unittest test_visual_registry_proposals test_visual_quote_bindings test_auto_visual test_answer_visual_api -v`; expected PASS. Rerun the unchanged 12-case bank to a fresh output path, review its 9 positives explicitly, and report per-kind omissions rather than just process exit. No commit.

## Stage B — referential figure understanding

### Task 4: Versioned panel/table records with independent provenance

**Files:** Create `study/visual/details.py`, `tests/test_visual_details.py`; modify `study/visual/{description,schema,jobs}.py` and version-aware schema dispatch.

**Interfaces:** `detail_schema() -> dict`, `validate_details(raw: str) -> dict`,
`detail_conflicts(details: dict) -> tuple[dict,...]`. V2 keeps the overview and
adds `panels` (max 16) and `tables` (max 4); each panel has ID, label, optional
owned bbox, organism/condition observations and uncertainties; each table has
headers (max 16), rows (max 32), cells (max 128 total) and explicit missing/merged
status. Observations carry origin and source references; generated pixels never
receive `native_text` merely because the caption repeats them. Overall 64 KiB and
existing local inference limits still apply; incomplete coverage is explicit.

- [ ] Write `test_caption_and_pixels_disagree_without_provenance_promotion`, `test_table_cells_keep_row_header_identity`, `test_missing_cell_is_not_zero`, `test_panel_conflicts_reported`, `test_repair_cannot_add_identity_even_if_other_fields_missing` and `test_v1_description_archive_still_readable`. Assert NMR/mouse disagreement is retained and VLM numbers remain uncertified.
- [ ] Run `python -m unittest test_visual_details -v`; confirm RED.
- [ ] Pin origins with `self.assertEqual(pixel_observation['origin'], 'vlm')`, `self.assertTrue(detail_conflicts(conflicting_details))` and `self.assertEqual(missing_cell['value'], None)`; distinct caption assertions require their own native source reference.
- [ ] Implement a distinct versioned description contract and prompt hash. Extract exact native caption panel ranges with source spans where unambiguous; record pixel proposals separately. Keep old validator/schema paths for old configurations. Structured repair preserves independently recognizable identities, never relabels a panel to make a conflict disappear.
- [ ] Run `python -m unittest test_visual_details test_visual_output_contract test_figure_description test_visual_jobs -v`; expected PASS. No commit.

### Task 5: Owned crops and shared focused-read budget

**Files:** Create `study/visual/focus.py`, `tests/test_visual_focus.py`; modify `study/visual/{assets,selection,jobs,storage}.py`.

**Interfaces:** Frozen `FocusRegion(id, figure_id, bbox, frame, context_refs,
source_hash, question_hash)`; `select_focus(question: str, figure, details: dict,
*, limit: int = 2) -> tuple[FocusRegion,...]`; `FocusBudget(max_calls: int,
deadline: float)` with `reserve_call(now: float) -> float` returning remaining
seconds or raising `StudyError`; `read_focus(regions, question, config, visual_store,
describer, budget: FocusBudget) -> tuple[dict,...]`.

- [ ] Write `test_original_render_cropped_before_downscale`, `test_rotated_panel_with_shared_legend_roundtrips`, `test_two_region_budget_includes_repair`, `test_timeout_not_reuploaded`, `test_missing_geometry_does_not_invent_crop`, `test_purge_before_publish_rejects_result` and `test_cache_key_changes_with_question_crop_hints_and_model`. Assert max 2 calls and shared 300/600 deadline using fake clock; borrowed legacy test providers do not count as real-model evidence.
- [ ] Run `python -m unittest test_visual_focus -v`; confirm RED.
- [ ] Pin budgets with `self.assertLessEqual(provider.calls, 2)`, `self.assertLessEqual(clock.elapsed, 300)` in non-thinking mode, and `self.assertEqual(provider.calls, 1)` after an unknown timeout. Coordinate assertions use `self.assertAlmostEqual` for all four original bbox coordinates after rotation/crop roundtrip.
- [ ] Implement geometry/label-driven selection over owned records and original render transforms. Preserve headers/legends as owned context; no extra selection VLM call. Use existing inference ownership/preflight and private checkpoints. Extend `FigureDescriber.describe` with an optional shared call budget, so repairs consume the same budget; keep default standalone behavior unchanged. Persist versioned region records under visual revisions; no mutable replacement of originals.
- [ ] Run `python -m unittest test_visual_focus test_visual_assets test_visual_storage test_visual_jobs -v`; expected PASS. No commit.

### Task 6: Wire explicit Ask preparation, indexed details and precise highlights

**Files:** Modify `api/study_visual.py`, `study/visual/storage.py`, `study/searcher.py`, `visual_outputs/source.py`, `frontend/src/{types.ts,lib/api.ts,lib/prepare-document-question.ts,lib/prepare-document-question.test.ts}` and `components/answer-visuals/SourceVisual.tsx`; create `tests/test_visual_focus_api.py`.

**Interfaces:** Preserve resolve-only `/visual-question`; its response adds
versioned owned region candidates and safe warnings. Explicit visual-start may
request `description_version=2` and `focus=true`; backend freezes question/config
and enforces the shared budget. `resolve_source_visual` keeps existing arguments,
adds validated panel/row highlights and `highlight_precision` values `panel` and
`table_row` in v2 only. Old v1 precision values retain their meanings.

- [ ] Write `test_get_upload_and_resolve_never_start_focus_inference`, `test_ambiguous_figure_number_never_selects_other_document`, `test_full_ask_uses_caption_ocr_and_question`, `test_unindexed_focus_revision_cannot_answer` and `test_purged_or_wrong_question_revision_cannot_highlight`. Frontend tests assert one explicit start, abort prevents run submission, late completion is discarded and no cloud consent is inferred.
- [ ] Run `python -m unittest test_visual_focus_api -v` and `npm --prefix frontend test -- src/lib/prepare-document-question.test.ts`; confirm RED.
- [ ] Pin side effects with `self.assertEqual(provider.calls, 0)` for resolve/upload/GET, `expect(start).toHaveBeenCalledTimes(1)` for explicit Ask, and `expect(submitAnswer).not.toHaveBeenCalled()` after abort or a late result for a different question.
- [ ] Integrate the new records into existing homogeneous derived units and normal atomic pack indexing, with question/source revision identity intact. Claim/citation projection resolves precise owned records; source resolver rechecks asset hash/lease/generation. Keep native captions independent from interpreted details. Local controls show panel/row/whole-figure precision and conflict warnings; do not redesign the page.
- [ ] Run source/API/attachment regression modules plus the frontend preparation/source tests. On a fresh trial pack, run the frozen real-PDF questions through actual Ask preparation and answer delivery; manually grade panel ownership, table lookup, unsupported controls and locator accuracy. Keep memory-deferred runs pending. No commit.

## Stage C — richer deterministic diagrams

### Task 7: Ground relationship/group semantics and version the graph contract

**Files:** Create `visual_outputs/relations.py`, `tests/test_visual_relations_v2.py`; modify `visual_outputs/{schema,grounding,planner}.py` and `frontend/src/types.ts`.

**Interfaces:** Frozen `CheckedRelation(subject_id, predicate, object_id,
qualifiers, claim_ids, bindings, support)`; `checked_relations(proposal: dict,
registry, context) -> tuple[CheckedRelation,...]`. V2 graph keeps max 20 nodes/
30 edges; adds orientation (`TD|LR`), layout (`pathway|cycle|hierarchy`), visual
roles (`entity|process|condition`), groups (max 8) and qualified relation records.
Membership is either source-bound factual containment or explicitly neutral
presentation grouping. No arbitrary model CSS, paths or geometry.

- [ ] Write `test_may_inhibit_and_negative_condition_survive`, `test_group_membership_requires_own_support`, `test_cycle_layout_cannot_invent_return_edge`, `test_reversed_or_association_as_causation_rejected`, `test_parallel_procedure_not_linearized` and `test_v1_graph_unchanged`. Assert complete qualifiers/conditions and exact source/claim ownership, not mere node co-occurrence.
- [ ] Run `python -m unittest test_visual_relations_v2 -v`; confirm RED.
- [ ] Pin semantics with `self.assertIn('may', checked_relation.qualifiers)`, `self.assertEqual(len(checked_edges), len(source_edges))` for a cycle layout and `self.assertNotEqual(invented_group_result.status, 'ready')`.
- [ ] Implement structured relationship checks with exact source bindings and retained-claim support. Presentation hints cannot add facts. Reuse existing procedure/comparison checks, extend only where complete bound records establish semantics rather than relaxing old tests. Unsupported projections retain a specific omission reason.
- [ ] Run relationship, grounding, schema, Auto and core-adapter tests; expected PASS. No commit.

### Task 8: Render graph layouts and semantic SVG markers

**Files:** Modify `frontend/src/lib/visual-diagram.ts`, `components/answer-visuals/{DiagramVisual,ProcedureVisual,ComparisonVisual}.tsx`, `export.ts`; tests in corresponding `*.test.ts(x)` files plus `frontend/tests/e2e/answer-visuals.spec.ts`.

**Interfaces:** Keep `compileDiagram(spec) -> string` for trusted Mermaid. Add
`applyDiagramSemantics(svg: string, spec: DiagramVisualSpec) -> string` using
known node/edge IDs; it creates only app-owned shapes/markers and passes through
the existing sanitizer. V2 support styles, group geometry and keyboard citation
handlers share the same validated spec used for export.

- [ ] Write tests asserting distinct activation/inhibition/association/containment markers, LR/TD and grouped layouts, complete visible qualifiers, no invented cycle edge, no external resources, malicious labels remain inert and SVG/PNG exports retain support/qualifiers. Include desktop/mobile long-label and overlapping-group fixtures.
- [ ] Run `npm --prefix frontend test -- src/lib/visual-diagram.test.ts src/components/answer-visuals`; confirm intended new assertions fail.
- [ ] Pin rendering with `expect(inhibitionMarker).not.toEqual(activationMarker)`, `expect(renderedLabels).toContain('may inhibit')` and `expect(svg.querySelectorAll('script,foreignObject,a[href]')).toHaveLength(0)`; assert exported qualifier/support strings match the screen spec.
- [ ] Implement trusted graph compilation and marker application; inhibition is a blunt end, association an unheaded connection, activation/causation directed arrows distinguished by their grounded labels, containment a supported enclosure. Mermaid computes bounded layout; no external renderer/editor. Preserve zoom, keyboard access and source controls. Do not clip factual labels or change dash patterns while applying relation markers.
- [ ] Run Vitest, frontend build and focused Playwright diagram cases sequentially; expected PASS. Save new screenshots and manually review readability/source fidelity, not only SVG existence. No commit.

## Stage D — scientific plot semantics and rendering

### Task 9: Bind observations, trajectories, uncertainty and table data

**Files:** Create `visual_outputs/observations.py`, `tests/test_visual_observations_v2.py`; modify `visual_outputs/{schema,grounding,planner}.py`, `frontend/src/types.ts`.

**Interfaces:** Frozen `CheckedObservation(id, series_id, group, quantity, value,
unit, x, x_unit, population, uncertainty, bindings, support)`;
`checked_observations(payload: dict, registry, context) -> tuple[CheckedObservation,...]`.
V2 keeps max 3 series/100 observations total; requires explicit series identity
and `origin='source_observation'`. Uncertainty is absent or source-bound:
`{kind: SD|SEM, magnitude, bindings}` or `{kind: CI|source_interval, lower, upper,
level?, bindings}`. Magnitudes are nonnegative; intervals contain the source's
stated center where applicable. Decimal strings remain authoritative and the
definition/level must be source-stated. Mean +/- supplied SD/SEM is drawing
geometry only, never an inferred CI or new observed datum; exports retain the
original center/magnitude and identify any computed drawing endpoint as derived
geometry, not a source-transcribed number.

- [ ] Write `test_different_groups_at_adjacent_times_cannot_join`, `test_table_headers_bind_same_row_value`, `test_swapped_cells_and_population_rejected`, `test_uncertainty_definition_and_bounds_are_source_bound`, `test_native_mean_cannot_fabricate_sample_distribution`, `test_vlm_ocr_or_simulation_origin_rejected` and `test_missing_value_stays_null`.
- [ ] Run `python -m unittest test_visual_observations_v2 -v`; confirm RED.
- [ ] Pin scientific constraints with `self.assertNotEqual(cross_group_line.status, 'ready')`, `self.assertEqual(missing.value, None)`, `self.assertEqual(sd.uncertainty['magnitude'], source_sd)` and `self.assertNotEqual(inferred_ci.status, 'ready')`.
- [ ] Implement one observation's source/cell/retained-claim ownership and compatible population/units; reject unknown trajectory identity, missing uncertainty definition, foreign cells and interpreted numeric inputs. Do not add arbitrary prose aliases or treat mere span existence as a numeric association. Preserve v1 inputs as legacy; v2 rejects the old cross-group time-line fixture unless rendered as separate observations.
- [ ] Run plot grounding/schema and observation tests; expected PASS. No commit.

### Task 10: Combined series, error bars, heatmaps and source distributions

**Files:** Create `frontend/src/lib/visual-plot.ts`, `visual-plot.test.ts`, `components/answer-visuals/{HeatmapVisual,DistributionVisual}.tsx` and their tests; modify `PlotVisual.tsx`, `AnswerVisual.tsx`, `export.ts`, backend v2 plot schema/observation checks as needed.

**Interfaces:** `plotGeometry(spec: PlotVisualSpec) -> PlotGeometry` moves to the
pure helper; `PlotGeometry` contains series/points, axis domains/scales, legends,
null masks, uncertainty and heatmap/bin geometry. `heatmap` uses unique row/column
IDs and at most 100 cells. `distribution` uses at most 100 source observations or
source-stated bins; no invented samples, KDE, fits or computed aggregates.

- [ ] Write tests for combined-series legends, source-bound intervals, missing heatmap cells distinct from zero, log-scale rejection of nonpositive values, unmatched-unit rejection, source bins not smoothed, source-table parity and export parity. Assert bars start at zero, lines don't bridge nulls and scatter remains unjoined.
- [ ] Run the new pure-helper and component tests; confirm RED.
- [ ] Pin geometry with `expect(barGeometry.yDomain[0]).toBe(0)`, `expect(lineGeometry.connectNulls).toBe(false)` and `expect(missingHeatmapCell.value).toBeNull()`; no tooltip/export may label SD as CI or substitute an invented sample.
- [ ] Render shared-axis series with existing Recharts and deterministic SVG heatmap/bin geometry. Use explicit labels, distinct accessible styling, visible scales and original data tables. Render only source-supplied uncertainty; do not compute SD/CI from samples in this pass. Update exported artwork/data together, retaining source refs and support status per observation.
- [ ] Run plot frontend tests and build; run backend plot/schema tests for added chart kinds. Review screenshots on desktop/mobile and compare every displayed value/unit to its source record. No commit.

## Stage E — compatibility, complete testing and quality handoff

### Task 11: API, export, ownership and whole-answer regressions

**Files:** Modify existing `tests/test_answer_visual_{api,schema,sources}.py`, `tests/test_visual_storage.py`, `tests/test_core_visual.py`, frontend visual/export tests and `frontend/tests/e2e/answer-visuals.spec.ts`; update `frontend/openapi/aura-bio.openapi.json` and `src/generated/api.ts` only through the existing API schema generation workflow.

**Interfaces:** Existing request options and answer text contract unchanged;
v1/v2 response unions explicit. Private source/registry/region revision IDs
remain lease-scoped. Full answer comparison records text, delivered claim IDs,
citations, confidence and decision before/after optional output planning.

- [ ] Write tests asserting those text/claim/confidence fields are identical when visual generation fails; test Off makes zero proposal calls; Auto/manual share grounding; no core image highlight without actual asset; stale/cross-pack IDs rejected. Add purge/cancel while focused interpretation or Mermaid rendering is pending and assert no late visible result or residual private artifact.
- [ ] Run the targeted modules/components/browser cases; confirm RED for the new v2 boundary behaviors.
- [ ] Pin whole-answer preservation with `self.assertEqual(after.markdown, before.markdown)`, `self.assertEqual(after.delivered_ids, before.delivered_ids)` and unchanged citations/confidence/decision; `expect(oldVisual).not.toBeVisible()` after cancellation/purge/replacement.
- [ ] Update version-aware serializers/schema projections, source overlays and exports. Reuse existing expiry/purge/abort ownership, don't add a global private cache or archive private text. For unsupported v2 renderers show a limitation and preserve text, never reinterpret as v1.
- [ ] Run backend full suite, frontend full suite, build and full visual browser suite sequentially. Expected zero test failures; preserve logs for each. Manually inspect screenshot fixtures containing long qualifiers, repeated labels and mixed provenance. No commit.

### Task 12: Frozen live evaluation and honest release report

**Files:** Extend `benchmarks/run_visual_upgrade.py`, create `tests/test_visual_upgrade_evaluation.py`; modify `visual_outputs/evaluation.py` to add `evaluate_upgrade_results(bank, records, reviews) -> dict` without changing `evaluate_visual_results`' original 12-case gate. Update `docs/{VISUAL_OUTPUTS,study-packs}.md` with actual limitations/results.

- [ ] Write `test_missing_omitted_and_unreviewed_stay_in_denominator`, `test_three_of_four_each_kind_required`, `test_guard_fixture_is_not_live_refusal`, `test_semantic_error_cannot_pass_as_valid_json` and `test_violation_prevents_release`. Assert 20 positive denominators, 3/4 each kind, all 10 controls, no unknown reviews treated as passes and zero unsupported/provenance/privacy violations required.
- [ ] Run `python -m unittest test_visual_upgrade_evaluation -v`; confirm RED.
- [ ] Pin denominators with `self.assertEqual(summary['positive_total'], 20)` and `self.assertEqual(summary['per_kind']['plot']['total'], 4)`; `self.assertFalse(summary['release_passed'])` when any category has only 2/4 valid positives, any control fails or any audited violation is nonzero.
- [ ] Implement separate automatic execution statistics and manual semantic/readability decisions. Report each positive kind and each control mode separately, including source resolution, call/latency totals, omissions, failures and memory deferrals. Review keys never enter runtime/model inputs. Preserve source-disjoint results as held-out checks, not repeated tuning cases.
- [ ] Run original 12-case output bank and the frozen 30-case extension sequentially on the selected unchanged local model/config. Run figure questions through full production resolver/VisualJobs/index/claim-delivery/source-resolver path and capture actual rendered diagrams/plots. Independent case failures continue; no automatic retry of unknown completions. Review native bindings, panel ownership, qualifiers, units, uncertainty and readability against actual sources.
- [ ] Release only if both original and extension gates pass, all audited safety controls pass and required whole-path tests complete without silent stage/model fallback. If blocked, state which gate failed with records and screenshots; don't claim completion from 858 old tests or future fixture passes.
- [ ] Hand off concise before/after results, representative real rendered outputs, pending limitations and the next deferred feature. No commit or push.

## Commands and execution notes

Use the existing environment; no installation/pull is part of this plan:

```powershell
Set-Location G:\aura_llm
$env:PYTHONPATH='G:/aura_llm/.cache/study-deps;G:/aura_llm/.cache/verification-deps;G:/aura_llm/aura_bio_system/src;G:/aura_llm/corpus_pipeline/src;G:/aura_llm/aura_bio_system/tests'
$env:USE_TF='0'
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:PYTHONIOENCODING='utf-8'
python -u -X utf8 -m unittest discover -s aura_bio_system/tests -v
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:e2e -- answer-visuals.spec.ts --workers=1
```

Before unit suites, remove benchmark-only environment switches that load actual
models into authored sparse/extractive fixtures; never weaken production model
requirements to make a live benchmark run. Model runs explicitly use
`AURA_OLLAMA_HOST=http://127.0.0.1:11434` and `qwen3.5:4b`, with frozen digest.

The new runner CLI is `python -u -X utf8 aura_bio_system/benchmarks/run_visual_upgrade.py
--manifest PATH --output NEW_DIRECTORY --mode fixture|model [--model qwen3.5:4b]`.
`--resume` is explicit and verifies source/model/question/schema identity; it skips
completed checkpoints but never duplicates a request with unknown completion.
Every run creates `progress.log`, `events.jsonl`, `records.jsonl` and `summary.json`.
Progress inspection: `Get-Content NEW_DIRECTORY/progress.log -Tail 20 -Wait`.

## Self-review and execution handoff

Coverage: shared registry/diagnostics (2–3), frozen baseline (1), source details/
crops/Ask/highlights (4–6), diagrams/comparisons/procedures (7–8), plot semantics/
rendering (9–10), ownership/export compatibility (11), quality gates/docs (12).
All five Review Focus conditions have owning tests. No placeholders or inferred
authorizations to commit, upload or install. Old results remain old results.

Recommended execution: **native/inline**, completing tasks in order and reviewing
each stage before enabling the next. This avoids fresh agent contexts for tightly
coupled contracts and matches the user's token-cost preference. A final independent
review can be requested under the review skill; do not spawn agents merely because
the generic header lists that option. Implementation starts after the user reviews
this plan and confirms the execution approach.
