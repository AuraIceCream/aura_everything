# Grounded visual outputs — proposed design

Status: approved for implementation. On 14 October the user explicitly requested
visual implementation only, without further Ollama/text-runtime work. This waives
the implementation prerequisite below, not the outstanding text/live release
validation. Preserve the failed-run evidence and do not claim that it passed.

## Intent and scope

Make AURA's study answers easier to understand through source-linked diagrams,
plots and original-figure highlights. Preserve the distinction between a checked
statement, a model's interpretation and an independently established fact.
Use the current claim-delivery and document/figure machinery; do not introduce
a second retrieval pipeline. The first release targets structured study-pack
answers. Legacy/core answers without a retained atomic-claim context remain
text-only, with an explicit limitation when a visual was requested.

The existing output choices remain: ASCII for simple explanations, diagrams for
relationships, plots for supported data, annotated originals for source inspection,
and optional conceptual illustrations later. Add grounded comparison tables and
a numbered procedure view, not just free-form Markdown tables.

Delivery order: shared contract after the prerequisite, then source highlights,
then diagrams (including procedure and comparison views), then plots. Plot
grounding and testing requirements are not reduced by this priority order.

## Selected approach

Use a versioned declarative visual specification, checked on the backend and
rendered by trusted frontend code. Do not execute model-authored Python,
JavaScript, raw SVG, HTML or arbitrary Mermaid. This is preferable to unrestricted
LLM plotting code (execution and grounding risks) or image generation for every
answer (cost, latency and unreliable scientific labels).

Flow: existing retrieval -> checked claims -> retained claims -> optional visual
proposal -> grounding/shape checks -> local rendering -> source controls.

Rendering uses locally bundled Mermaid for bounded graphs and the already
declared Recharts dependency for bar/line/scatter plots. ASCII/text and a data
table are the accessible fallback. No renderer uses a CDN or hosted editor.
Mermaid supports local imports and SVG rendering; it is MIT licensed. See
[usage](https://mermaid.js.org/config/usage.html),
[configuration](https://mermaid.js.org/config/schema-docs/config.html), and
[licence](https://github.com/mermaid-js/mermaid/blob/develop/LICENSE).

## Global constraints

- No commits or pushes. Preserve unrelated work, original uploads and the core corpus.
- Local-first; no additional provider or model switching, cloud upload or GPU job.
- Default `visual_output=none`; explicit options are `source`, `diagram`, `comparison`, `procedure`, `plot`.
- At most one visual and one schema-constrained proposal call per answer; no repair loop.
- Proposal generation reuses the selected local model and think setting, with a 1024-token output cap and a 120-second timeout.
- The checked text answer survives any visual validation, timeout or rendering failure.
- Version 1 limits: 64 KiB JSON, 20 nodes, 30 edges, 3 plot series, 100 points total, 6 comparison columns, 12 comparison rows, 20 procedure steps and 120 characters per label/cell.
- Every factual visual element references retained claim IDs and original citation IDs; omitted claims cannot reappear.
- Provenance remains `native_text`, `ocr`, `vlm` or `user_annotation`, with per-element checking status.
- A VLM description, generated diagram or user annotation cannot verify itself.
- Source support is not independent scientific truth; badges must say what was checked.
- Private visual assets follow the existing pack/attachment access, lease, expiry and purge rules.

## Grounding and rendering requirements

Graph proposals contain nodes, typed edges and retained claim references, not
rendering code. Node labels cannot introduce ungrounded entities. Every factual
edge must be supported by a retained claim and checked against its cited source;
two supported nodes do not establish a relationship. Preserve direction,
negation, uncertainty and association-versus-causation. A visible arrow derived
only from figure interpretation stays interpreted, not an established mechanism.

Plot proposals bind each point's group, value, unit and scope to a retained claim
and an exact cited evidence span. Use decimal strings until display conversion;
reject non-finite values, swapped group bindings, incompatible units and missing
denominators. Version 1 does not invent/interpolate points, convert units, compute
aggregates or infer graph values from pixels. OCR/VLM-only numeric plots are
declined with an explanatory limitation; their original figure remains viewable.
Bars start at zero; lines require ordered numeric x values and do not bridge
missing observations; scatter plots are not joined. Always expose the source data.

Source visuals resolve server-side pack/document/unit/asset IDs, never arbitrary
model URLs or filesystem paths. Reuse upright-coordinate crops and locator
transforms. Display source pixels unchanged with separate highlights and a legend;
do not claim precise region grounding if only a page locator is known.

Comparison headers, row labels and factual cells use retained claims and cited
spans. Missing support is displayed as "Not stated in the selected material",
not an inferred negative. Render deterministically as an accessible HTML table;
no model-authored HTML. Comparison columns must use compatible criteria/units.

Procedure steps preserve source ordering and qualifiers. A `precedes` edge can
justify an order; citation order or page order alone cannot. Cycles/contradictory
ordering cannot be rendered as a linear procedure. Unordered/parallel branches
remain marked as such or use the graph view rather than a fabricated total order.

All diagrams have plain-text descriptions and citation controls. Native checked
support uses solid edges/borders, interpreted support dashed, OCR/user annotations
dotted with an explicit badge. Unsupported edges are absent. These styles appear
in the drawing and exports, not only a legend, and do not claim independent truth.
Clicking or keyboard-activating a node opens its cited passage using app-owned
handlers mapped to validated node IDs, never model/Mermaid URLs or callbacks.
Compile only approved graph data into Mermaid, escape labels, disable HTML labels
and Mermaid click actions, and sanitize the returned SVG. Insert only this
trusted-compiled, sanitized SVG; app-owned delegated handlers accept known IDs
only. Arbitrary SVG input, external hrefs, scripts and event attributes are rejected.
Local fonts, no external resources or SVG scripts.
An async result for an old question must never appear in the next answer.

SVG/PNG exports carry title, source references and provenance badges in the visible
artifact, plus a JSON manifest. Exports are explicit local downloads, not public
links. Do not persist extra pack image copies just to render an answer. Files the
user downloads cannot be recalled by a later pack purge; disclose that boundary.

## Release gates and later work

Before visual-output implementation, confirm that production pack answering uses
`generate_claims -> verify_claims -> deliver_claims`, retains the selected draft's
IDs, and records delivered IDs/citation IDs. Then complete and manually review the
two pending frozen text regressions (`extra-02`, `extra-03`) with hybrid retrieval,
reranking, NLI, Qwen and both drafts intact. Execution without required answer
details, fallback, or runtime/checker failure does not pass this prerequisite.
Preserve existing banks and before results; do not weaken criteria to proceed.

Freeze a 12-case output manifest before prompt tuning: 9 answerable cases (3 source
highlights, 2 diagrams covering pathway/cycle/hierarchy fixtures, 1 procedure,
1 comparison, 2 plots) and 3 negative controls (unsupported relation, absent
numeric data, OCR/VLM-only numeric data). Use mixed-document/provenance inputs in
the positive cases. Scatter-specific and additional hierarchy cases also have
deterministic fixtures; the small live bank is not a general accuracy estimate.

Release requires valid, factually/source-faithful visuals on at least 70% of all
frozen answerable cases: **at least 7/9**, with at least one valid output in each
of source/diagram/comparison/procedure/plot. Missing, failed, invalid or unattempted
positive cases stay in the denominator. All 3 negative controls must correctly
decline the unsupported visual while preserving any supported text answer.
Unsupported facts, numeric provenance promotions and private external requests
must each be zero. Report every kind's numerator/denominator and do not relabel
cases after seeing failures. Add adversarial label and expiry/race tests separately.
Check facts, edge direction, units, citations, provenance and readability, not
merely whether a picture rendered.

Local rendering tests need no model; live generation needs the selected model.

## Follow-on source-label practice

After the three main rendering families pass, add an explicit "Practice labels"
action to source figures. Use existing upright OCR word boxes; default suggestions
require confidence >=85, and the user confirms or edits each grouped label/key
before practice. No OCR results means a visible unavailable state, not an
automatic OCR/GPU job. Mask the confirmed regions with separate overlays, retain
arrows/structure, and support answer/reveal/reset without modifying source pixels.

The hidden answer must not leak through alt text/tooltips/accessibility labels
before reveal; provide a clearly described accessible alternative. A quiz is
practice, not secure examination: the original remains downloadable/viewable.
Keys are user-confirmed transcriptions, not verified biological assertions.
Matching initially normalizes case/Unicode/whitespace only; no hidden model
grading. Session attempts bind to immutable pack/document/asset/revision IDs and
expire with the pack. Emit a provenance-bearing practice-result event; durable
mastery scheduling/scoring is a separate integration because no mastery store
currently exists. Do not claim improved mastery from rendering tests.

Defer generated raster illustrations to a separate opt-in feature: conceptual
teaching aids, never evidence, measured plots or fabricated microscopy. Defer
arbitrary plotting code, visual editing canvases, animated diagrams, 3D structures,
internet search and broad core-answer conversion from this release.
