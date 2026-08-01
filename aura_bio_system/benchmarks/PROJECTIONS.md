# Expected benchmark movement: baseline → full RAG → finetuned + RAG

Grounded in the measured baseline run (441 questions, `aura-bio:v0`, no
pipeline). These are forecasts with stated reasoning, not results.

## Measured baseline

| Metric | Baseline |
|---|---:|
| Overall | 0.822 |
| Concept recall | 0.827 |
| Numeric accuracy | 0.800 |
| Process-order accuracy | 0.833 |
| Forbidden-misconception rate | 0.027 |
| Hallucination rate (adversarial) | 0.375 |
| Median latency | 29.3 s |

## Where the 78.4 lost points actually are

- **243 of 441 questions (55%) already score a perfect 1.0.** Retrieval cannot
  improve these; it can only hold them or damage them.
- Of the remaining loss, **only 3.0 points come from the 8 adversarial items**,
  and 75.4 from concept recall on ordinary questions.
- Sampling the missed concepts: **95% are concrete biological terms**
  (`FADH2`, `proton gradient`, `semiconservative`, `bile`, `Escherichia coli`)
  rather than rubric phrasings. These are exactly what a corpus passage
  supplies, so the gap is genuinely retrievable — verified by inspection, e.g.
  the "seven characteristics of living organisms" answer really did omit
  *respiration* and *excretion*, and the model-organism answer never named
  *E. coli* at all.
- Only 13 missed concepts are wording of my own rubric that retrieval cannot fix.

So the addressable pool is real, but it is capped by a hard ceiling: 55% of the
paper is already full marks.

## Full RAG — expected

| Metric | Baseline | Expected | Confidence |
|---|---:|---:|---|
| Overall | 0.822 | **0.87 – 0.91** | medium |
| Concept recall | 0.827 | 0.87 – 0.91 | medium |
| Numeric accuracy | 0.800 | 0.90 – 1.00 | high |
| Process-order accuracy | 0.833 | 0.92 – 1.00 | high |
| Hallucination rate | 0.375 | **0.00 – 0.13** | high |
| Median latency | 29 s | 60 – 120 s | high |

Reasoning:

- **Hallucination is the surest win.** Adversarial questions name entities that
  do not exist, so nothing in the corpus supports them and the verifier's
  unsupported-claim check fires. Expect 3/8 → 0–1/8.
- **Numeric and process-order are near-certain wins** because they do not
  depend on retrieval at all: the SymPy checker and the step-order checker
  detect the error and the revision loop forces a correction. These are
  deterministic, which is why confidence is high.
- **Concept recall is the uncertain one.** Recovering the addressable gap
  requires retrieval to find the passage *and* the model to actually use the
  term. A realistic joint capture rate is 50–65%, giving +25 to +40 points.
- **Counter-pressure is real.** Grounding instructions make answers terser and
  more citation-bound, which can *drop* concept mentions on the 243 already-
  perfect answers. A 5% regression there costs ~12 points and is the main
  reason the range starts at 0.87 rather than 0.91.

## Finetuned + RAG — expected

| Metric | Full RAG | Expected | Confidence |
|---|---:|---:|---|
| Overall | 0.87 – 0.91 | **0.90 – 0.94** | low–medium |
| Hallucination rate | 0.00 – 0.13 | 0.00 – 0.06 | medium |
| Median latency | 60 – 120 s | unchanged | high |

Fine-tuning mainly buys *behaviour*, not knowledge: citation discipline, stable
answer structure, level adaptation, and refusing when evidence is absent. Those
lift the format-sensitive parts of the score and suppress the last hallucinations.

**The honest caveat:** the gold set yields a few hundred SFT examples, while
SRS 15.4 targets 5,000–20,000. At that size, on a 4B model, expect a modest
gain and a genuine overfitting risk. Do not expect finetuning to add another
0.05 on its own.

## Methodological warning: the benchmark has a ceiling

With 55% of questions already perfect at baseline, the headline mean compresses
real differences between systems. Report **two numbers**:

1. the overall mean, for the SRS 25 table; and
2. the mean over the **discriminative subset** — the 198 improvable questions
   plus the 8 adversarial ones — where the systems can actually separate.

On the discriminative subset the baseline sits near 0.60, so the same absolute
gain shows up roughly twice as large and the comparison is far more readable.
If later runs bunch together, add harder items rather than concluding the
components do not work.
