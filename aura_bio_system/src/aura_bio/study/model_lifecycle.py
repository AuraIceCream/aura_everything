"""Cache stable model owners, not permanently resident CPU retrieval weights."""
import gc
from weakref import WeakSet
from ..resources import MODEL_PHASE_LOCK

_OWNERS = WeakSet()


class RetrievalModel:
    """Exact-model reload after an explicit generation handoff; no fallback."""
    def __init__(self, factory, model_name):
        self.factory, self.model_name, self._model = factory, model_name, None
        with MODEL_PHASE_LOCK:
            _OWNERS.add(self)

    def load(self):
        with MODEL_PHASE_LOCK:
            if self._model is None:
                self._model = self.factory()
            return self

    def encode(self, texts, **kwargs):
        with MODEL_PHASE_LOCK:
            self.load()
            return self._model.encode(texts, **kwargs)

    def predict(self, pairs, batch_size=None, **kwargs):
        with MODEL_PHASE_LOCK:
            self.load()
            if batch_size is not None:
                kwargs['batch_size'] = batch_size
            return self._model.predict(pairs, **kwargs)


def release_retrieval_weights():
    """Drop every registered inner weight reference, including cached owners.

    Inference holds the same process-wide lock through its entire call, so a
    concurrent request cannot lose weights mid-encode/predict. Index snapshots,
    selected evidence and model identity are untouched.
    """
    with MODEL_PHASE_LOCK:
        released = 0
        for owner in list(_OWNERS):
            if owner._model is not None:
                owner._model = None
                released += 1
        if released:
            gc.collect()
        return released
