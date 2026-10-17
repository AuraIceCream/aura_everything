# Execution ledger — plan: 2026-10-12-claim-first-study-answers.md

User approved the design with constrained decoding, teaching blocks, fresh baseline before implementation and neutral look-again prompts, and explicitly requested implementation.

Ruling: execute in the existing dirty checkout without commits or worktree creation — required study code is uncommitted and the user requested this folder and no commits — cost: no Git checkpoint; preserve existing files and use narrow patches.

Ruling: use closed teaching templates instead of entity/number heuristics — those heuristics cannot prove that a sentence has no factual assertions — cost: less free-form teaching prose until a separately checked expansion exists.

Pre-flight: claim checking feeds delivery, delivery flags feed look-again, and optional background remains outside both; shared interfaces must preserve structured provenance and scope. Task 1 gates all production behaviour edits.

Task 1: preparing frozen baseline; GPU currently around 20% utilisation despite no loaded Ollama model. No production behaviour changes yet.

Task 1: frozen seven-case bank and checkpointed evaluation runner created. Three evaluator regression tests observed RED then GREEN (3/3). Prepared claim-contract and delivery tests observed RED and retained under the local evaluation's planned-tests folder; they are not added as known failures to the active suite while baseline is blocked.

Baseline attempt 1: production answer preflight blocked at 3552 MiB free / 16% utilisation, before any answer generation. Baseline attempt 2: CPU embedding/reranker warmed before GPU preflight; blocked again with busy_gpu, 0/7 completed. Machine has no loaded Ollama model; no process was unloaded, provider changed or GPU threshold lowered.

Ruling: stop before production behaviour changes — user explicitly required a fresh completed current-pipeline baseline first — cost: implementation awaits GPU availability. Existing archived Fig. 2 traces are not substituted for the requested baseline.

GPU startup diagnosis: Windows counter samples identify Codex copy-engine activity (~14%) while compute/3D engines are idle. NVIDIA aggregate utilisation (~16%) incorrectly trips the launch guard. Narrow resource-monitor correction excludes measured copy-engine traffic on single-NVIDIA Windows hosts, retains all other engines and falls back conservatively when counters fail. VRAM thresholds, loaded-model restrictions and answer behaviour are unchanged. New baseline output directory required because source code hash changed; old blocked attempts retained.

Baseline restarted under `.local/claim-delivery-eval-20261012-idle-check` (session 23600). Four GPU-counter regression tests and three vision-provider tests pass. Live GPU check reports ~1.3% non-copy utilisation before launch; subsequently Ollama confirms qwen3.5:4b loaded (3,266,450,553 bytes VRAM), NVIDIA utilisation 100% with 170 MiB free, demonstrating generation is active. No claim-delivery behaviour changes until this seven-case baseline finishes. Prior blocked outputs remain untouched.
