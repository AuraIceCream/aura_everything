# Deep-evidence compression ablation (2026-09-29)

The question IDs were frozen in `diagnostic_15_20260929.txt` before this
ablation. This is a deliberately failure-enriched diagnostic slice, not an
unbiased estimate of accuracy. Internet search was not used.

## Model-free evidence replay

On the 15 questions, the final evidence contained 25/46 answer-key terms not
already present in the question with the current policy, and 28/46 when deep
evidence compression was disabled. Both variants kept the same evidence
selection cap. The three recovered terms were on `bio-0370` (somatic versus
germline editing, 0/2 to 2/2) and `bio-0380` (excitatory versus inhibitory
neurotransmitters, 0/2 to 1/2). Turning off the per-source cap also recovered
terms, but lost one on `bio-0061`; it was not adopted.

Term presence is only a retrieval diagnostic. It does not prove that a passage
supports the answer or that the model uses it correctly.

## Complete-pipeline model run

Both measured variants retained the learned router, dense plus sparse search,
cross-encoder reranking, evidence selection, local Llama 3.2 1B generation,
verification including NLI, external critic, and bounded revisions. The only
accuracy-policy difference was deep-evidence compression. To avoid 4 GiB GPU
out-of-memory failures, these runs placed the dense encoder and Llama on CPU,
used the same 8,192-token context, and asked Ollama to unload after each
request. Device placement makes latency incomparable with previous GPU runs,
but was identical between the two new arms.

The compression-off arm answered all 15 without errors. Under the current
scorer, its mean was **0.5922**. The earlier full-pipeline Llama run on those
same IDs rescored to **0.5945**, so this cross-run comparison shows no overall
gain. The earlier run used a different device setup and stochastic decoding;
it is not a controlled estimate of the toggle's effect.

A matching CPU control was run for the four questions whose evidence actually
changes, plus two unchanged questions. All six control rows completed without
errors. Scores below were recomputed from answer text using the current scorer.

| Question | Compression on | Compression off | Difference |
| --- | ---: | ---: | ---: |
| `bio-0370` gene-editing contrast | 0.50 | 0.75 | +0.25 |
| `bio-0380` neurotransmitter contrast | 0.50 | 1.00 | +0.50 |
| `bio-0061` lac operon | 1.00 | 0.80 | -0.20 |
| `bio-0317` immune memory | 0.75 | 0.75 | 0.00 |

The four affected cases average **0.6875 on versus 0.8250 off**, a +0.1375
diagnostic difference. Among them, two improved, one regressed, and one tied.
Across all six matched questions, including the unchanged controls, the means
were 0.6805 on and 0.6889 off. Both unchanged controls happened to score lower
in the off run, demonstrating material run-to-run variation even when the
toggle cannot change their evidence.

Importantly, the compression-off `bio-0370` answer still incorrectly described
somatic editing as heritable. Its higher keyword score must not be interpreted
as a fully correct biological answer. The current scorer is not a substitute
for a contradiction/faithfulness review.

## Decision

Keep deep compression **on by default**. The opt-in
`--no-compress-evidence` benchmark flag is useful for reproducible ablations,
but this is not sufficient evidence for a global policy change. The only
questions that both gained missing answer terms and improved their matched
scores were two deep compare/contrast items. The untouched 35 of the fixed
50-question bank contain no *deep-routed* compare/contrast items, so they
cannot independently validate a contrast-specific exception. Promoting such
an exception from these two diagnostic cases would be overfitting.

The next accuracy work should target the separately observed retrieval
ambiguity and false-acceptance paths, then validate on the untouched 35. In
particular, `bio-0097` retrieves cross-reactivity passages for a genetics
"test cross" query, although an exact-phrase search of the current core index
returns multiple passages titled **Test cross** at the top. This suggests the
ordinary query relaxation/fusion, not corpus absence, as the retrieval failure
to investigate. `bio-0370` shows that NLI/critic revisions can still leave a
biological contradiction. Do not add internet search until those local failure
modes are addressed and measured.
