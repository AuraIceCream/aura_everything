"""A learned router: frozen sentence encoders plus a linear head (SRS 6.1, 9.x).

The rule router in :mod:`aura_bio.routing.rules` classifies subdomain well —
51.2% over 18 classes against a ~5.6% chance floor — but learner level is
catastrophic: it assigns ``high_school`` to 439 of 441 benchmark questions and
agrees with the declared level 5.2% of the time, against a 44.7% floor from
simply always answering "undergraduate". The cause is structural rather than a
bad pattern: :meth:`QueryRouter.route_learner_level` only fires on explicit
markers ("for a Class 6 student") or on advanced-vocabulary weight, and real
questions carry neither, so nearly everything falls through to the
``high_school`` default at confidence 0.2.

That is not cosmetic. Level selects the prompt's ``LEVEL_GUIDANCE``, so every
question was answered with "define each term on first use" school framing
instead of "full technical vocabulary and mechanistic detail" — plausibly
suppressing the very terminology the answer keys score.

**Why frozen embeddings and not fine-tuning.** There are 441 labelled examples
and six level classes, the smallest holding four. Fine-tuning a 150M-parameter
encoder on that will memorise, not generalise, and it would need GPU hours that
compete with benchmark runs. Encoding once and fitting a linear head takes
seconds, is reproducible, and leaves the grid search affordable enough to be
wide.

**Why a hybrid feature space.** A biomedical encoder (SapBERT, trained on
PubMed) and a general one (BGE) disagree usefully, and character/word n-grams
retain the surface cues an encoder smooths away — "briefly", "with reference
to", "derive", "Class 6". Which blocks actually carry signal is measured rather
than assumed; see ``benchmarks/run_routing_eval.py``.

The trained classifier satisfies the existing
:class:`aura_bio.routing.router.LLMClassifier` protocol, so it drops into
``QueryRouter(classifier=...)`` unchanged.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

#: Dimension keys. These are the ``question`` strings ``QueryRouter._ask_llm``
#: passes, so the same object can serve every routed dimension.
LEVEL = "learner level"
TASK = "task type"
SUBDOMAIN = "biology subdomain"

#: Encoders available as feature blocks, both cached under ``HF_HOME``. A
#: biomedical encoder and a general one disagree usefully; ModernBERT was
#: considered and dropped, since its advantages (8192-token context, efficiency
#: at length) are irrelevant for ~20-token questions and it is general-domain
#: where SapBERT is trained on PubMed.
ENCODERS: dict[str, str] = {
    "sapbert": "cambridgeltl/SapBERT-from-PubMedBERT-fulltext",
    "bge": "BAAI/bge-base-en-v1.5",
}


def _device() -> str:
    from ..device import resolve_device

    # CPU by default: the 4 GiB card holds the LLM, and evicting it to encode
    # 441 short questions is a bad trade (the same lesson the reranker taught).
    return os.environ.get("AURA_ROUTER_DEVICE") or "cpu" or resolve_device()


#: Vectors are cached at module level, keyed by (model, text), rather than on
#: the instance. ``sklearn.base.clone`` rebuilds an estimator from its
#: constructor parameters for every grid candidate and every fold, which
#: discards any per-instance state — so an instance cache meant each of several
#: hundred candidate fits reloaded a 400 MB SentenceTransformer and re-encoded
#: from scratch. That is not a pickling problem (``__getstate__`` does not help,
#: because ``clone`` never pickles) and it is why the search died silently even
#: single-threaded. A shared cache survives cloning, so the warm-up done once in
#: :meth:`CachedEncoder.warm` is visible to every clone.
_VECTOR_CACHE: dict[tuple[str, str], np.ndarray] = {}


class CachedEncoder:
    """Encode text with a frozen sentence-transformer, memoised per string.

    Implements the sklearn transformer interface so it can sit inside a
    ``Pipeline`` and be cross-validated without leakage: nothing here is fitted,
    so the same vectors are produced whether a string is in the training fold
    or the held-out one.
    """

    def __init__(self, model_name: str, batch_size: int = 32, device: str | None = None) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.device = device or _device()
        self._model: Any = None

    @property
    def _cache(self) -> dict[str, np.ndarray]:
        """A view of this model's slice of the shared cache."""

        return {
            text: vector
            for (model, text), vector in _VECTOR_CACHE.items()
            if model == self.model_name
        }

    # -- sklearn surface ------------------------------------------------------

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        return {"model_name": self.model_name, "batch_size": self.batch_size, "device": self.device}

    def set_params(self, **params: Any) -> CachedEncoder:
        for key, value in params.items():
            setattr(self, key, value)
        return self

    def __getstate__(self) -> dict[str, Any]:
        """Never ship the model itself to a worker process.

        ``GridSearchCV(n_jobs>1)`` pickles the pipeline into every worker, and
        including the SentenceTransformer means each worker rebuilds 400 MB.
        The vectors travel separately in ``_VECTOR_CACHE``; see
        :func:`warm_workers`.
        """

        state = self.__dict__.copy()
        state["_model"] = None
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)

    def fit(self, X: Sequence[str], y: Any = None) -> CachedEncoder:
        return self

    def transform(self, X: Sequence[str]) -> np.ndarray:
        return self.encode(list(X))

    def fit_transform(self, X: Sequence[str], y: Any = None) -> np.ndarray:
        return self.transform(X)

    # -- encoding -------------------------------------------------------------

    @property
    def model(self) -> Any:
        if self._model is None:
            os.environ.setdefault("USE_TF", "0")
            os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        missing = [
            text for text in dict.fromkeys(texts)
            if (self.model_name, text) not in _VECTOR_CACHE
        ]
        if missing:
            # Reaching here during a grid search means warm() missed something,
            # which is slow enough to be worth noticing rather than absorbing.
            vectors = self.model.encode(
                missing,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            for text, vector in zip(missing, vectors):
                _VECTOR_CACHE[(self.model_name, text)] = vector.astype(np.float32)
        return np.vstack([_VECTOR_CACHE[(self.model_name, text)] for text in texts])

    def warm(self, texts: Iterable[str]) -> None:
        """Populate the shared cache up front so a grid search never re-encodes."""

        self.encode(list(dict.fromkeys(texts)))


@dataclass(slots=True)
class RouterModel:
    """One fitted dimension: the sklearn estimator plus what it was trained on."""

    dimension: str
    estimator: Any
    labels: tuple[str, ...]
    blocks: tuple[str, ...]
    cv_score: float
    #: The rule router's balanced accuracy on the same training split, measured
    #: at the same time by ``benchmarks/run_routing_eval.py``. Stored so the
    #: runtime can decide *from measurement* whether this model is entitled to
    #: overrule the rules, rather than from a hand-set confidence threshold.
    #:
    #: ``None`` means "never measured", which is not the same as zero: a model
    #: saved before this field existed would otherwise look like it had beaten
    #: rules that score 0.0 and would claim every dimension it was loaded for.
    #: Unmeasured models keep the conservative rules-first behaviour.
    rule_score: float | None = None
    params: dict[str, Any] = field(default_factory=dict)

    #: How much better than the rules this model must be before it is allowed
    #: to overrule a confident rule. Both numbers are cross-validated on ~390
    #: questions, so differences of a point or two are noise; a margin this
    #: wide only opens for the large gaps actually observed (level 0.17→0.42,
    #: subdomain 0.51→0.75, task 0.45→0.79).
    SUPERSEDE_MARGIN = 0.05

    @property
    def supersedes_rules(self) -> bool:
        """Is this model measurably better than the rules it would replace?"""

        if self.rule_score is None:
            return False
        return self.cv_score > self.rule_score + self.SUPERSEDE_MARGIN

    def predict(self, query: str) -> tuple[str, float]:
        """Return ``(label, confidence)`` for one query.

        Confidence is anchored on the model's held-out accuracy, not on its
        per-sample posterior, because ``QueryRouter`` compares this number
        against the rule router's own hand-assigned confidence and the two must
        mean the same thing. A rule that has no signal returns 0.2 as a stand-in
        for "guessing"; a six-class classifier's maximum posterior sits near
        0.167 even when its argmax is right, because the grid search selects on
        balanced accuracy and happily picks a heavily regularised model with
        flat probabilities. Comparing 0.167 against 0.2 discarded every correct
        prediction this model made.

        What the router actually needs to know is "how often is this classifier
        right?", which is a property of the model — its cross-validated score —
        modulated by how clearly it separated this particular query. The margin
        between the top two classes provides that modulation without letting a
        flat posterior veto a model measured at several times chance.
        """

        label = str(self.estimator.predict([query])[0])
        separation = 0.5
        scores: np.ndarray | None = None
        if hasattr(self.estimator, "predict_proba"):
            scores = np.asarray(self.estimator.predict_proba([query])[0], dtype=float)
        elif hasattr(self.estimator, "decision_function"):
            scores = np.atleast_2d(self.estimator.decision_function([query]))[0].astype(float)
        if scores is not None and scores.size > 1:
            top, second = np.partition(scores, -2)[-1], np.partition(scores, -2)[-2]
            spread = float(np.ptp(scores)) or 1.0
            # 0 when the top two are tied, →1 when the winner is clear.
            separation = float(np.clip((top - second) / spread, 0.0, 1.0))
        # Never fall below the measured accuracy by more than half: an ambiguous
        # query is still answered by a model that beats the rules on average.
        confidence = float(self.cv_score * (0.5 + 0.5 * separation))
        return label, min(confidence, 0.95)


class EncoderClassifier:
    """Serves trained :class:`RouterModel` instances through the router protocol.

    By default ``QueryRouter`` consults a classifier only where its rules are
    unconfident, then discards any answer that does not out-confidence the
    rule. That conservatism is right for an unvalidated LLM classifier, but it
    silently wasted this one on ``task type``: the rules are *confident* there
    and merely wrong, so the gate never opened and held-out accuracy was
    identical with and without the trained model (0.606 either way), despite
    the model scoring 0.723 on the same questions when asked directly.

    :meth:`supersedes` lets the router make that call from measurement instead.
    A dimension where the model was cross-validated well above the rules is
    answered by the model; a dimension where it was not keeps the old
    rules-first behaviour.
    """

    name = "encoder-router"

    def __init__(self, models: dict[str, RouterModel]) -> None:
        self.models = models

    def supersedes(self, dimension: str) -> bool:
        """May this classifier overrule a *confident* rule on ``dimension``?"""

        model = self.models.get(dimension)
        return model is not None and model.supersedes_rules

    def classify(self, query: str, question: str, labels: list[str]) -> dict[str, Any]:
        model = self.models.get(question)
        if model is None:
            return {}
        label, confidence = model.predict(query)
        if label not in labels:
            return {}
        return {"label": label, "confidence": confidence}

    # -- persistence ----------------------------------------------------------

    def save(self, directory: Path) -> Path:
        import joblib

        directory.mkdir(parents=True, exist_ok=True)
        manifest: dict[str, Any] = {}
        for dimension, model in self.models.items():
            stem = dimension.replace(" ", "_")
            joblib.dump(model.estimator, directory / f"{stem}.joblib")
            manifest[dimension] = {
                "file": f"{stem}.joblib",
                "labels": list(model.labels),
                "blocks": list(model.blocks),
                "cv_score": model.cv_score,
                "rule_score": model.rule_score,
                "params": {k: str(v) for k, v in model.params.items()},
            }
        path = directory / "router.manifest.json"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, directory: Path) -> EncoderClassifier:
        import joblib

        manifest = json.loads((directory / "router.manifest.json").read_text(encoding="utf-8"))
        models = {
            dimension: RouterModel(
                dimension=dimension,
                estimator=joblib.load(directory / entry["file"]),
                labels=tuple(entry["labels"]),
                blocks=tuple(entry["blocks"]),
                cv_score=float(entry["cv_score"]),
                rule_score=(
                    None if entry.get("rule_score") is None else float(entry["rule_score"])
                ),
            )
            for dimension, entry in manifest.items()
        }
        return cls(models)


def default_model_dir() -> Path:
    """Where a trained router lives by default."""

    override = os.environ.get("AURA_ROUTER_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "benchmarks" / "router_model"


def load_default_classifier() -> EncoderClassifier | None:
    """Load the trained router if one has been built, else ``None``.

    Returning ``None`` rather than raising keeps the pipeline runnable on a
    machine where the router has not been trained; ``QueryRouter`` then behaves
    exactly as it did before this module existed.
    """

    directory = default_model_dir()
    if not (directory / "router.manifest.json").is_file():
        return None
    try:
        return EncoderClassifier.load(directory)
    except Exception:
        return None
