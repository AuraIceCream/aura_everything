# Evaluation and expansion plan

This plan describes proposed work. It does not claim the experiments, domain
packages, or visual features have been completed. Current measurements and
their limitations are recorded in [FINDINGS.md](../aura_bio_system/benchmarks/FINDINGS.md).

## What to evaluate next

Keep the existing banks for different purposes:

| Asset | Role |
|---|---|
| [441-question biology bank](../aura_bio_system/benchmarks/biology_benchmark.jsonl) | Broad regression coverage across topics and question types. Most questions test established knowledge. |
| [50-question subset](../aura_bio_system/benchmarks/subset_50.txt) | Historical paired comparison and router training holdout. Do not change its membership. |
| [100-question subset](../aura_bio_system/benchmarks/subset_100.txt) | Larger pilot on the same bank; it still has the original bank's limits. |
| [38-question retrieval bank](../aura_bio_system/benchmarks/retrieval_bank.jsonl) | Recorded negative result: the raw model knew most of the supposedly difficult facts. Preserve its pre-registered tags and keys. |

For the next experiment, use **only the existing frozen 50-question subset**.
Do not replace questions or tune prompts against their outcomes. Keep the other
banks as historical and regression assets, but do not run them in this study.
This compact study tests model interchangeability and paired performance on
largely textbook biology; it cannot establish whether retrieval helps on novel,
corpus-specific facts or prove training-data membership. Review automatic
scoring disagreements and citation support manually. A citation's presence
alone does not establish that it supports its claim.

### Two-model experiment

Run two **different model families** through the same two configurations,
yielding exactly 200 answers:

| Configuration | Purpose |
|---|---|
| Raw model | What the generator answers from its own weights |
| Full AURA pipeline | Combined effect of retrieval, routing, reranking, verification, critique if enabled, revision, and tracing |

The current Qwen 3.5 4B model is model 1. Model 2 is `llama3.2:1b` (the
instruction-tuned Ollama tag, about 1.3 GB by default), subject to a short
full-prompt memory and completion smoke test on the 4 GB GPU. Its smaller size
tests whether evidence can help a constrained generator; its different model
family makes the swap more informative than choosing another Qwen variant.
The smaller model may also struggle to follow long evidence prompts, so an
accuracy gain is a hypothesis, not a foregone conclusion. Pin the exact model
digest before running. The historical
`aura-bio:v0` is a Qwen persona build, so do not compare it against an unprompted
Llama as if the only difference were weights: either use the two plain base
tags with the same external role instruction, or give both equivalent persona
instructions, and report which protocol was used.

Use the same question IDs, corpus and index snapshot, generation token budget,
context window, sampling settings, and hardware-offload policy where those
settings are supported. Keep each configuration's prompt policy fixed across
models; the raw and RAG prompts necessarily differ. Record the actual model
version, quantization, GPU/CPU placement, index manifest, component switches,
latency, and errors in each run. The current baseline runner defaults to 800
output tokens while the full runner defaults to 1024; align them before a new
comparison. A second Ollama model tag tests interchangeability **within the
Ollama adapter**. A
different provider requires another `Generator` implementation and is a
separate portability claim. Changing the *embedding* model requires rebuilding
the dense vectors and index; hold it fixed for this experiment.

For the full configuration, explicitly enable the intended dense channel,
reranker, entailment checker, and critic consistently, or report any omitted
component as an ablation. Inspect the stored trace and run the existing liveness
check: a component that loads but never fires cannot count as tested.

Report paired differences within each model, then check whether the direction
and failure modes repeat across models. Two successful model families show
portability for those families; they cannot establish that every model will
benefit. Show overall/concept scores, citation support, unsupported claims,
refusal and numerical results where the 50 items provide examples, and latency
separately. Include confidence intervals and per-question disagreements, but
label small-category results as descriptive. Use full-pipeline traces to
diagnose losses; these four runs alone cannot attribute gains or losses to an
individual stage.

### Can we tell whether a model trained on the corpus?

Usually not from a black-box model. A correct unaided answer could come from
pretraining, another source, or reasoning; it is not evidence that the exact
corpus document was in training. Use model-card cutoff information when
available, and label the inference as uncertain. Better controls are private
or newly authored passages with arbitrary but coherent facts, post-cutoff
documents, and counterfactual updates whose answer is changed only in the
retrieved document. Compare closed-book and evidence-conditioned answers, and
verify the cited passage actually supports the answer. These controls test
whether the model *uses supplied evidence*; they still do not prove training
membership for the original corpus.

### Effort estimate

The four configurations × 50 questions mean **200 answers**. Budget roughly
**one machine day** for runs, warmups, and any failed-item reruns, and **one to
two person-days** to align settings, inspect traces, review disagreements,
and write the report. These are planning ranges, not measured project timings;
the exact runtime depends on offload, context length, optional critic calls,
and reruns. The historical corrected Qwen pair was 0.8757 raw vs. 0.9030 full
pipeline overall, a +0.0273 paired difference with a 95% CI crossing zero.
Historical runner settings differed, so the Qwen pair must be rerun under the
same settings as the new comparison.

## Why curriculum-aware retrieval matters

The existing findings include a case where the baseline gave an NCERT-style
list of life characteristics and retrieval steered the pipeline toward a
different, valid Campbell-style list. The scorer expected the former. This is
neither a simple retrieval miss nor a hallucination. The route already captures
learner level, but retrieval does not consistently use a curriculum preference.

Adding more famous sources alone is not the fix: the corpus already spans
multiple source families, and a bigger unqualified pool can increase conflicts.
Start with one or two suitable, licensed curriculum sources. Tag passages with
source, curriculum, edition/year, and level; let a learner select a curriculum
or leave it unspecified; then filter or boost matching passages during evidence
selection. When no curriculum is specified and sources disagree legitimately,
the answer should name the conventions and cite both. Test this on a small
labelled set of conflicting terminology and syllabus questions before changing
global source weights. The benchmark key must accept defensible alternatives
unless a curriculum was explicitly part of the question.

## What can become a domain package

The present pipeline has useful boundaries but is not yet a runtime plugin
system. A first extraction should keep orchestration, traces, canonical text
evidence, search interfaces, model invocation, and revision control in a core
package. The biology package should provide its router taxonomy and patterns,
prompts, ontology authorities, source mappings/parsers, deterministic biology
checks, and evaluation bank. Some components are mixed today: `AuraBioPipeline`
constructs `QueryRouter` and `BiologyVerifier` by default, and the retrieval
store has special PubMed handling. Those are explicit refactor points.

The third-party libraries are more general than the checks built around them:
SymPy is a reusable arithmetic/symbolic engine, Pint is a reusable unit engine,
and `periodictable` is a reusable chemistry parser. Their current extraction
rules, formulas, magnitude bounds, and error policy are largely biology-specific.
Biopython sequence operations are reusable across life-science subdomains, but
not a generic law or physics adapter. NLI and provenance checks are broadly
reusable, provided their thresholds and accepted evidence types are validated
for each new domain.

The proof should be a **small second domain**, not a second 35 GB corpus: one or
two source formats, a few dozen documents, a domain prompt/router, one useful
deterministic checker, and 20–30 manually reviewed questions. Run the same
route → retrieve → select → generate → verify → revise → trace path. Only after
that works should package discovery and stable third-party plugin APIs be
promised. Estimate **2–4 weeks** for a credible extraction and vertical slice,
depending on how much of the current biology coupling must be moved.

## Visual input and output

Begin with one workflow: a learner supplies a labelled pathway or textbook
figure, asks a question, and receives an answer tied to the figure and its
source. Store the original image, checksum, license, page/figure ID, crop or
bounding box, OCR/caption text, and any derived embedding as one evidence item.
The verifier should distinguish a statement read from the image from a model
inference about the image. A text-only model can use OCR and captions; a vision
model adapter can inspect pixels directly. Both require separate evaluation.

For output, use **structured artifacts** with citations:

| Need | First implementation | Limitation |
|---|---|---|
| Quick relationship or sequence | Mermaid or SVG rendered by the frontend from a validated node/edge specification | Restrict labels and links to safe text; verify content against evidence. |
| Quantitative biology result | Matplotlib/Recharts from verified numeric data | A plot of invented numbers remains wrong, so preserve source values and units. |
| Exact scientific figure | Licensed source image or region crop with an overlay and citation | Requires rights, coordinates, and clear distinction from generated art. |
| ASCII sketch | Text fallback in the answer | Useful for simple explanations, weak for complex figures and accessibility. |
| Generative illustration | Optional, clearly marked conceptual illustration | Never treat it as observed evidence. |

For a simple process diagram, the LLM should return a typed node/edge JSON
artifact rather than executable drawing code. The server checks its schema,
node and edge limits, label text, and supporting evidence IDs. A frontend
converter escapes labels and builds Mermaid flowchart syntax; Mermaid lays out
the graph and renders SVG in the browser. Clicking a node can show its source
passage. This is the narrow first renderer, not a general scientific drawing
engine: spatial anatomy, molecular structure, and richly branching pathways
need separate figure or graph renderers. Avoid executing model-written Python
or JavaScript to produce figures. The existing Recharts components only render fixed dashboard
charts; the answer API does not yet accept images or return visual artifacts.
Estimate **1–2 weeks** for a narrow diagram-output slice and **2–4 weeks** for
figure input with traceable regions and a small visual evaluation set. General
microscopy or histology interpretation is a separate, larger project.
