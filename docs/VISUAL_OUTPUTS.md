# Grounded answer visuals

In **Ask**, select study material and choose **Answer visual**. Text-only remains
the default. **Off — text only** disables visual planning. **On — automatic**
lets the pipeline infer whether a source view, diagram, comparison, procedure or
plot materially helps, including indirect requests. It may choose no visual for
a simple answer or insufficient support; this is a normal decision, not an error.
Existing explicit output choices remain manual overrides.

Auto uses the question, retained checked claims and original cited evidence,
not a keyword-only router. Selection and any layout are returned together in
one constrained local call, with no extra decision/repair call. Source choices
reference bounded app-assigned candidates; the model cannot supply a foreign
path, crop or URL. The trace records requested mode, selected kind and a bounded
reason code. A normal no-visual decision does not render an unavailable warning.

Explicit source highlights need no extra model call. Diagram, comparison,
procedure and plot proposals use at most one schema-constrained call to the
already selected local model; there is no repair loop or provider/model switch.
Visual failure or omission leaves the checked text answer, confidence and
decision unchanged.

## What each view does

- **Source highlight:** opens the cited immutable unit and existing owned image.
  Only stored upright regions are highlighted. A page/unit without a region is
  labelled whole-source or unit-only; it is not a precise claim highlight.
- **Diagram:** locally bundled Mermaid renders app-compiled graph data, not
  arbitrary model Mermaid/SVG/code. Click or keyboard-activate a node to inspect
  its citation. Version 1 accepts complete retained relationship propositions;
  unsupported paraphrases, reversed arrows and dropped qualifications are omitted.
- **Comparison:** deterministic accessible tables. Absent cells say **Not stated
  in the selected material**, not an inferred negative. Version 1 transcribes
  complete simple group/attribute/value propositions; ambiguous or qualified
  projections are omitted rather than silently strengthened.
- **Procedure:** only an explicit source ordering permits numbered steps.
  Parallel/unspecified order stays unnumbered; cycles are rejected.
- **Plot:** native, source-checked observations with exact group/value/unit spans.
  Pixel/OCR/annotation-only numbers are declined. Bars include zero, numeric line
  x values are ordered, missing observations are not connected and scatter points
  are not joined. Direct group/value/unit phrases establish the numeric binding,
  not mere co-occurrence in a sentence. Axis and series names are neutral app
  labels; source units and original decimal strings remain in the table.

Solid borders/edges mean source-checked, dashed means interpreted, and dotted
means transcribed/annotated. These are source-support distinctions, not proof of
independent scientific truth. The drawing itself and exports carry the labels.

## Exports and label practice

Download SVG, PNG or a JSON provenance manifest explicitly. Exports include title,
source references and per-element support/citation labels, not just a generic
legend; no public share link is created.
Downloaded files cannot be recalled by later pack deletion. No extra copy of a
user pack image is persisted merely to render an answer.

**Practice labels** uses existing OCR boxes only. Suggestions require confidence
at least 85 and explicit user confirmation/correction. Cropped OCR boxes map back
to the upright source image. Confirmed keys are not put in hidden alt text,
tooltips or accessibility labels before reveal. Practice has answer/reveal/reset
controls and session-only results bound to source and OCR revision IDs. It is not
a secure exam; the original remains accessible. It starts no OCR/model job and
does not claim a durable mastery database or verified biology.

## API and boundaries

The run request accepts `visual_output`:
`none | auto | source | diagram | comparison | procedure | plot`.
Final answers may include `visuals`, at most one `{status, spec, limitations,
metadata}` result. Answers without eligible checked claims remain text-only with
a limitation when a visual is requested. Partial visual JSON is
never rendered. Source assets retain existing pack leases, expiry and purge rules.
Auto and manual layouts also support core biology-corpus answers through a
visual-only adapter. It consumes only the selected final report's NLI-supported,
inline-cited native claims, with the original evidence numbers; it does not
regenerate the answer, move core teaching to the source-only document prompt,
or promote lexical overlap/uncited memory. Rejected/partial claims, stale reports,
refusals and OCR/VLM/annotation-only evidence cannot supply core visual facts.
Core source-image highlighting requires real owned assets, which the core text
index does not currently provide; no images or locations are fabricated.

No generated Python/JavaScript, arbitrary SVG/HTML, model URLs, cloud upload,
automatic vision job, unit conversion, interpolation or fabricated measurements
are part of this feature. Conceptual raster illustrations are deferred.

The local layout call copies exact source quotes and, for repeated text, a unique
surrounding source context. The application resolves these to original character
offsets before grounding; it never asks the small model to count characters.
Missing, ambiguous or altered quotes are rejected without fuzzy repair. This
does not relax group/value/unit, retained-claim or provenance checks. Comparison
decoding distinguishes populated `stated` cells from strictly empty `not_stated`
cells. Public visual/export bindings remain `{cite_id, start, end}`.
The optional local layout call has a separate bounded 3,072-token output budget
and 300-second timeout. Compact-layout guidance avoids redundant descriptions
and unnecessarily long quote contexts without dropping required facts or
qualifiers. The answer generator's own budget is unchanged. Length-truncated
JSON is still rejected; there is no automatic repair, retry or model switch.

## Validation

The frozen bank and SHA256 manifest are under
`aura_bio_system/benchmarks/data/visual_output_bank_v1.*`: nine positive cases and
three controls. At least seven of nine manually reviewed valid positives, at
least one per output kind, all controls correct and zero reported grounding,
provenance/privacy violations are required. Unattempted/failed/omitted positives
stay in the denominator. Synthetic fixture success is not real-model accuracy.

Run the fixture harness without starting a model:

```powershell
python aura_bio_system/benchmarks/run_visual_output_eval.py --output .local/visual-eval-new
```

Use a new output directory each time. Synthetic assets are retained there for
review; user packs are not modified. `--reviews review.json` takes explicit
per-case `{ "valid": true/false }` manual reviews. `--model MODEL` explicitly
starts the selected local model for proposal evaluation; it is not the default.
In model mode the nine positives use live proposals; the three frozen bad-layout
controls still test the deterministic guard (`mode=guard_fixture`). Their generic
question text does not ask for the unsupported facts encoded in those layouts,
so they cannot honestly measure model refusal. Real unsupported-question tests
remain separate. All model positives still require manual review.

The user authorized implementation before the pending live text/Ollama regression
was resolved. That result remains pending; neither unit tests nor this fixture
bank are a substitute for final end-to-end model validation.

Known v1 limitation: partial procedures are honestly unnumbered, but the stepper
does not yet draw individual dependency edges. Use the diagram output when the
branch structure matters. This does not invent a total order.
