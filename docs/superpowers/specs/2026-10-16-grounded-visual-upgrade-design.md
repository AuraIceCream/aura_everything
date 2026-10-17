# Grounded visual upgrade: source inspection, diagrams and plots

Status: scope approved in chat; this written design awaits user review.
Date: 2026-10-16 (Asia/Calcutta).

## 1. Agreed intent and boundaries

Make the existing referential and diagrammatic pipeline useful and reliable
before attempting newly illustrated anatomical figures or image generation.
The user explicitly deferred labelled cell/leaf illustrations and generated
artwork. This pass covers source-figure interpretation/referencing, richer
relationship diagrams, comparisons/procedures and source-grounded plots.

Keep the existing local model, retrieval, claim delivery and storage machinery.
Preserve Off/Auto/manual choices, optional thinking, original uploads, existing
indices, core corpus and unrelated dirty work. No commits, pushes, downloads,
cloud uploads, provider switches or page/application redesign are authorized.
Renderer changes are in scope; a frontend redesign is not.

No component executes model-written Python, JavaScript, SVG, HTML or Mermaid.
Model output is structured data, independently validated and rendered by app code.
A visual failure must never replace, lower or discard an otherwise checked text
answer. Native text, OCR, VLM and user-annotation provenance remain distinct.

## 2. Evidence motivating the change

- Latest backend regression suite: 858 tests passed in 439.251 seconds, recorded
  in `.local/figure-fix-20261016/backend.log`. Browser fixtures previously passed
  24 desktop/mobile tests; this is not a live-model quality result.
- Frozen live output bank: 12 cases attempted, 3 source views and 1 interpreted
  diagram ready; 1 diagram, 1 comparison, 1 procedure and both plots omitted.
  All 9 positive cases still await explicit manual review; release did not pass.
  The 3 negative controls are authored guard fixtures, not live model refusals.
- Same-pixel figure replay: four descriptions completed, including the three
  former runtime failures. Direct review still found wrong panel ownership,
  omitted table rows, transcription errors and an inferred undrawn arrow.
- That replay supplied pixels but no question, OCR or caption hints. Production
  `VisualJobs` already supplies OCR and caption context and supports question
  focus. A production-parity baseline is therefore required before attributing
  the remaining errors to either the model or missing pipeline functionality.
- `visual_outputs/planner.py` currently asks the model to copy exact quotes;
  `quotes.py` rejects missing/ambiguous copies. Grounding must remain strict,
  but source lookup should not depend on a small model recopying source text.
- `frontend/src/lib/visual-diagram.ts` currently compiles rectangular top-down
  graphs with identical arrow geometry. `PlotVisual.tsx` supports bar, line and
  scatter, but series are separate figures and series identity is not sufficient
  to establish that points may be joined as one trajectory.

Earlier exact-quote Auto failures and memory-deferred full text/core checks are
still outstanding; this design does not relabel them as passing.

## 3. Chosen approach and alternatives

Recommended: extend the declarative pipeline, first fixing evidence binding,
then source inspection, then richer deterministic diagram/plot rendering.
This preserves the safety and ownership machinery already tested.

Prompt-only tuning is a cheaper alternative but cannot recover tiny pixels,
represent missing table structure or improve the renderer's vocabulary.
Unrestricted model drawing/plotting code offers flexibility but creates new
execution and grounding risks. Neither is the chosen approach. A model change
or fine-tuning is not a prerequisite; any later model comparison is explicit.

The implementation stays in the modular local application. No new service or
second retrieval stack is needed.

## 4. Shared immutable evidence references

Build a request-scoped registry from the final delivered claims and their cited
original evidence, never from rejected drafts or uncited model memory.

Each source fragment has an opaque app-assigned ID and stores citation/claim IDs,
source revision/checksum, generation, exact original start/end and text,
provenance, and any owned locator/region. Candidate roles identify entities,
relationships, qualifiers, observations and table fields without certifying them.
IDs are valid only for that immutable request context.

The proposal schema enumerates permitted registry IDs. The model selects IDs
instead of copying quotes or inventing character offsets. The app resolves IDs
to original spans and applies the existing grounding checks. An ID establishes
identity/location, not entailment: a selected value still has to belong to its
selected group, unit, population and retained claim.

Do not use fuzzy quote matching, nearest-entity substitution or generic lexical
overlap as verification. Duplicate source strings keep distinct span identities.
Unknown/stale IDs, foreign citations, omitted claims and cross-pack references
are rejected. A bounded candidate list that cannot cover the question produces
an explicit limit/omission, not a silently incomplete supposedly valid visual.
Limit the registry to 256 fragments and the prompt to the selected model's
remaining context allowance after output and instruction reservations. Select
question-relevant candidates without excluding required claim dependencies;
record truncation/coverage limits. Do not silently raise the model context.

Keep legacy v1 offset-bound specs and archived descriptions readable. Introduce
versioned proposal/visual contracts for new structure; do not reinterpret old
artifacts or silently mutate existing indices. New private traces retain raw
proposals, rejection stage/reason, model identity, prompt/schema versions and
source hashes. Public errors contain no private source text.

## 5. Source-figure inspection and referencing

### Production-parity baseline

Run the existing resolver -> VisualJobs -> indexed evidence -> claim delivery
path with the real question, frozen source, caption and available OCR. Test
the saved failure cases before tuning. Gold keys remain outside inference.
Test direct image questions separately, because they lack native captions.

### Bounded question-directed inspection

Reuse caption anchors, manual crops, stored render transforms and OCR boxes.
Resolve figure/page identity first; never substitute another similarly numbered
figure or a nearby unrelated image. Ambiguous documents/references require a
visible ambiguity result. Pure GET/upload/discovery starts no model work.

On explicit Ask/visual-pass action, retain an overview and select at most two
relevant detail regions. Crop the original owned render before applying the
existing per-input one-megapixel limit; never enlarge a compressed preview and
claim recovered detail. Keep panel IDs, relevant legends, axes and table headers
in the region or as separately owned context. Do not cut through a requested row.
If geometry cannot safely identify a region, offer the original/manual crop
and report the limit rather than inventing panel coordinates.

The optional focused-reading stage has at most two provider calls total per
question, including structural repair, across at most two regions. Its shared
wall-clock budget is 300 seconds, or 600 only when thinking is explicitly chosen.
One region may use an initial call plus one repair; two regions get one call
each. A timeout with unknown completion is never automatically reuploaded.
This is a proposed explicit orchestration budget, not an unbounded retry loop.
Existing standalone ingestion jobs retain their explicit per-figure settings.
An overview reuses available pixels/metadata or cached descriptions; any new
overview VLM call counts toward the same two-call limit. Region selection adds
no separate unconstrained model call.

Use neutral questions, not expected-answer hints. Cache identity includes source
revision, crop transform/hash, question, hints, model digest, schema/prompt version
and thinking configuration. Never mount a result into a newer question.

### Structured descriptions

The new description contract retains the existing overview and adds bounded
panel and table records. Every panel record names its panel ID, owned bbox when
known, exact visible labels, organism/condition only when supported, and
uncertainties. Table records keep header IDs, row IDs, cell text, missing/merged
cell status and their locators together; absent cells are not negative results.

Native captions, OCR transcriptions and pixel interpretations are separate
observations. A caption-supported panel mapping can be cited as native support;
it does not make the VLM's pixel account native-verified. Conflicts are retained
and disclosed, not silently resolved in favor of whichever account sounds better.
VLM/OCR numbers remain uncertified even if their respective checker agrees.

Claims may reference those bounded records. Contradictory assignments for the
same panel/property within one account are rejected or flagged for a bounded
focused read. Unresolved portions are omitted with explanation; supported
portions remain answerable. Generic model confidence is not a verification score.

Source highlights use the most precise stored ownership available: exact region,
panel, table row, whole figure or whole page. They state that precision visibly.
Highlighting a panel is not proof that each assertion about it is correct.
Source pixels stay unchanged; overlays, pointers and legends are separate.

## 6. Rich diagrams, comparisons and procedures

Use retained, supported relationship records and exact source references.
Preserve subject/object direction, negation, modality, conditions and scope.
If a relationship cannot be represented without dropping a qualifier, retain
the text or report an omission; do not strengthen it to make a neat arrow.

Extend the bounded graph contract with presentation orientation, visual roles
and groups. Layout hints such as left-to-right or cyclic arrangement add no
factual claims. Compartment membership, hierarchy, temporal order and feedback
edges do add facts and therefore require their own checked support. Spatial
grouping without evidence uses neutral stage/group labels, not invented biology.

Trusted rendering provides branching pathways, cycles, hierarchies, grouped
stages and parallel procedures. Cycles in a mechanism are allowed; cycles in
a proposed linear procedure are not. Do not invent return edges to close a ring.
Activation, inhibition, association, containment and plain visible connections
have distinct visual semantics, not only different text on identical arrows.
Mermaid remains the bounded graph layout engine; approved SVG markers/shapes are
app-generated, sanitized and local. No free-form model drawing code is accepted.

Keep readable labels, per-element source controls, keyboard access, visible
qualifiers, support styles and provenance-bearing exports. Long labels must not
be cropped to fit. Group legends cannot upgrade interpreted members. Bound node
and edge counts remain explicit; larger graphs use an honest scoped view rather
than silently dropping required elements.

Comparisons reuse bound attributes/cells; procedures reuse explicit ordering
and dependency records. Missing comparison cells say not stated. Parallel steps
remain parallel; citation/page order never establishes experimental order.
App-compiled accessibility descriptions carry the same facts as the drawing.

## 7. Scientifically meaningful plots

Fix the current plot omissions using the shared evidence registry first.
Structured observations bind group/series, quantity, value, unit, population,
independent variable and source provenance. Do not relax numeric/source checks
to make a chart appear. Equivalent syntax such as a native table row must have
explicit cell/header ownership, not the current prose-only adjacency assumption.

Plot multiple comparable series together with distinct styling and legends.
Series identity represents the same entity/condition across observations.
Ordered x alone is not permission to join Group A at time 0 to Group B at time 1.
Separate groups remain separate; uncertain trajectory membership uses unjoined
points or a categorical view. Missing values stay missing and are not bridged.

Add explicitly bound uncertainty bars, heatmaps and distributions. Error bars
must state SD/SEM/CI or the source's actual uncertainty definition; no invented
intervals or conversion of one uncertainty type into another. Heatmap cells
retain row/column/value/unit bindings and a visible color scale; missing cells
are distinct from zero. Distribution plots require actual observations or
source-stated bins; summary means do not justify fabricated sample points.

Use common units, stable series identities, appropriate axis scales and source
tables. Bars retain a zero baseline. Log scales are explicit and reject invalid
values. Do not infer numeric observations from graph pixels, OCR or VLM text.
Existing source figures remain viewable even when numeric regeneration is unsafe.

This pass plots native source observations only. Schemas reserve a distinct
origin field for future calculated/simulated data, but those inputs are rejected
unless a separately approved calculator supplies a reproducible derivation.
No simulations, fitted curves, aggregates, unit conversions or significance
claims are newly authorized by this visual upgrade.

## 8. Runtime, ownership and failure handling

Keep one layout proposal call per answer, currently bounded to 3072 output tokens
and 300 seconds, with no proposal repair or silent fallback. Off starts no output
planning; Auto may select none. Figure understanding requested by the question
is separate from whether answer visuals are displayed. Thinking stays optional.

Use existing resource guards/model-phase ownership. New focused reads must not
overlap memory-heavy model phases; resource failures are visible and recorded.
No unrelated apps/models are unloaded and no pagefile settings are changed.
Core sources without image assets remain ineligible for image highlights.
The core checked-claim adapter remains source-supported only; do not rebuild
claims from uncited prose to gain visual coverage.

Leases, expiry, deactivation and purge cover new crops, records, caches and traces.
Derived crops reference immutable originals and transforms. Purge racing a read
or streamed answer fails closed for private assets without attaching late results.
User-downloaded exports remain outside the pack's deletion boundary, as today.

Record safe reason codes distinguishing intentional no-visual, ambiguous source,
unreadable region, invalid proposal, unbound fact, unsupported numeric origin,
resource deferral and renderer failure. Private diagnostics preserve the actual
cause instead of flattening every failure into a generic omission.

## 9. Delivery stages and validation

1. Evidence registry, safe diagnostics and unchanged-bank production baseline.
2. Referential source inspection, bounded focused reads and panel/table ownership.
3. Diagram semantics, grouping/layouts, comparisons and procedures.
4. Multi-series plot semantics, uncertainty, heatmaps and distributions.

One written implementation plan will cover these stages after design approval.
Do not start subsequent schema families until the shared binding contract is
tested. Keep old before-runs and frozen banks unchanged.

Preserve the original 12-case bank and its gate: at least 7 of 9 positive cases
must produce manually reviewed faithful/readable visuals, at least one in each
kind, with all 3 fixture controls rejected. Pending reviews are not passes.

Before tuning, freeze an additional 30-case extension: 20 answerable cases,
four each for source/diagram/comparison/procedure/plot, plus 10 safety controls.
Include the observed real PDF failures and source-disjoint real examples, not
just invented ORION/VEGA fixtures. Authored synthetic cases establish precise
contracts; real cases measure the model/source path. Report them separately.
Freeze keys, categories, source/crop/model configuration and bank hashes.

Extension gate: at least 70% faithful/readable output coverage overall (14/20),
AND at least 3/4 valid cases in every positive kind (therefore at least 15/20
in practice). Failed, omitted, unattempted and unreadable positive cases stay
in the denominator. All 10 controls must reject the bad assertion or unsafe
visual while preserving any supported text; include live unsupported-question
controls separately from deliberately malformed proposal fixtures.

Manually review label transcription, panel/condition ownership, complete table
bindings, edge direction/modality, numerical identity, trajectory grouping,
units, uncertainty definitions, citation resolution and readability. Automatic
JSON validity is not semantic correctness. Unsupported accepted facts,
numeric provenance promotions, false precision and private external requests
must each be zero on the frozen audited cases, not claimed zero universally.

Regression coverage includes malformed/dangling IDs, duplicate text, stale
generation, partial JSON repair, conflicts, crop transforms, missing/merged
cells, qualified/negated edges, graph/procedure cycles, cross-series line joins,
invented uncertainty, missing heatmap cells, injection, export parity and purge
races. Test full production Ask flows, not only direct FigureDescriber calls.

Run backend, frontend, build, browser and model checks sequentially with separate
logs, per-case checkpoints and explicit quality results. Independent failures
do not stop later independent tests; dependent stages pause with a reason.
Resource-deferred stages remain pending, never silently marked complete.
GPU-free does not establish sufficient Windows commit memory. No reliable ETA
is asserted until the new stage timings are measured.

## 10. Explicitly deferred

New anatomical/cell/leaf drawings, reusable biological illustration component
libraries, raster generation, image-generator provider selection, hosted uploads,
free-form model-authored rendering code, fine-tuning, internet search, 3D figures,
animation, a drawing editor and application-wide frontend redesign.
There is no promise to answer every possible question from any document.
