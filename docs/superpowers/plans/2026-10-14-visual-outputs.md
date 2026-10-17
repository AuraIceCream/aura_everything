# Grounded Visual Outputs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax. User amendments are incorporated. User override, 14 October: implement visuals now without more text/GPU troubleshooting. Task 0's live result remains pending, but no longer blocks implementation; do not misreport it as passed.

**Goal:** Add citable diagrams, data plots and source-figure highlights without weakening checked text answers.

**Architecture:** Build an optional visual proposal from retained structured claims. Validate factual bindings against original evidence, then render through bounded local components; failures leave the text answer intact. Reuse pack assets and lifecycle controls.

**Tech Stack:** Python dataclasses/JSON, existing verifier and Ollama adapter, React/TypeScript, locally bundled Mermaid, existing Recharts, unittest, Vitest and Playwright.

**Spec:** [Grounded visual outputs design](../specs/2026-10-14-visual-outputs-design.md).

**Execution status, 14 October:** Tasks 1–7 are implemented in place, including a
single independently reviewed grounding/export fix pass. Task 0 remains deferred
under the user's visual-only override. Fresh verification and deferred findings
are recorded in `.local/visual-outputs-20261014/implementation-review.md` and the
execution ledger. The original checklists below preserve the approved plan;
they are not a claim that the live/manual quality gate passed.

## Global Constraints

All Global Constraints in the linked spec apply verbatim. In particular: no
commits/pushes; no corpus/upload changes; `visual_output=none` by default; options
`source|diagram|comparison|procedure|plot`; one visual and at most one constrained proposal call;
1024 output tokens/120 seconds; no repair or silent model/provider fallback;
64 KiB/20 nodes/30 edges/3 series/100 points/6 columns/12 rows/20 steps/120-character labels and cells; retained claim
and citation references; provenance preserved; visual failure retains text.

## Review Focus

1. A rejected text claim reappears as an arrow or data point: reject the visual (Tasks 1–2).
2. Correct values attach to the wrong groups, units or denominators: reject the plot (Tasks 2 and 5).
3. Private labels inject code, external image loads or Mermaid directives: no execution/network requests (Task 4).
4. A rotated crop, purged source or stale async result points at the wrong material: correct locator or visible failure, never substitute (Tasks 3 and 4).
5. Visual generation/renderer fails after a good answer: preserve identical text and show a limitation (Tasks 2 and 6).

---

## File and interface map

New backend package: `aura_bio_system/src/aura_bio/visual_outputs/` containing
`__init__.py`, `schema.py` (bounded wire types), `context.py` (retained claims),
`grounding.py` (evidence bindings), `planner.py` (one proposal), `source.py`
(authorized source resolution). Keep it separate from `study/visual/`, which
describes incoming images rather than producing outputs.

New frontend folder: `frontend/src/components/answer-visuals/` containing
`AnswerVisual.tsx`, `SourceVisual.tsx`, `DiagramVisual.tsx`, `ComparisonVisual.tsx`, `ProcedureVisual.tsx`, `PlotVisual.tsx`,
`export.ts` and focused co-located tests. Pure graph compilation lives in
`frontend/src/lib/visual-diagram.ts` with its own test file.

Wire types are mirrored in `frontend/src/types.ts` and the existing OpenAPI files;
Python uses frozen dataclasses and authoritative local validation. Define:

- `VisualContext`: retained `StructuredClaim` tuple, `claims_by_id` mapping, corresponding final claim-basis records and original indexed evidence. IDs come from the selected delivered draft, never another candidate.
- `VisualSpec`: version 1, ID, kind (`source|diagram|comparison|procedure|plot`), title, description and typed payload. Grounding status/citation IDs are assigned by the backend, not trusted from the model.
- Diagram payload: nodes `{id,label,claim_ids}` and edges `{from_id,to_id,relation,label,claim_ids}`. Relation enum: `precedes|part_of|associated_with|activates|inhibits|causes|visible_arrow`; edge labels retain source qualifiers/negation and are checked with their endpoints. Disconnected nodes allowed, dangling edges forbidden.
- Plot payload: chart type `bar|line|scatter`, axis titles/units, series and points with decimal-string values, group labels, retained claim IDs and evidence bindings `{cite_id,start,end}` for label/value/unit. Group scope and denominator, when applicable, must also be bound.
- Source payload: retained claim IDs and authorized pack/document/unit/asset IDs, optional normalized upright bbox. No URLs or paths from the model.
- Comparison payload: columns, row criteria and cells `{text,claim_ids,bindings}`; missing cells use an explicit `not_stated` status, not a negative factual assertion. Headers/criteria have grounding bindings too.
- Procedure payload: grounded steps `{id,text,claim_ids}` and validated `precedes` pairs; preserve partial ordering instead of inventing a sequence from citation position.
- `VisualResult`: `status` (`ready|omitted|failed`), optional spec and safe limitations. API `answer.visuals` is an optional list (maximum one); old records need no migration.

Export frontend `VisualSpec` as the discriminated union of `SourceVisualSpec`,
`DiagramVisualSpec`, `ComparisonVisualSpec`, `ProcedureVisualSpec` and `PlotVisualSpec`. Internal evidence bindings use the
existing one-based integer cite IDs; API mapping uses their unchanged `cit-N`
equivalents. Do not renumber after filtering citations.

### Task 0: Confirm the text dependency before implementation

**Files:** inspect `study/runtime.py`, `study/claim_generation.py`,
`study/claim_delivery.py`, `pipeline.py`; use existing frozen
`.local/last-completion-pass-20261013/run_after.py` and original questions.

- [x] Confirm production pack default selects `StudyClaimGenerator`, calls `generate_claims -> verify_claims -> deliver_claims` and records the selected draft's delivered/citation IDs. The final draft/report/delivered objects remain available at the visual integration point.
- [ ] Rerun `extra-02,extra-03` into a new results directory with Qwen, hybrid, reranker, NLI and two drafts unchanged; no overwritten before records or question keys.
- [ ] Manually require R3 thresholds 10+/5–9/1–4, counts 33/38/104 and the actual research-frequency/geography bias. Require R2's unproven role, single-cell/TCR/spatial methods, and the proposed clonotype/cancer-cell-killing objective. Refusal, dropped required detail, fallback or runtime/checker failure keeps this gate closed.
- [ ] Record evidence paths and pass/fail in the execution ledger. Do not start Tasks 1–6 while the gate is closed.

Current prerequisite evidence (14 October): 15 claims-format/delivery unit tests
passed. Both live attempts stopped before reranking because available Windows
commit was 788/754 MiB against its 2048 MiB load guard. The second attempt excluded
unused TensorFlow imports; startup improved but memory remained insufficient.
See `.local/visual-outputs-20261014/progress.md`. Task 0 is not passed and no visual
product code has been started.

Later retry with ~7.7 GiB initial commit headroom completed both questions, but
NLI still declined to load with 663/583 MiB available. Manual review also found
missing required details. This is preserved in `gate_20261014_v3/records.jsonl`;
the prerequisite is still closed, despite successful request execution. The
fresh focused contract/completion/resource suite passed 39 tests.

### Task 1: Freeze cases and establish the contract

**Files:** new package `schema.py`, `context.py`; create
`aura_bio_system/tests/test_answer_visual_schema.py`; create
`aura_bio_system/benchmarks/data/visual_output_bank_v1.jsonl` and its manifest.

**Interfaces:** `visual_schema(kind: str) -> dict`;
`parse_visual(raw: str, context: VisualContext) -> VisualSpec`;
`build_visual_context(draft, delivered, evidence) -> VisualContext`.

- [ ] Freeze the spec's 12 cases with `answerable` and `kind` fields and expected source IDs/spans before tuning: 9 positives and 3 negative controls. Add separate SHA256 manifest; do not edit existing figure/document banks. Coverage gate is >=7/9 valid positives, >=1 per kind, all 3 controls correct; omitted/failed/unattempted positives count as failures.
- [ ] Write failing schema tests: `assert parsed.version == 1`; reject 21 nodes, 31 edges, 101 points, duplicate IDs, unknown kinds, NaN, boolean numerics, extra fields and 65537-byte input. `assert set(context.claims_by_id) == set(delivered.delivered_ids)` and reject a removed claim reference even if it existed in the draft.
- [ ] Run `python -m unittest discover -s aura_bio_system/tests -p "test_answer_visual_schema.py" -q`; confirm the missing implementation fails, then implement the interfaces and rerun to PASS.
- [ ] Test unsupported legacy/core contexts explicitly: `assert result.status == 'omitted'`; do not infer retained claims from rendered Markdown.

### Task 2: Ground proposals and isolate failures

**Files:** new `grounding.py`, `planner.py`; modify
`aura_bio_system/src/aura_bio/pipeline.py` at structured delivery,
`aura_bio_system/src/aura_bio/tracing.py`,
`aura_bio_system/src/aura_bio/api/app.py`,
`aura_bio_system/src/aura_bio/api/mapping.py`; create
`aura_bio_system/tests/test_answer_visual_grounding.py` and
`test_answer_visual_api.py`.

**Interfaces:** `ground_visual(spec: VisualSpec, context: VisualContext, verifier) -> VisualResult`;
`plan_visual(kind: str, question: str, context: VisualContext, generator, verifier) -> VisualResult`.
Add request `visual_output: Literal['none','source','diagram','comparison','procedure','plot']='none'`;
store the result in the selected final record before trace persistence.

- [ ] Write failing tests proving two supported entities do not permit an unsupported causal edge; reversed direction and dropped qualifiers fail. `assert result.status == 'omitted'` for an edge referencing a discarded claim or an OCR/VLM-only numeric plot; mixed support never promotes an interpreted element to verified.
- [ ] Add number-binding tests: the same two numbers with swapped group spans must fail; correct label/value/unit bindings pass. Missing units/denominators or different cited populations fail. Do not accept a bare substring match as semantic support.
- [ ] Run the two new test modules with unittest discovery; record RED, then implement a schema-constrained proposal using the existing selected local generator. Check factual edge propositions and numeric bindings against both retained claims and their cited evidence using existing verifier capabilities. If the verifier cannot establish a binding, omit the visual rather than invent a new verifier score.
- [ ] Keep the claim generator schema unchanged. A visual call cannot add claims, restart retrieval or change answer selection. `none` uses zero calls; source display uses deterministic resolution; diagram/comparison/procedure/plot uses at most one constrained layout proposal with no repair. Tables/steppers are rendered deterministically, not as model-authored HTML.
- [ ] Test timeout/malformed output/verification failure at the mapped-answer boundary: `assert result['markdown'] == before['markdown']`, identical confidence/decision, no visual, safe limitation and recorded visual timing/failure. Assert call count `<= 1`, no raw private text in public errors, stable original citation numbering and valid old answer payloads.
- [ ] Rerun both modules and existing `test_claim_delivery.py`, `test_study_pipeline.py` and `test_api.py` to PASS. Do not change answer accuracy or completeness claims based on these unit tests.

### Task 3: Source highlights first

**Files:** new backend `source.py`, new frontend `SourceVisual.tsx` and tests;
reuse `frontend/src/components/study-source.tsx` and `study-crop.tsx`;
create `aura_bio_system/tests/test_answer_visual_sources.py`. Integrate the source
option into `api/app.py`, `api/mapping.py`, `frontend/src/types.ts`,
`frontend/src/pages/AskPage.tsx` and `frontend/src/components/ui.tsx` now, so this
stage is usable before diagram/plot work rather than waiting for Task 6.

**Interfaces:** `resolve_source_visual(spec: VisualSpec, context: VisualContext, store, visual_store) -> VisualResult`;
`SourceVisual({spec,onCitation})` requests only existing authorized asset routes.

- [ ] Write failing tests for foreign-pack asset IDs, expired attachments, purged documents and malformed bboxes: no substitute image and no external URL. A unit/page locator without bbox produces a whole-source preview, never a claimed precise highlight.
- [ ] Resolve original immutable asset/revision and upright bbox server-side under existing leases. Carry generation and provenance. Reuse the current region overlay; do not burn highlights into original images or duplicate assets.
- [ ] Add rotated-source fixture: `assert displayed_bbox == expected_upright_bbox`; unit and original-image buttons must open the same cited revision. Test purge during preview and assert the visible source-unavailable state.
- [ ] Run backend source tests and frontend source/crop tests to PASS. Preserve original file hashes and existing purge/lease tests.

### Task 4: Diagrams, comparison tables and procedure views

**Files:** new `frontend/src/lib/visual-diagram.ts` and tests; new
`DiagramVisual.tsx`, `ComparisonVisual.tsx`, `ProcedureVisual.tsx` and tests; modify `frontend/package.json`,
`frontend/package-lock.json`, `frontend/src/types.ts`.

**Interfaces:** `compileDiagram(spec: DiagramVisualSpec): string`;
`DiagramVisual({spec,onCitation})`, `ComparisonVisual({spec,onCitation})`,
`ProcedureVisual({spec,onCitation})`; trusted label escaping, generated node IDs.

- [ ] Add failing tests: compilation preserves supported edge direction/cycles; label text containing quotes, `%%{init...}%%`, HTML or URLs cannot become directives, tags or links. Renderer error exposes the plain-text description, not raw SVG code. An unmounted/replaced answer ignores late render completion.
- [ ] Pin an exact reviewed Mermaid release and direct SVG sanitizer dependency with lockfile integrity; do not alter unrelated dependencies. Bundle renderer and fonts locally. Configure `securityLevel='strict'`, `htmlLabels=false`, `startOnLoad=false`; generate only trusted flowchart syntax, never accept Markdown code fences as renderable diagrams.
- [ ] Implement local rendering and sanitized inline SVG from trusted compilation only. Reject scripts, event attributes, `foreignObject`, external hrefs/resources and unsafe CSS; allow only internal marker references. Do not bind Mermaid click functions. App-owned delegated mouse/keyboard handlers open citations only for validated node IDs; test unknown IDs have no effect.
- [ ] Test and implement provenance in the drawing: `native_verified` solid, interpreted dashed, OCR/user annotation dotted plus badges. Edge styles use edge support, not the best-supported node. Verify click/keyboard opens the exact supporting passage, and styles survive export without relying on color.
- [ ] Add table tests: a swapped cell binding fails, missing support shows `Not stated in the selected material`, headers/criteria cannot introduce facts, all supported cells open citations. Render accessible deterministic HTML with per-cell provenance.
- [ ] Add procedure tests: source-supported sequence renders numbered steps, a cycle is rejected, unordered/parallel steps are not arbitrarily numbered. Preserve qualifications and citation controls. Do not treat graph `causes` or citation order as `precedes`.
- [ ] Verify flowchart, hierarchy and cycle fixtures fit mobile width, remain zoomable and have descriptions. Run focused Vitest tests to PASS, then `npm run build` from `frontend`.

### Task 5: Plots, with unchanged grounding standards

**Files:** new `PlotVisual.tsx` and tests; extend backend grounding tests.

**Interfaces:** `PlotVisual({spec,onCitation})` consumes backend-validated
`PlotVisualSpec`; data table displays original decimal strings, units and sources.

- [ ] Write failing tests: bar baseline is zero; ordered numeric line x values are required; missing points are not connected; scatter points are not joined; incompatible series units fail. `expect(table).toHaveTextContent('33')` and its matching group/unit; no fabricated points or error bars.
- [ ] Implement with existing Recharts; disable animation for reproducible exports. Use source units/labels and visible provenance, no additional model/numeric transformations. Preserve decimal strings in the table and verify finite conversion before plotting.
- [ ] Run co-located Vitest tests and backend grounding tests to PASS. Confirm chart/data-table/citation agreement with manual fixture review, not only snapshots.

### Task 6: Integrate, export and evaluate

**Files:** new `AnswerVisual.tsx`, `export.ts` and tests; modify
`frontend/src/components/ui.tsx`, `frontend/src/pages/AskPage.tsx`,
`frontend/src/lib/api.ts`, `frontend/src/styles.css`,
`frontend/openapi/aura-bio.openapi.json`, `frontend/src/generated/api.ts`;
create `frontend/tests/e2e/answer-visuals.spec.ts` and
`aura_bio_system/benchmarks/run_visual_output_eval.py`.

**Interfaces:** `AnswerVisual({visual,onCitation})`;
`downloadVisual(spec: VisualSpec, svg: SVGElement): Promise<void>`.
Public schemas match Task 2 exactly. Export SVG/PNG plus provenance JSON locally.

- [ ] Add explicit output selector to Ask; render only final validated payloads, never streamed partial visual JSON. Old text-only answers remain unchanged. A failed visual shows one limitation without suppressing answer text.
- [ ] Write export tests: visible title/source/provenance footer in SVG and PNG; JSON records claim/citation IDs, units and model/prompt version where relevant. Reject unsafe SVG; revoke blobs after use. Browser downloads are explicitly outside future purge control.
- [ ] Add Playwright tests blocking all non-app network requests, malicious diagram labels, mobile readability, citation opening, stale-run replacement and attachment expiry/purge. `expect(externalRequests).toEqual([])` and `expect(previousAnswerVisual).not.toBeVisible()` after replacement.
- [ ] Run `npm test`, `npm run build` and `npm run test:e2e -- answer-visuals.spec.ts` from `frontend`; run new backend modules plus the existing claim/provenance/source/API regressions. All must PASS; inspect rendered fixtures for clipped labels and misleading axes.
- [ ] Preserve Task 0's passing evidence and run the frozen 12-case output manifest; report attempted/completed/failed counts, factual edge correctness, numeric binding/citation/provenance violations and latency separately. Manually review source fidelity and readable rendering; unit tests alone do not establish answer quality.
- [ ] Add evaluator threshold tests: `6/9` valid positives fails; `7/9` passes only with >=1 success per kind, all three negative controls correct and zero grounding/provenance/privacy violations. Unattempted positives remain in denominator. An omitted supported plot cannot be relabelled a control. Output the exact failed gate names and per-kind counts.

### Task 7: Follow-on source-label practice

This follows the three rendering families; it does not delay the source-highlight
release and does not invent a new mastery database.

**Files:** create `frontend/src/components/answer-visuals/SourceLabelQuiz.tsx`
and tests; reuse source OCR metadata and immutable asset IDs; add focused browser
coverage to `frontend/tests/e2e/answer-visuals.spec.ts`.

**Interfaces:** `SourceLabelQuiz({source,ocrWords,onPracticeResult})`;
`onPracticeResult({pack_id,document_id,asset_id,revision_id,label_ids,correct,attempted})`.

- [ ] Test suggestions require confidence >=85 and user confirmation/editing. No OCR means a visible unavailable state and zero background OCR/model calls. Group words without inventing unobserved label text.
- [ ] Test mask locations on upright/rotated assets, non-destructive overlays, answer/reveal/reset and source/pack purge. Before reveal, hidden keys must not appear in rendered alt text/tooltips/ARIA labels. Explain that original access remains possible; this is practice, not exam security.
- [ ] Implement session-only attempt state bound to immutable revision IDs. Normalize case/Unicode/whitespace for matching; accept user correction, do not run hidden LLM grading. Emit the provenance-bearing event but do not claim durable mastery integration exists.
- [ ] Run focused component/browser tests plus source regressions to PASS. Later durable mastery integration requires its own reviewed schema and retention policy.

## Handoff

Execute natively and sequentially under the user override above, to keep context/token use
down. No new agents are needed. Priority is source highlights, diagrams/views,
then plots; all keep the same grounding standards.
Generated illustrations and broad legacy/core integration require separate plans.
