"""Train and score the learned router (the SRS routing benchmark, finally built).

The handoff lists "Routing benchmark: labelled set not built" as an open item.
The labels have existed all along: every question in the bank declares its
``level``, ``task_type`` and ``subdomain``. This trains a hybrid encoder + linear
head on them and reports held-out accuracy against the two numbers that decide
whether it is worth shipping:

* the **rule router**, which manages 0.052 on level and 0.512 on subdomain;
* the **majority-class floor**, 0.447 on level — a router that cannot beat
  "always say undergraduate" is not a router.

Scoring is ``f1_macro``. Plain accuracy would reward predicting
``undergraduate`` for everything, since it is 197 of 441 while ``high_school``
is 23 — so a per-class measure is needed. The first version used
``balanced_accuracy``, which is macro *recall*: it averages per-class recall and
contains no precision term at all, so over-predicting a rare class costs
nothing. The classifier duly learned to, and the damage showed up downstream
rather than in the metric. On 50 evaluation questions whose true level is
``postgraduate`` or ``research`` **nine** times, the balanced-accuracy model
predicted one of those levels **22** times — sixteen escalations against three
de-escalations.

That is not a cosmetic mislabel. Learner level selects the prompt's guidance,
and ``postgraduate`` guidance says "be concise and rigorous" while
``postgraduate``/``research`` also promotes the teaching mode to ``research``,
which replaces guided explanation's multi-step structure with one terse
instruction. Escalated questions therefore came back 32% shorter and named
fewer of the concepts the answer keys score.

``f1_macro`` still weights every class equally, so it keeps the property that
motivated the original choice, but it penalises the false positives that
balanced accuracy gave away free. The cost here is genuinely asymmetric —
wrongly escalating produces a terse answer that drops content, while wrongly
de-escalating produces a verbose one that merely over-explains — so a metric
blind to precision was the wrong instrument.

**Leakage discipline.** The labels come from the evaluation bank, so questions
in ``subset_50.txt`` — the end-to-end evaluation set — are held out of training
entirely. Cross-validation runs over the remaining questions only, and the
saved model never sees an evaluation question. Pass ``--holdout-file`` to change
which set is excluded.

    python aura_bio_system/benchmarks/run_routing_eval.py --dimension level
    python aura_bio_system/benchmarks/run_routing_eval.py --all --save
"""

from __future__ import annotations

import argparse
import json
import os
import time
import warnings
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from aura_bio.env import load_env

load_env()  # HF_HOME lives in .env; must be set before transformers is imported

from aura_bio.evaluation import all_questions  # noqa: E402
from aura_bio.routing import QueryRouter  # noqa: E402
from aura_bio.routing.encoder_router import (  # noqa: E402
    ENCODERS,
    LEVEL,
    SUBDOMAIN,
    TASK,
    CachedEncoder,
    EncoderClassifier,
    RouterModel,
    default_model_dir,
)

#: Which bank attribute supplies the truth for each routed dimension.
DIMENSIONS: dict[str, str] = {"level": LEVEL, "task_type": TASK, "subdomain": SUBDOMAIN}


class _Unusable(Exception):
    """A dimension that cannot be cross-validated; skipped, not fatal."""


def _scratch_dir(name: str) -> Path:
    """A working directory off the system drive.

    joblib memmaps arrays and caches transformers under the temp directory, and
    on this machine that is on a system volume that has run as low as 90 MB
    free -- which surfaced as an opaque ``OSError`` inside a worker rather than
    as a disk-space message. ``AURA_SCRATCH`` overrides.
    """

    root = os.environ.get("AURA_SCRATCH")
    if not root:
        for candidate in ("D:/", "E:/"):
            if Path(candidate).exists():
                root = candidate
                break
    base = Path(root or Path.home()) / name
    base.mkdir(parents=True, exist_ok=True)
    return base


def _transform_cache() -> Any:
    from joblib import Memory

    return Memory(location=str(_scratch_dir("aura-sklearn-cache")), verbose=0)


def _rule_predictions(rules: QueryRouter, questions: Sequence[Any], dimension: str) -> list[str]:
    """What the rule router answers for each question, on one dimension."""

    if dimension == "level":
        return [rules.route(q.question).learner_level.label for q in questions]
    if dimension == "subdomain":
        return [rules.route(q.question).subdomain.label for q in questions]
    return [rules.route_task(q.question.lower()).label for q in questions]


#: Macro F1: every class weighted equally, but unlike ``balanced_accuracy`` it
#: charges for false positives. See the module docstring for why that matters
#: more than it sounds.
SELECTION_METRIC = "f1_macro"


def _macro_f1(truth: Sequence[str], predicted: Sequence[str]) -> float:
    """The rule router measured on the same metric the search selects on."""

    from sklearn.metrics import f1_score

    return float(
        f1_score([str(t) for t in truth], [str(p) for p in predicted],
                 average="macro", zero_division=0)
    )


def _balanced_accuracy(truth: Sequence[str], predicted: Sequence[str]) -> float:
    """Mean per-class recall — the same measure the grid search selects on."""

    from sklearn.metrics import balanced_accuracy_score

    return float(balanced_accuracy_score([str(t) for t in truth], [str(p) for p in predicted]))


def _feature_union(blocks: Sequence[str], encoders: dict[str, CachedEncoder]) -> Any:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import FeatureUnion

    parts: list[tuple[str, Any]] = []
    for name in blocks:
        if name == "tfidf_word":
            # Fitted inside each CV fold, so fold vocabulary never leaks.
            parts.append((name, TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1)))
        elif name == "tfidf_char":
            parts.append((name, TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                                sublinear_tf=True, min_df=2)))
        else:
            parts.append((name, encoders[name]))
    return FeatureUnion(parts)


def _grids() -> list[dict[str, Any]]:
    """A wide search over cheap fits.

    Cheap because a ``TruncatedSVD`` step reduces the feature union to a few
    hundred dense components before the classifier sees it. Without it, the
    char 3-5 gram block alone produces tens of thousands of features and an
    SVC-RBF fit over them takes seconds — 132 candidates x 4 folds then ran for
    814 s on one block set and the process was killed twice before finishing.
    Projecting first makes each fit milliseconds, which is what makes a grid
    this wide affordable at all. The projection is inside the pipeline, so it is
    refitted per fold and leaks nothing.

    ``saga``/``elasticnet`` is dropped: it was by far the slowest candidate and
    on 391 samples never competitive with the plain L2 and L1 fits.
    """

    from sklearn.linear_model import LogisticRegression
    from sklearn.svm import SVC, LinearSVC

    c_wide = [0.001, 0.01, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0]
    weights = [None, "balanced"]
    components = [128, 256]
    shared = {"svd__n_components": components}
    return [
        {
            **shared,
            "clf": [LogisticRegression(max_iter=5000, solver="lbfgs")],
            "clf__C": c_wide,
            "clf__class_weight": weights,
        },
        {
            **shared,
            "clf": [LogisticRegression(max_iter=5000, solver="liblinear", penalty="l1")],
            "clf__C": c_wide,
            "clf__class_weight": weights,
        },
        {
            **shared,
            "clf": [LinearSVC(max_iter=8000)],
            "clf__C": c_wide,
            "clf__class_weight": weights,
        },
        {
            **shared,
            "clf": [SVC(kernel="rbf")],
            "clf__C": [0.1, 1.0, 3.0, 10.0, 30.0, 100.0],
            "clf__gamma": ["scale", 0.001, 0.01, 0.1],
            "clf__class_weight": weights,
        },
    ]


def _block_sets(available: Sequence[str], ablate: bool = False) -> list[tuple[str, ...]]:
    """Feature-block combinations to try.

    Without ``ablate`` only the full hybrid is fitted, which is what you want
    for a dimension you are simply trying to route well. The per-block
    breakdown costs five times as much and is worth paying once, on the
    dimension whose contribution you actually need to attribute.
    """

    everything = tuple(available) + ("tfidf_word", "tfidf_char")
    if not ablate:
        return [everything]
    sets: list[tuple[str, ...]] = [("tfidf_word", "tfidf_char")]
    for name in available:
        sets.append((name,))
    if len(available) > 1:
        sets.append(tuple(available))
    sets.append(everything)
    # Preserve order while dropping any duplicates a single-encoder run creates.
    return list(dict.fromkeys(sets))


def _fit_with_fallback(pipe: Any, texts: list[str], y: Any, cv: Any, jobs: int) -> Any:
    """Grid-search, dropping to serial if a parallel worker gets killed.

    Every loky worker imports sklearn afresh (~300 MB) and holds its own copy of
    the feature matrix. On this 15.7 GB box, running the grid beside a benchmark
    that owns the GPU and a gigabyte of RAM got workers OOM-killed twice —
    ``TerminatedWorkerError`` — losing the whole search each time. Serial is
    slower but uses one process and cannot be killed for wanting memory, so a
    long unattended run finishes rather than dying at hour two.
    """

    from sklearn.model_selection import GridSearchCV

    for attempt_jobs in ([jobs, 1] if jobs not in (1, None) else [1]):
        search = GridSearchCV(
            pipe, _grids(), scoring=SELECTION_METRIC, cv=cv,
            n_jobs=attempt_jobs, refit=True, error_score=0.0,
            pre_dispatch="2*n_jobs",
        )
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                search.fit(texts, y)
            return search
        except Exception as exc:
            if attempt_jobs == 1:
                raise
            print(f"    parallel fit failed ({type(exc).__name__}); retrying serially",
                  flush=True)
    raise RuntimeError("unreachable")


def evaluate(dimension: str, texts: list[str], labels: list[str], blocks_available: list[str],
             encoders: dict[str, CachedEncoder], folds: int, jobs: int,
             ablate: bool = False) -> tuple[Any, dict[str, Any]]:
    from sklearn.model_selection import GridSearchCV, StratifiedKFold
    from sklearn.pipeline import Pipeline

    counts = Counter(labels)
    # StratifiedKFold needs every class present in every fold. A class with a
    # single example cannot be cross-validated at all — the benchmark has one
    # `research_paper` question — so drop those rather than abort the whole
    # run, and say which. Reporting balanced accuracy over the classes that
    # remain is honest; refusing to report anything is not.
    singletons = sorted(label for label, count in counts.items() if count < 2)
    if singletons:
        print(f"  note: dropping single-example class(es) {singletons} — cannot cross-validate")
        keep = [index for index, label in enumerate(labels) if label not in singletons]
        texts = [texts[index] for index in keep]
        labels = [labels[index] for index in keep]
        counts = Counter(labels)
    if len(counts) < 2:
        print(f"  skipped: {dimension} has fewer than two usable classes")
        raise _Unusable(dimension)

    y = np.asarray(labels)
    usable = min(folds, min(counts.values()))
    if usable < folds:
        print(f"  note: smallest class has {usable}, reducing folds {folds} -> {usable}")
    cv = StratifiedKFold(n_splits=usable, shuffle=True, random_state=20260729)

    results: list[dict[str, Any]] = []
    best_overall: tuple[float, Any, tuple[str, ...], dict[str, Any]] | None = None
    for blocks in _block_sets(blocks_available, ablate):
        from sklearn.decomposition import TruncatedSVD

        pipe = Pipeline(
            [
                ("feats", _feature_union(blocks, encoders)),
                # Handles sparse TF-IDF and dense embeddings alike, and refits
                # per fold so nothing leaks across the split.
                ("svd", TruncatedSVD(n_components=128, random_state=20260729)),
                ("clf", None),
            ],
            # The featurisation and projection depend only on the fold and the
            # component count, not on which classifier is being tried, but
            # without caching sklearn recomputes them for every candidate --
            # roughly 720 SVD fits instead of 8. The cache lives off the system
            # drive, which has repeatedly been the binding constraint here.
            memory=_transform_cache(),
        )
        started = time.perf_counter()
        search = _fit_with_fallback(pipe, texts, y, cv, jobs)
        elapsed = time.perf_counter() - started
        name = "+".join(blocks)
        print(f"  {name:<46} {SELECTION_METRIC}={search.best_score_:.4f}  "
              f"({elapsed:.0f}s, {len(search.cv_results_['params'])} candidates x {usable} folds)",
              flush=True)
        results.append({
            "blocks": list(blocks),
            "cv_score": round(float(search.best_score_), 4),
            "best_params": {k: str(v) for k, v in search.best_params_.items()},
            "seconds": round(elapsed, 1),
        })
        if best_overall is None or search.best_score_ > best_overall[0]:
            best_overall = (float(search.best_score_), search.best_estimator_, blocks, search.best_params_)

    assert best_overall is not None
    score, estimator, blocks, params = best_overall
    return estimator, {
        "dimension": dimension,
        "n_train": len(texts),
        "classes": len(counts),
        "folds": usable,
        "best_blocks": list(blocks),
        # Named for what it is rather than for the metric it used to be: this
        # is whatever SELECTION_METRIC measures, and the metric travels with it
        # so a stored report can never be read against the wrong scale.
        "selection_metric": SELECTION_METRIC,
        "best_cv_score": round(score, 4),
        "best_params": {k: str(v) for k, v in params.items()},
        "ablation": results,
    }


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Train and score the learned router")
    parser.add_argument("--dimension", choices=sorted(DIMENSIONS), action="append",
                        help="repeatable; defaults to level only")
    parser.add_argument("--all", action="store_true", help="every routed dimension")
    parser.add_argument("--holdout-file", type=Path, default=here / "subset_50.txt",
                        help="ids excluded from training so end-to-end eval stays clean")
    parser.add_argument("--encoders", default="sapbert,bge",
                        help=f"comma-separated from {sorted(ENCODERS)}")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--jobs", type=int, default=4,
                        help="parallel fits. Each loky worker imports sklearn afresh "
                             "(~300 MB); -1 on this 12-core box spawned 12 of them and "
                             "the OS killed one mid-search")
    parser.add_argument("--ablate", action="store_true",
                        help="fit every feature-block combination, not just the full "
                             "hybrid, to attribute each block's contribution")
    parser.add_argument("--save", action="store_true", help="persist the fitted router")
    parser.add_argument("--model-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=here / "results/routing_eval.json")
    args = parser.parse_args(argv)

    dimensions = sorted(DIMENSIONS) if args.all else (args.dimension or ["level"])

    questions = all_questions()
    holdout: set[str] = set()
    if args.holdout_file and args.holdout_file.is_file():
        holdout = {
            line.strip()
            for line in args.holdout_file.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        }
    train = [q for q in questions if q.id not in holdout]
    print(f"{len(questions)} questions, {len(holdout)} held out for end-to-end eval, "
          f"{len(train)} used for router training\n")

    wanted = [name.strip() for name in args.encoders.split(",") if name.strip()]
    unknown = [n for n in wanted if n not in ENCODERS]
    if unknown:
        raise SystemExit(f"unknown encoders {unknown}; choose from {sorted(ENCODERS)}")
    encoders = {name: CachedEncoder(ENCODERS[name]) for name in wanted}
    texts = [q.question for q in train]
    for name, encoder in encoders.items():
        started = time.perf_counter()
        encoder.warm(texts)
        print(f"encoded {len(texts)} questions with {name} "
              f"({ENCODERS[name]}) in {time.perf_counter()-started:.0f}s")
    print()

    rules = QueryRouter()
    report: dict[str, Any] = {"held_out": sorted(holdout), "dimensions": {}}
    models: dict[str, RouterModel] = {}

    for dimension in dimensions:
        labels = [getattr(q, dimension) for q in train]
        counts = Counter(labels)
        majority = max(counts.values()) / len(labels)
        if dimension == "level":
            rule_hits = sum(1 for q in train if rules.route(q.question).learner_level.label == q.level)
        elif dimension == "subdomain":
            rule_hits = sum(1 for q in train if rules.route(q.question).subdomain.label == q.subdomain)
        else:
            rule_hits = sum(1 for q in train if rules.route_task(q.question.lower()).label == q.task_type)
        rule_acc = rule_hits / len(train)

        # Every metric, so the comparison is like for like. Macro F1 is the
        # selection criterion; balanced accuracy is kept alongside it because
        # earlier results are quoted in it and dropping it would make them
        # incomparable. A constant predictor scores 1/n_classes on balanced
        # accuracy, not the majority share, so quoting the majority share
        # against a per-class score would understate the model.
        truth = [getattr(q, dimension) for q in train]
        predicted = _rule_predictions(rules, train, dimension)
        rule_balanced = _balanced_accuracy(truth, predicted)
        rule_macro_f1 = _macro_f1(truth, predicted)
        print(f"=== {dimension} ({len(counts)} classes) ===", flush=True)
        print(f"  rule router      plain={rule_acc:.4f}  balanced={rule_balanced:.4f}  "
              f"macro_f1={rule_macro_f1:.4f}", flush=True)
        print(f"  constant predictor plain={majority:.4f}  balanced={1/len(counts):.4f}", flush=True)
        try:
            estimator, summary = evaluate(
                dimension, texts, labels, wanted, encoders, args.folds, args.jobs,
                ablate=args.ablate,
            )
        except _Unusable:
            report["dimensions"][dimension] = {"skipped": "fewer than two usable classes"}
            continue
        summary["rule_accuracy"] = round(rule_acc, 4)
        summary["rule_balanced_accuracy"] = round(rule_balanced, 4)
        summary["rule_macro_f1"] = round(rule_macro_f1, 4)
        # The score the model must beat, on the metric it was selected by.
        summary["rule_selection_score"] = round(rule_macro_f1, 4)
        summary["majority_floor"] = round(majority, 4)
        summary["balanced_floor"] = round(1 / len(counts), 4)
        beats = summary["best_cv_score"] > max(rule_macro_f1, 1 / len(counts))
        summary["beats_floors"] = bool(beats)
        print(f"  -> best {summary['best_cv_score']:.4f} {SELECTION_METRIC} on "
              f"{'+'.join(summary['best_blocks'])}  "
              f"{'BEATS' if beats else 'DOES NOT BEAT'} both the rules "
              f"({rule_macro_f1:.4f} on the same metric) and a constant "
              f"predictor ({1/len(counts):.4f})\n",
              flush=True)
        report["dimensions"][dimension] = summary
        # Written after every dimension, so a failure late in the run cannot
        # discard the dimensions that already succeeded.
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        models[DIMENSIONS[dimension]] = RouterModel(
            dimension=DIMENSIONS[dimension],
            estimator=estimator,
            labels=tuple(sorted(counts)),
            blocks=tuple(summary["best_blocks"]),
            cv_score=summary["best_cv_score"],
            # Carried into the saved model so the runtime router can tell,
            # per dimension, whether this classifier earned the right to
            # overrule a confident rule. Both numbers come from the same
            # training split, so they are comparable.
            rule_score=rule_macro_f1,
            params=summary["best_params"],
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")

    if args.save:
        directory = args.model_dir or default_model_dir()
        path = EncoderClassifier(models).save(directory)
        print(f"saved router -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
