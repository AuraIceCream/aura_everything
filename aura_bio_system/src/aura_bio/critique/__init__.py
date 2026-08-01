"""External critique and the critique-revision loop (SRS 17-18)."""

from .comparison import CRITIC_CASES, CriticCase, compare_critics, format_comparison_table
from .external import CriticResult, GeminiCritic, GLMCritic, critic_from_env
from .schema import (
    Critique,
    RevisionRecord,
    combine_decision,
    parse_critique,
    revision_instructions,
)

__all__ = [
    "CRITIC_CASES",
    "CriticCase",
    "CriticResult",
    "Critique",
    "GLMCritic",
    "GeminiCritic",
    "RevisionRecord",
    "combine_decision",
    "compare_critics",
    "critic_from_env",
    "format_comparison_table",
    "parse_critique",
    "revision_instructions",
]
