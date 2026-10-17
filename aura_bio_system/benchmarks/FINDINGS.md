# What measuring this pipeline actually showed

Written 2026-07-30. Every number here was produced by a script in this
directory and can be reproduced from the stored answers. None is recalled.

The short version: **the local model is not the weak link.** A 4B biology model
already knows 87.8–95.6% of what this benchmark asks for and refuses
false-premise questions 7 times in 8. Retrieval cannot beat memory at recalling
memorised biology, and three separate attempts to find headroom converged on
the same answer. That is the most useful thing this project has measured, and it
should change what the system claims to be for.

---

## 1. The bare model already knows the material

Three independent measurements, each on a different question set.

| Measurement | Set | Result |
|---|---|---|
| Concepts named unaided | original 441-question bank, 50 sampled | **87.8%** |
| Concepts named unaided | bank written to be hard for a 4B model | **95.6%** |
| Adversarial questions correctly refused | 8 planted non-existent entities | **7 / 8** |

The second is the striking one. A 38-question bank was written specifically to
ask for things a small model was expected to approximate: the σ factor and the
`TATAAT`/`TTGACA` promoter consensus sequences, `MCM`/`ORC`/`Cdc6`/`Cdt1` origin
licensing, caspase-9 versus caspase-8, PEP carboxylase in mesophyll versus
bundle sheath, leghemoglobin shielding nitrogenase, the chloride shift,
FG-nucleoporins and the Ran gradient. Answer keys were written before looking at
what retrieval returned, and ten control questions on core textbook material
were included to catch a rigged bank.

The bare model scored **0.955 on the 28 "hard" questions** and 0.975 on the
controls, naming 130 of 136 required concepts. The maximum possible gain for any
pipeline on that bank was **+0.0395**.

The selection hypothesis was simply wrong, and is reported as wrong rather than
replaced with a bank that cooperates.

### The ceiling, measured

Over 50 representative questions and 188 required concepts:

| | coverage |
|---|---:|
| Present in the retrieved evidence | 0.878 |
| Known by the bare model | 0.878 |
| Named by the full pipeline | 0.878 |
| **Union of evidence and memory** | **0.936** |
| In evidence but missing from the answer | 0.059 |
| Known by the model but dropped by the pipeline | 0.048 |
| In neither | 0.064 |

A perfect pipeline could beat the raw model by under six points here. The two
systems overlap on ~82% of concepts. Retrieval's unique contribution is the
~5.8% the model does not already hold.

The middle rows are the diagnosis: the pipeline **adds 5.9% from evidence and
loses 4.8% from memory**, which nearly cancel. That is why three very different
systems all land on 0.878.

---

## 2. The published hallucination rate is a scorer artifact

The project's headline number, a 0.375 hallucination rate, is used to argue
that the model's failure is behavioural and that fine-tuning should start with
refusal examples. Reading the eight answers rather than the scores:

| System | scored as hallucinating | **actually fabricates** |
|---|---:|---:|
| baseline | 3 / 8 | **1 / 8** |
| full pipeline | 3 / 8 | **1 / 8** |

The scorer marks an adversarial question hallucinated unless the answer contains
one of three literal markers: `no such`, `does not exist`, `not a recognised`.
The bare model answers *"The 'Golgi mitochondrial bridge organelle' does not
exist as a recognized biological structure"* and the pipeline answers *"There is
no biological entity known as…"*. Both refuse. Only one phrasing matches.

The genuine failures are one each: the baseline invents a mechanism for the
"Hensen-Baxter law", the pipeline invents the "Krebs-Watson cycle".

**There was never much hallucination headroom for retrieval to capture.**

---

## 3. Where the pipeline does earn its place

Not recall. Three things the accuracy number cannot show:

**Deterministic verification.** Recomputation, not an LLM judge (SRS 31 Risk 4
warns against the latter). SymPy re-derives arithmetic. Biopython checks codons
against the genetic code, complements and GC content. `periodictable` balances
stated equations by element. `pint` catches a resting potential given in volts.
A table of pathway constants catches a wrong net ATP yield. Measured across
**537 real generated answers these raise zero false blocking errors**.

The numerical checker is the one component with a large, reproducible accuracy
gain: **+0.200 on numerical questions**.

**Contradiction detection that works.** `Support.CONTRADICTORY` had been in the
schema from the start, was read by two call sites, and was **never once
produced**. The old checker compared token overlap, which measures topical
proximity, not agreement. An answer stating the opposite of its evidence scored
as well supported. That is why the accept/revise signal came out *inverted*:
answers the verifier accepted scored 0.041 **below** the bare model while
answers it flagged scored 0.015 above.

Replacing it with NLI entailment, on the twelve labelled critic cases:

| | planted contradictions caught | false alarms on sound answers |
|---|---:|---:|
| token overlap | **0 / 7** | 0 / 5 |
| NLI entailment | **5 / 7** | 0 / 5 |

The two misses are correct: a reversed process order and a level mismatch are
not factual contradictions, and the process-order checker and the external
critic catch them respectively.

**Provenance.** The bare model states `TATAAT` as confidently as the pipeline
does. Only the pipeline can show which passage says so. Claim citation rate,
citation validity and unsupported-assertion rate are now recorded for every
answer. This is a capability the baseline scores zero on at any accuracy.

**The external critic.** Never executed before this session. The key was
present in `.env` and nothing ever called `load_dotenv()`, so `critic_from_env`
read an empty environment and every run silently used `critic=None`. Measured on
the twelve labelled cases:

| | decision accuracy | false accepts | false revises |
|---|---:|---:|---:|
| deterministic verifier alone | 0.750 | — | — |
| GLM-4.7-flash critic | **0.917** | 1 | **0** |

Its one miss is a false accept on the hallucinated organelle, the dangerous
direction, and the reason `combine_decision` lets a critic only ever be
*stricter* than the verifier.

**The learned router.** The hand-written rules route subdomain adequately and
learner level not at all: they answer `high_school` at confidence 0.2 for 439 of
441 benchmark questions, because real questions rarely announce a level. Since
level selects the prompt's `LEVEL_GUIDANCE`, every postgraduate question was
being answered in "define each term on first use" school framing.

Frozen SapBERT and BGE embeddings plus TF-IDF n-grams, reduced by SVD and fed to
a grid-searched linear head, on 391 questions with 50 held out and never seen:

| dimension | classes | rules (macro F1) | learned (macro F1) |
|---|---:|---:|---:|
| learner level | 6 | 0.030 | **0.412** |
| biology subdomain | 18 | 0.417 | **0.699** |
| task type | 8 | 0.656 | **0.711** |

**The selection metric was wrong, and it cost real answer quality.** This is the
most instructive error here, because balanced accuracy is a standard and
normally sensible choice.

The search originally selected on balanced accuracy, reasoning that plain
accuracy rewards answering `undergraduate` for everything (197 of 441). Sound
reasoning, wrong remedy: balanced accuracy is macro *recall*, the mean of the
per-class recalls, with no precision term at all, so predicting a rare class
more often than it occurs is free. The classifier learned exactly that. On 50
held-out questions whose true level is postgraduate or research **nine** times,
it predicted one of those **22** times: 16 wrong escalations against 3
de-escalations.

That is not a cosmetic mislabel, because learner level reaches the prompt
twice. `POSTGRADUATE` guidance says *"be concise and rigorous"*, and
postgraduate/research also promotes the teaching mode to `RESEARCH`, which
replaces guided explanation's multi-step structure with one terse instruction.
Escalated answers came back **32% shorter** and named fewer scored concepts. The
routing metric improved from 0.200 to 0.479 while the answers got worse.

The costs are asymmetric in a way the metric could not see: escalating a
school-level question suppresses content the key requires, while de-escalating a
postgraduate one merely over-explains. Re-selecting on **macro F1**, still
equal-weighted per class but charging for the false positives balanced accuracy
gave away, fixes it:

| selected on | exact level | predicts advanced (true: 9) | wrong escalations |
|---|---:|---:|---:|
| rules | 4/50 | 0 | 0 |
| balanced accuracy | 14/50 | 22 | 16 |
| **macro F1** | **27/50** | **11** | **8** |

Exact agreement nearly doubles and the model becomes roughly calibrated.
Subdomain is unchanged. Task type moves by less than 50 questions can resolve.

The lesson generalises: a metric chosen to correct one bias introduced another,
in the opposite direction and invisible to itself. Only looking at what the
component did *downstream* exposed it.

Two integration bugs are worth recording, because in both the model was fine and
the *plumbing* silently discarded it, which looks identical to a model that does
not work.

First, `sklearn.base.clone` rebuilds an estimator from its constructor arguments
for every grid candidate and every fold, discarding instance state, so each of
several hundred fits reloaded a 400 MB SentenceTransformer and re-encoded from
scratch. This is not a pickling problem and `__getstate__` does not help, because
`clone` never pickles. Moving the vector cache to module level fixed it: 200
clone cycles now take 0.00s.

Second, and more instructive: the router consults a classifier only where its
*rules* are unconfident, then discards any answer that does not out-confidence
the rule. That is the right conservatism for an unvalidated LLM classifier, but
it makes a **confidently wrong** rule unreachable. Task type showed *exactly*
0.606 with and without the trained model, because the rules were confident, so
it was never asked, despite scoring 0.723 on the same questions when queried
directly. The fix is to make the gate a measurement rather than a threshold:
training records the rules' balanced accuracy alongside the model's, and a
model may overrule a confident rule only on dimensions where it was measured
clearly better. An unmeasured model, and the LLM classifier, keep the old
behaviour.

**Entity authority.** 135,941 names from Gene Ontology, MeSH, Reactome and the
encyclopaedia index answer "is this a real thing?" offline. Judging a
**question** it identifies **all 8 fabricated entities with a 0.7% false-alarm
rate over 433 real questions**. Judging an *answer* it warns about once per
answer, including on real terms the corpus files under another title, so the
answer-side checker ships disabled and the question-side signal ships on.

---

## 3b. Verification, not generation, dominated latency

Timing a real request end to end put the cost somewhere nobody had guessed:

| stage | time | share |
|---|---:|---:|
| routing | 0.2s | — |
| retrieval | 2.6s | 1% |
| rerank | 10.4s | 3% |
| generation | 56.5s | 17% |
| **verification** | **258.8s** | **79%** |

Generation is the expensive-looking step and it was not the problem.
`entail_claims` compares each claim against its highest-overlap passages, which
means every pair carries a *different* premise. The scorer's only entry point
took one premise and many hypotheses, so calling it per passage ran one forward
pass per pair and `batch_size` never engaged: 18 claims × 4 passages was 72
single-item forward passes at roughly 3.6s each.

Restructuring the loop into rounds — round *r* scores every still-unsettled
claim against its *r*-th passage, in one batch — preserves the original early
exit (a claim stops as soon as one passage supports it) while letting every
claim in a round share a forward pass. Measured **7.3x faster with byte-identical
output**: same labels, same chunk ids, same probabilities to 1e-4.

The general point is the same one this file keeps making: the slow component
was not the one that looked slow, and only measuring per stage showed it.

---

## 4. Method notes, including two mistakes worth recording

**Benchmark leakage, twice.** Tuning a prompt against failing questions slid
into copying their answer keys. A "use canonical terminology" instruction named
*a chloroplast's double membrane* and *homeostasis as a stable internal
environment*, both `must_include` phrases of the very questions being fixed. A
refusal instruction spelled out *"there is no such thing and it does not
exist"*, which are the scored markers for all eight adversarial questions. Both
were removed and an audit added that checks every injected prompt string against
every `must_include` and `must_avoid`, ignoring common instruction English.

Part of a previously reported gain was leakage. After removing it the pipeline
scored **below** the baseline, and that is the honest number.

**Validate on real output, not paraphrases.** Every new checker was run over 537
stored answers before being trusted. The first pass raised three issues and *all
three were false positives*: `CONTAINING` read as a nucleotide sequence, "47
chromosomes" flagged inside a Down syndrome explanation where 47 is correct, and
"starts at ATG … ends at a stop codon" read as "ATG is a stop codon". Synthetic
tests had passed all three.

**Scorer defects, all symmetric.** `_present` missed plural forms, so
`hydrogen bonds` did not satisfy a key of `hydrogen bond`, costing 3.3% of all
key phrases across the baseline run. Both gradings are reported side by side,
since correcting it lifts the baseline more than the pipeline and therefore
*narrows* the gap.

Three more of the same kind were found by asking, of every concept the scorer
called missing, whether the answer really lacked it. Most did not:

| defect | example | recovered (baseline / pipeline) |
|---|---|---:|
| markup inside a key phrase | `**allele** frequency` vs key `allele frequency` | 1 / 1 |
| British vs American spelling | key `depolarise`, answer "depolarizing" | 6 / 2 |
| hyphen vs space | key `R group`, answer "R-group" | 5 / 1 |

A key compiles to `allele\s+frequenc…`, which cannot match across `**`. The keys
were written in British spelling and the model answers in American. And
`R-group` is the near-universal written form of `R group`. None of these is a
disagreement about biology. Together they recover 11 of 1,680 baseline phrases
and 3 of 188 pipeline phrases, and break none, verified by checking that no
phrase which matched before stops matching.

Two live regressions were traced to their causes rather than aggregated away,
and neither is what it first looked like. Both answers were much shorter than
the baseline's, which suggested brevity was costing concepts. It was not.

* "Define homeostasis" lost the key `regulation` because the pipeline wrote
  *regulatory mechanisms*. The concept is plainly present. This is the stemming
  case again, and it is left unfixed on purpose.
* "List the seven characteristics shared by all living organisms" lost
  `nutrition`, `respiration` and `excretion` because the pipeline answered with
  the **Campbell** list (order, sensitivity, adaptation, energy processing)
  while the key expects the **MRS GREN** list the NCERT syllabus teaches. The
  bare model, answering from memory, produced the curriculum's list. Retrieval
  steered the pipeline to a different and entirely correct taxonomy that the
  key does not accept.

The second is a real finding about retrieval rather than a scoring artifact,
and it is not fixable by naming the expected list in the prompt: that is
exactly the leakage recorded above. It belongs to curriculum-aware retrieval,
which the learner-level router now makes possible but does not yet use.

Stemming was **not** added. "divergent" still fails a key of `diverge`, and that
is left standing: a scorer that guesses at word senses stops being reproducible,
which is the one property SRS 24 actually wants from it. `AURA_SCORER_STRICT=1`
still reproduces the pre-2026-07-29 grading exactly, normalisations included.

The corrections raise both systems, which is the point: they fix the
measurement rather than favour a system. On the 50-question subset:

| | concept recall | overall |
|---|---:|---:|
| baseline | 0.8857 | 0.8757 |
| full pipeline | 0.9130 | **0.9030** |
| difference | +0.0273 | +0.0273 |

The difference is **not statistically resolved at this sample size**: paired
SD 0.175, 95% CI [−0.021, +0.076], 38 of 50 questions scoring identically.
Resolving a gap this size needs ~157 questions.

**Configuration that silently skewed a comparison.** `run_baseline.py` always
passed `num_gpu: 99`, `OllamaGenerator` never did, so Ollama split the model
53%/47% onto CPU and the baseline generated at 19.6 tok/s against the pipeline's
9.2. The two systems also ran at different `num_predict`. Neither difference had
anything to do with retrieval.

---

## 5. What this means for the project

Stop claiming that retrieval improves accuracy for this model on this material.
The measurements refuse that claim, and a reader who checks will find they do.

The defensible claim is narrower and more interesting: **a local-first biology
tutor where arithmetic is machine-verified, contradictions against sources are
detected, false premises are caught against a 136k-entity authority, and every
statement can be traced to the passage it came from**, at 4 GiB of VRAM and a
35 GB corpus.

Evaluate it on those axes. Recall is saturated. Provenance and verification are
not.

---

## Reproducing

```bash
python aura_bio_system/benchmarks/rescore.py results/<run>.jsonl --suffix .strict.jsonl
python aura_bio_system/benchmarks/compare_subset.py --ids-file subset_50.txt results/*.jsonl
python aura_bio_system/benchmarks/report_bank.py
python aura_bio_system/benchmarks/run_critic_eval.py
python aura_bio_system/benchmarks/run_routing_eval.py --dimension level --ablate

# Did every stage actually run, or did something load and stay silent?
python aura_bio_system/benchmarks/check_liveness.py results/<run>.jsonl

# Which concepts does the pipeline lose that the bare model already had?
python aura_bio_system/benchmarks/analyse_dropped.py \
    results/baseline_aura-bio_v0.jsonl results/full_rag_subset50.jsonl

# Two runs, one scorer, with a confidence interval rather than a bare mean.
python aura_bio_system/benchmarks/compare_runs.py results/a.jsonl results/b.jsonl
```

`check_liveness.py` exists because the trained task-type router was loaded,
reported healthy, and never consulted, and neither the unit tests nor the
accuracy number could see it. `compare_runs.py` prints an interval because the
difference between any two of these systems is usually not resolvable at fifty
questions, and a bare mean invites reading noise as a result.
