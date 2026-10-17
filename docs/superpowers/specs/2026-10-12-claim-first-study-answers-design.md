# Claim-first study answers

Status: approved with the user's four amendments; implementation pending baseline.

## Purpose and constraints

Produce useful, source-aware tutor answers when retrieval succeeds but parts of generation fail verification. Replace prose parsing as the primary grounding contract, without lowering evidence thresholds or promoting visual interpretations to verified facts.

The user approved structured claims, partial tutor answers, bounded visual reinspection and optional outside-material context. Tutor mode is the study default; strict mode remains selectable. Outside-material context is off by default. Thinking remains optional. Local-only processing, exact provider/model selection, explicit GPU starts, cancellation, purge/leases and existing provenance rules remain intact. Do not commit, push, alter original documents, rebuild the original corpus or overwrite existing benchmark results.

## Existing integration points

- `aura_bio_system/src/aura_bio/pipeline.py`: evidence selection, draft/repair selection and whole-answer scope finalization.
- `study/runtime.py`, `study/prompts.py`, `study/verification.py`: private generator setup, pack prompts and claim/source checks.
- `study/provenance.py`: existing claim basis and source-method records.
- `study/visual/jobs.py`, `study/visual/description.py`: checkpointed question-focused figure interpretation.
- `api/app.py`, `api/mapping.py`, `tracing.py`: request validation, answer delivery and audit records.
- `frontend/src/lib/prepare-document-question.ts`, `frontend/src/pages/AskPage.tsx`, `frontend/src/types.ts`: explicit Ask orchestration and presentation.

Keep the core biology benchmark path unchanged. Implement this in focused study modules rather than expanding the shared pipeline with visual-provider logic.

## 1. Structured claim contract

Study model output is a versioned JSON object with a `claims` list and ordered `blocks`. Each claim contains `id`, `claim`, `cite_ids` and optional `depends_on`. IDs are unique within a response. Citations reference the request's numbered evidence, never arbitrary document IDs. Dependencies may reference earlier claims only; reject unknown IDs, duplicate IDs and invalid citations. Cap output at 24 claims, 1,200 characters per claim and 64 KiB total JSON. Ollama receives the JSON schema through its `format` parameter. Validate returned JSON locally as well; fail visibly on invalid/truncated output, without spending generation calls on formatting repair or silently converting to unchecked prose.

The model cannot assign its own verification status or introduce evidence. The verifier consumes each claim and its cited passages directly, without reconstructing claim boundaries from Markdown. Preserve the original claim and all checker results in traces. Numerical claims keep current premise/unit checks. Compound claims must be split or checked in full; partial entailment is not acceptance.

Generate atomic, qualified statements; discourage unrequested counts, causal strengthening and factual headings. Render citations and neutral headings deterministically. Do not run an unchecked prose-polishing pass. Any later generative synthesis must undergo the same checks.

Blocks reference a claim ID or contain a `teaching` template ID. Teaching templates provide transitions, invitations to explain the preceding claim, and source-inspection hints without factual assertions. Free-form teaching prose cannot bypass verification: absence of new numbers/entities does not prove absence of factual content. Templates have no interpolated model text, and blocks referencing removed claims (including their dependent teaching prompts) are pruned. This preserves tutor scaffolding while closing the factual-text loophole.

Extractive mode produces structured claims directly. Legacy prose verification remains available for older traces and the unchanged core pipeline, not as an invisible fallback for malformed study-model output.

## 2. Graded delivery

Request field `answer_mode` accepts `tutor` or `strict`; default is `tutor` for study requests. Unknown values fail validation.

Retain existing detailed basis kinds: native verified, native unverified transcription, VLM interpreted, OCR transcribed and user annotated. UI labels distinguish these; none implies independent truth of the source document. Unsupported, contradictory, invalid and dependent-on-removed claims are excluded from tutor delivery. A visual label alone is not permission to keep an invented detail: existing interpretation alignment checks still apply.

Tutor mode returns useful surviving claims and a deterministic notice when some requested material could not be confirmed. It records omitted claim IDs/reasons and delivered claim counts. Do not display unsupported claim text as a supposed fact. If no useful claim survives, return insufficient support. Strict mode refuses when unresolved blocking claims remain. Retrieval success alone never forces an answer.

Dependency pruning is transitive. Neither strict nor tutor mode may retain a conclusion whose declared premise was removed. Since models can omit dependencies, require each surviving claim to have its own supporting citations; dependency validation is an additional check, not a substitute.

Delivery statuses distinguish complete supported, complete interpreted/transcribed, partial and insufficient. Keep original candidate failures separate from final delivered-answer verification. Recompute final citation/provenance accounting from delivered claims; never attach the unfiltered draft's successful metrics to a shortened answer. Benchmark reports include completeness, omission and refusal rates alongside support quality so dropping everything cannot improve the score artificially.

## 3. Bounded look-again

Only figure-scoped questions with an explicit Ask action are eligible. After initial claim checking, a missing question-relevant visual detail can create a targeted reinspection request against the already selected crop. Arbitrary unsupported biology claims must not trigger a visual call. Default budget is one additional visual call per answer; maximum two, explicitly configurable. Structural repair calls count toward that additional-call budget. Exhaustion is visible and proceeds to graded delivery, not an unbounded retry.

The targeted prompt is neutral: ask for visible labels/connections relevant to the user's question without supplying a rejected claim, expected answer, presumed arrow direction or gold key. Same-model agreement is never evidence of independent confirmation.

Use the same explicitly selected provider/model and existing GPU preflight, source snapshot, image limits, thinking configuration and checkpoint machinery. Local Ask consent does not grant hosted consent. Never switch providers/models or unload unrelated models. Busy GPU, timeout, failure and cancellation are visible, preserving completed checkpoints. Cancellation prevents a later answer from mounting into a new question.

Orchestrate reinspection outside the text-generation inference reservation: finish/release that phase, run the visual job, wait for its index generation, then reacquire answer resources. Do not recursively start a visual job while holding its inference lock. Recheck pack availability and source/crop identity at every boundary.

Store the targeted question, parent request/claim IDs, source/crop hash and new VLM revision. Retrieval reserves this newly indexed evidence. Recheck affected claims and dependencies within the existing answer budget. Repeated readings by the same model remain VLM interpretations, never independent confirmation; pixel-derived numbers remain unverified. Raw image attachment to the final text generator is deferred in favour of this bounded route.

## 4. Optional outside-material context

Request field `outside_context` accepts `off`, `corpus` or `model`; default is `off`. Expose a deliberate UI choice. Selecting one source does not authorize another or any internet/hosted request.

`corpus` runs a separate read-only retrieval over the existing biology corpus and renders a separately cited section headed `Beyond your materials — biology corpus`. Do not merge corpus passages into pack evidence or reuse ambiguous citation identifiers. Corpus absence/failure is visible without preventing the pack answer.

`model` uses a separate local background prompt and renders `Beyond your materials — model background, not source-verified`. Do not feed private pack excerpts/images into that background prompt; send the user's question and explicitly selected scope only. This section has no invented citations or verified badge. A failed optional section never causes provider fallback.

Both remain separate structured sections in API output and traces. Neither rescues failed pack claims, changes pack grounding/confidence or counts as grounded benchmark credit. Entirely absent pack support can coexist with a visibly separate opted-in background section, but must still report insufficient pack support. Source-pack lifecycle rules govern the containing run and any derived context.

## Verification and rollout

Implement sequentially: structured contract/checking, graded delivery/API/UI, look-again orchestration, then optional context. Write regression tests first and observe their expected failures. Test real production boundaries, using fake model/provider responses only where inference would otherwise be required.

Required controls: malformed/oversized JSON; dangling citations/dependencies; preserved negation/qualifiers; compound claim rejection; mixed native/VLM sources; visual invention despite an interpreted label; OCR number uncertified; unsupported dependency pruning; zero surviving claims; strict refusal; non-factual deterministic headings; partial-answer provenance; look-again call-budget exhaustion; busy GPU and cancellation; purge during reinspection; stale indexed revision; outside-context default-off; disjoint corpus citations; uncited model context never earning pack credit.

Freeze a diverse local evaluation manifest and expected source facts before prompt tuning: direct native facts, qualifications, procedures, comparisons, multi-unit answers, figures with omitted/ambiguous relationships, numeric figure controls and unsupported questions. Run that manifest on the current production pipeline before changing production behaviour, including the previous Fig. 2 refusal. Preserve existing figure/study banks and original keys. Record evaluated subset, exact configuration and hashes. Report coverage and latency as well as grounding; do not infer full-bank scores from completed subsets. If hardware prevents baseline inference, report the blocker and do not pretend an archived trace is the requested fresh baseline.

Run the full backend suite, frontend tests and production build after integration. Run a small real-model end-to-end comparison only after checking GPU availability; include previous refusal as a regression case, not the sole tuning target. Passing deterministic tests does not establish visual accuracy or justify claiming that all document questions work.

## Design review

This preserves the existing source separation and safety checks while changing how supported material is delivered. All four requested changes are included. Implementation details, test ownership and exact orchestration interfaces belong in the implementation plan after this design is approved. No implementation or model runs have occurred for this change yet.
