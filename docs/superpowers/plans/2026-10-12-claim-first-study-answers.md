# Claim-first study answers implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver useful claim-checked tutor answers without citation-parser mismatches or hidden source mixing.

**Architecture:** Preserve shared retrieval and core biology behaviour. Add study-specific claim generation/checking/delivery, then explicit visual continuation and separate optional background sections.

**Tech Stack:** Python, Ollama schema-constrained chat, existing SQLite/FAISS study stores, FastAPI/Pydantic, React/TypeScript.

**Spec:** `docs/superpowers/specs/2026-10-12-claim-first-study-answers-design.md` (approved with four amendments).

## Global constraints

- No commits, pushes, stashes, resets, deletion of existing work or changes to original corpus/documents.
- Work in the existing checkout: the requested features build on its uncommitted code.
- Baseline on the frozen manifest must finish before production behaviour changes.
- Tutor default, strict selectable, outside context off by default, one additional visual call by default and maximum two.
- Schema-constrained generation with local validation; no formatting repair call.
- Teaching templates only; factual teaching content must be a verified claim.
- Preserve source methods, question/crop snapshots, pack leases, explicit inference starts and exact providers/models.
- No GPU model starts while busy; no external upload or unrelated model unload.

## Review focus

1. An unsupported premise disappears but its conclusion survives: transitive dependency pruning plus independent support.
2. A factual sentence hides in teaching: only closed templates can bypass checking.
3. Reinspection deadlocks while answering owns inference: phase release before visual start, cancellation/lease tests.
4. Partial answers inherit unfiltered success metrics: separate draft/delivered reports and coverage denominators.
5. Optional background becomes pack evidence: disjoint sections, citations, verifier accounting and default-off tests.

### Task 1: Freeze and run baseline

Files: create `aura_bio_system/benchmarks/claim_delivery_bank.jsonl`, a local-source manifest and `run_claim_delivery.py`; tests in `tests/test_claim_delivery_eval.py`.

Interfaces: a checkpointed before/after runner calling the existing pack pipeline, with fixed questions, selected figures, source/config/code hashes and non-overwriting output.

- [ ] Test resume refusal on manifest/config changes and retention of completed cases.
- [ ] Run tests red, implement runner, run green.
- [ ] Freeze literal expected concepts/controls from native sources; capture current-pipeline baseline when GPU preflight passes.
- [ ] Record completeness, refusals, errors and timing; manual semantic review remains distinct from keyword coverage.

### Task 2: Structured claims and teaching blocks

Files: create `study/claims.py`, `study/claim_generation.py`; modify `study/verification.py`, `api/generation.py`, `study/runtime.py`; tests in `tests/test_study_claims.py`.

Interfaces: `claim_schema()`, `parse_claims(raw, evidence_count)`, `StudyVerifier.verify_claims(claims, evidence, route, question)`, and a study generator adapter with a structured generation method.

- [ ] Test constrained transport payload, local bounds, bad citations/dependencies, arbitrary teaching rejection, intact qualified claim boundaries and derived provenance.
- [ ] Observe red, implement minimal behaviour, run green plus existing study/generation tests.

### Task 3: Graded delivery and presentation

Files: create `study/claim_delivery.py`; modify `pipeline.py`, `api/app.py`, `api/mapping.py`, `tracing.py`, frontend types/AskPage; regression tests in `tests/test_claim_delivery.py` and frontend AskPage tests.

Interfaces: `answer_mode=tutor|strict`, deterministic blocks with claim statuses, omitted IDs/reasons and final delivery accounting.

- [ ] Test mixed surviving claims, transitive pruning, full refusal, strict behaviour, teaching anchoring and final metrics.
- [ ] Observe red, implement scoped structured path without changing core/prose compatibility, run green.

### Task 4: Neutral look-again continuation

Files: create `study/look_again.py`; modify private request orchestration and visual job/config integration; tests in `tests/test_study_look_again.py`.

Interfaces: bounded continuation metadata identifying existing crop/question, neutral target prompt, one-call default/two maximum, checkpoint/readiness gating.

- [ ] Test neutral prompt excludes rejected claims/gold expectations, call exhaustion, cancellation, purge, busy GPU and no inference-lock recursion.
- [ ] Observe red, implement reuse of existing jobs/index publication, run green.

### Task 5: Optional outside context

Files: create `study/outside_context.py`; modify request validation/mapping and frontend settings/display; tests in `tests/test_study_outside_context.py`.

Interfaces: `outside_context=off|corpus|model`, separately labelled API sections with disjoint citations and no pack metric credit.

- [ ] Test default-off no access, corpus-only access, model prompt privacy, explicit errors and unchanged pack verification.
- [ ] Observe red, implement bounded local sources, run green.

### Task 6: Verification

- [ ] Full backend tests, frontend tests, production build and distinct code review pass.
- [ ] Repeat the same frozen manifest after changes, retain before outputs and report actual completed denominators.
- [ ] Report real-model limitations; do not claim all document questions or independent visual verification.
