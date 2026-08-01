"""AURA-Bio runtime: routing, evidence selection, verification, and critique.

Corpus acquisition lives in ``aura_corpus`` and corpus preparation/indexing in
``aura_bio_pipeline``. This package is everything that runs per user query.
"""

__version__ = "0.1.0"

# Point the model caches at the drive that has room for them, before anything
# can import HuggingFace and read the default. Credentials are still loaded
# explicitly via aura_bio.env.load_env; this covers only cache paths, whose
# absence fills the system drive rather than disabling a feature. See
# aura_bio.env.ensure_cache_location for why that distinction is drawn here.
from .env import ensure_cache_location as _ensure_cache_location

_ensure_cache_location()
del _ensure_cache_location
