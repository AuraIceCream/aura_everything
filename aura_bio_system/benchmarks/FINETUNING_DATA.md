# How much fine-tuning data, and of what kind

Short answer: **1 GB is the right size for the wrong job.** Two different
training regimes are being conflated, and the benchmark gap needs the smaller
one.

## The two regimes

| | Continued pretraining (DAPT) | Instruction tuning (SFT) |
|---|---|---|
| Input | raw prose | question/answer pairs |
| Teaches | domain vocabulary and facts | format, citation, refusal, level |
| Size | 100 MB – 10 GB | 5,000 – 20,000 examples (20–80 MB) |
| SRS | 11.2, optional | 15.4, the actual target |

`aura-process build-training-corpus` produces the **first** kind. The gold set
(`benchmarks/gold/gold_answers.jsonl`) is the seed for the **second**.

## Why 1 GB of DAPT is the wrong lever here

Measured on this corpus: **~4.1 characters per token**, so

- 1 GiB of text ≈ **262 million tokens**
- 900 MB ≈ 230 million tokens

Throughput for a 4B model with QLoRA:

| Hardware | Rough rate | 262M tokens, 1 epoch |
|---|---:|---:|
| GTX 1650 (4 GB) | ~200–400 tok/s | **~10–15 days** continuous |
| Kaggle T4 (16 GB) | ~1,500–2,500 tok/s | **~30–48 h** (≈2 weeks of quota) |

That is the cost. Now the benefit: the baseline already scores **0.822** and
answers **55% of questions perfectly**. The model is not short of biology
knowledge. Its measured failures are behavioural:

- **hallucination 0.375** — it invents confident answers for entities that do
  not exist;
- missing specific terms on questions it otherwise answers well.

Continued pretraining on more biology prose does not teach a model to say "that
enzyme does not exist". Refusal, citation discipline, and level adaptation are
learned from *demonstrations*, which is SFT. Spending two weeks of GPU quota on
DAPT to move a metric that is already saturated is the wrong trade.

## Recommendation

1. **Start with SFT, ~5,000–20,000 examples (20–80 MB).** Build it from the 125
   corpus-verified gold answers plus generated variants, and — critically —
   **include explicit refusal examples**, since hallucination is the largest
   measurable gap. A few hundred examples is enough for a first LoRA; expect
   overfitting risk below ~1,000 on a 4B model.
2. **Then measure.** Run the benchmark against the SFT adapter before
   considering DAPT at all. If concept recall moves but hallucination does not,
   the refusal examples need work — not more raw text.
3. **Only then consider DAPT, and cap it at 200–400 MB** (50–100M tokens),
   which is roughly one Kaggle week. Use it if, and only if, the benchmark
   shows knowledge gaps that retrieval cannot close.

If you want the full 900 MB – 1 GB regardless, the tool produces it; the
command is in the README. Treat it as a domain-adaptation experiment with a
known multi-week cost, not as the path to a better benchmark score.

## What the filter actually does

Retrieval and training want different things. A UniProt record is fine evidence
and terrible training prose — train on it and the model learns to emit
field-value dumps. So selection is by *teaching register*, not coverage:

- **structured record sources excluded** (UniProt, GO, MeSH, Reactome) — 5.7M
  chunks that would otherwise dominate any budget;
- **topical relevance required.** This mattered more than expected: a first pass
  filled up with biologists' *biographies* ("Biography, Distinctions, Order of
  Merit") and clinical *systematic reviews*, both excellent prose teaching no
  biology. Adding a biology-vocabulary density check rejected ~19,000 such
  chunks per 20 MB selected;
- **per-document cap**, because reference works repeat a template across
  thousands of near-identical entries (one monograph per radioligand);
- **weighted source mix**, because equal round-robin handed the corpus to
  PubMed — 26M single-chunk abstracts that never exhaust — while textbooks, the
  register a tutor should learn, contributed least.

Every rejection is counted by reason in the manifest, so a selection can be
audited rather than trusted.

## A limitation of the corpus itself

The intended prose mix weights textbooks most heavily, because that is the
register a tutor should learn. At 300 MB the actual mix cannot reach it:

| Source | Target | Actual at 300 MB | Why |
|---|---:|---:|---|
| Wikipedia | 30% | ~43% | large and clean |
| PMC / PubMed | 30% | ~47% | effectively unlimited |
| NLM LitArch | 26% | ~8% | most of it is clinical reviews, filtered out |
| LibreTexts | 14% | ~1% | only 6,515 chunks exist in total |

**The corpus is short of textbook prose**, and no amount of weighting invents
more. If tutor register matters for the fine-tune, that is an acquisition gap
to close (more open textbooks) rather than a filtering parameter to adjust. At
smaller budgets the mix is closer to target, because the scarce sources are not
yet exhausted — a 100 MB selection is more textbook-weighted than a 300 MB one.

## Question-answer records

`--qa-fraction 0.30` fills 30% of the budget with QA-formatted records, from
three provenances, each marked with `kind`:

| Kind | Count | What it is |
|---|---:|---|
| `gold` | 125 | benchmark answers verified against both the key and the corpus |
| `pubmedqa` | ~723 | expert-labelled research questions with evidence |
| `template` | the rest | questions derived from a chunk's title and section |

Genuine QA is scarce — about 3.5 MB exists against the ~88 MB that 30% of a
300 MB budget requires — so templates fill the remainder. **They teach answer
format and grounding, not reasoning**: a question mechanically derived from the
answer it is paired with cannot supervise inference. Weight or drop them by
`kind`; do not report them as instruction data.

Template generation needed four guards that only real data revealed, each found
by reading the output rather than the counts:

1. **Chemical identifiers** — "what is 1(trans-[123I]iodopropen-2-yl)-4-…
   piperidine?" is a lookup, not a concept.
2. **Publication-type titles** — "Systematic Reviews" is a real NLM LitArch
   title, yielding "what is systematic reviews, and why does it matter in
   biology?".
3. **Source imbalance** — sources were walked in turn, and NLM LitArch never
   exhausts, so **89% of templates came from it** (56,794 of 63,508) while
   Wikipedia and the textbooks barely contributed. Sources are now interleaved
   with quotas favouring tutoring register.
4. **Fixed clinical templates** — GeneReviews repeats the same section headings
   ("Molecular genetic testing", "Risk to family members", "Related genetic
   counseling issues") across ~1,000 rare diseases. Those headings are now
   treated as generic, and a per-document cap stops a single entry emitting the
   same fallback question a dozen times.

The pattern across all four: **a filter that looks right on counts can still be
wrong on content.** Each was caught by sampling actual generated questions.
