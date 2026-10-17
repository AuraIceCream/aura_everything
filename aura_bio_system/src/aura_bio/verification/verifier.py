"""Compose the SRS 16 checkers into one verification pass."""

from __future__ import annotations

from typing import Sequence

from ..routing.schema import LearnerLevel, Route
from .checkers import (
    EvidencePassage,
    check_abbreviations,
    check_citations,
    check_claim_support,
    check_process_location,
    check_process_order,
    check_terminology,
    check_uncertainty,
    split_claims,
)
from .numerical import verify_numerical
from .schema import Support, VerificationReport, Issue

#: Levels for which an unexpanded abbreviation is a real comprehension barrier.
_EXPANSION_LEVELS = frozenset(
    {
        LearnerLevel.ELEMENTARY,
        LearnerLevel.MIDDLE_SCHOOL,
        LearnerLevel.HIGH_SCHOOL,
        LearnerLevel.SENIOR_SECONDARY,
        LearnerLevel.GENERAL_PUBLIC,
    }
)

_GROUNDED = {Support.SUPPORTED: 1.0, Support.PARTIALLY_SUPPORTED: 0.5}


class BiologyVerifier:
    """Runs every applicable checker and produces one structured report.

    The checkers stay independent so the ablation study (SRS 25) can switch any
    one of them off and attribute the difference.

    Two layers with different authority. The deterministic checkers — arithmetic
    recomputed with SymPy, codons against the genetic code, equations balanced
    by element, pathway yields against known constants, process order,
    compartments, terminology — decide ``error`` severity on their own. The NLI
    entailment model is the single learned component and may only raise an
    error for a *confident contradiction*; it never blocks on weak support,
    which is the failure that once rejected 97% of answers.
    """

    def __init__(
        self,
        check_claims: bool = True,
        check_terms: bool = True,
        check_processes: bool = True,
        check_numbers: bool = True,
        check_hedging: bool = True,
        check_biochemistry: bool = True,
        check_ontology: bool = False,
        use_entailment: bool = True,
    ) -> None:
        self.check_claims = check_claims
        self.check_terms = check_terms
        self.check_processes = check_processes
        self.check_numbers = check_numbers
        self.check_hedging = check_hedging
        #: Sequences, chemical equations, unit magnitudes and pathway yields.
        #: Measured over 537 real generated answers: zero blocking issues, so
        #: none of these fire on correct prose.
        self.check_biochemistry = check_biochemistry
        #: Off by default, on measurement. The entity lexicon is excellent at
        #: judging a *question* — it identifies all 8 fabricated entities in the
        #: adversarial set with 0.7% false alarms over 433 real questions — but
        #: run against an *answer* it warns roughly once per answer, mostly on
        #: real terms the corpus files under another title ("Krebs cycle") and
        #: on emphasised phrases that are not binomials. A warning stream that
        #: noisy trains a reader to ignore warnings. The question-side signal is
        #: shipped instead; see :func:`ontology.unknown_entities`.
        self.check_ontology = check_ontology
        #: NLI claim support. Falls back to token overlap when the model is
        #: unavailable, so a machine without it still runs.
        self.use_entailment = use_entailment

    def verify(
        self,
        answer: str,
        evidence: Sequence[EvidencePassage],
        route: Route | None = None,
        question: str | None = None,
    ) -> VerificationReport:
        report = VerificationReport()
        if not answer.strip():
            report.issues.append(Issue("generation", "empty_answer", "Supply an answer to the question.", "error"))
        query = question if question is not None else (route.query if route else "")

        claims = split_claims(answer)
        if self.check_claims:
            report.claims = self._support(claims, evidence, report)
            grounded = sum(_GROUNDED.get(claim.support, 0.0) for claim in report.claims)
            report.grounded_fraction = grounded / len(report.claims) if report.claims else 0.0
        coverage, citation_issues = check_citations(answer, len(evidence))
        report.citation_coverage = coverage
        report.issues.extend(citation_issues)

        if self.check_terms:
            report.issues.extend(check_terminology(answer))
            level = route.learner_level.label if route else None
            report.issues.extend(
                check_abbreviations(answer, expand_required=level in _EXPANSION_LEVELS)
            )

        if self.check_processes:
            from ..routing.router import ordered_processes_in

            named = set(ordered_processes_in(query)) | set(ordered_processes_in(answer))
            report.issues.extend(check_process_order(answer, sorted(named)))
            report.issues.extend(check_process_location(answer))

        if self.check_numbers and (route is None or route.needs_numerical_verification or query):
            checks = verify_numerical(query, answer)
            report.numerical = [check.as_dict() for check in checks]
            for check in checks:
                if check.verdict == "incorrect":
                    report.issues.append(
                        _numeric_issue(check.quantity, check.stated, check.expected, check.working)
                    )

        if self.check_biochemistry:
            report.issues.extend(self._biochemistry(answer, report))

        if self.check_ontology:
            report.issues.extend(self._ontology(answer))

        if self.check_hedging:
            report.issues.extend(check_uncertainty(report.claims))
        return report

    # -- layers ---------------------------------------------------------------

    def _support(
        self, claims: Sequence[str], evidence: Sequence[EvidencePassage], report: VerificationReport
    ):
        """Label claims by entailment where possible, token overlap otherwise."""

        if self.use_entailment and claims and evidence:
            try:
                from .entailment import check_entailment, claims_from_entailment, entail_claims

                results = entail_claims(claims, evidence)
                if results:
                    report.support_backend = "nli"
                    report.issues.extend(check_entailment(results))
                    return claims_from_entailment(results)
            except Exception as exc:
                # No model, no torch, no network — fall back rather than fail
                # the request (SRS 18.3).
                report.checker_status["nli"] = "unavailable: " + type(exc).__name__
                from ..resources import MemoryPressureError
                if isinstance(exc, MemoryPressureError):
                    report.issues.append(Issue('nli', 'memory_pressure', str(exc), 'warning'))
        report.support_backend = "lexical"
        return check_claim_support(claims, evidence)

    def _biochemistry(self, answer: str, report: VerificationReport) -> list:
        issues: list = []
        from .chemistry import check_chemical_equations, check_units
        from .pathways import check_pathway_stoichiometry
        from .sequences import check_sequences

        for check in (check_sequences, check_chemical_equations, check_units,
                      check_pathway_stoichiometry):
            try:
                issues.extend(check(answer))
                report.checker_status[check.__name__] = "ran"
            except Exception as exc:
                report.checker_status[check.__name__] = "unavailable: " + type(exc).__name__
                continue
        return issues

    def _ontology(self, answer: str) -> list:
        issues: list = []
        try:
            from .ontology import check_ontology_terms, check_taxonomy

            issues.extend(check_ontology_terms(answer))
            issues.extend(check_taxonomy(answer))
        except Exception:
            return []
        return issues


def _numeric_issue(quantity: str, stated: float | None, expected: float, working: str):
    from .schema import Issue

    return Issue(
        "numerical",
        "wrong_value",
        f"{quantity}: answer states {stated}, recomputed {expected:.6g} ({working})",
        "error",
        quantity,
    )
