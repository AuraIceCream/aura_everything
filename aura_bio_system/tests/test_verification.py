from __future__ import annotations

import unittest

from aura_bio.routing import QueryRouter
from aura_bio.verification import (
    BiologyVerifier,
    Certainty,
    EvidencePassage,
    Support,
    split_claims,
    verify_numerical,
)
from aura_bio.verification.checkers import (
    check_citations,
    check_process_location,
    check_process_order,
    check_terminology,
)


def passage(chunk_id: str, text: str) -> EvidencePassage:
    return EvidencePassage(chunk_id=chunk_id, text=text, title="t", source_id="wikipedia_biology")


class ClaimSplittingTests(unittest.TestCase):
    def test_sentences_become_claims(self) -> None:
        answer = (
            "DNA replication is semiconservative. "
            "Helicase unwinds the double helix at the origin of replication.\n"
            "- Primase lays down a short RNA primer for the polymerase.\n"
            "In summary, this is the process."
        )
        claims = split_claims(answer)
        self.assertEqual(len(claims), 3)
        self.assertTrue(claims[1].startswith("Helicase unwinds"))

    def test_questions_and_headings_are_not_claims(self) -> None:
        claims = split_claims("## Overview\nWhat do you think happens next in the cycle?\nStep 1")
        self.assertEqual(claims, [])


class ClaimSupportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = BiologyVerifier()

    def test_supported_claim_is_labelled_and_linked(self) -> None:
        evidence = [
            passage(
                "c1",
                "Helicase unwinds the double helix at the origin of replication, "
                "separating the parental strands during DNA replication.",
            )
        ]
        report = self.verifier.verify(
            "Helicase unwinds the double helix at the origin of replication. [1]", evidence
        )
        self.assertEqual(report.claims[0].support, Support.SUPPORTED)
        self.assertIn("c1", report.claims[0].evidence_chunk_ids)
        self.assertEqual(report.decision(), "accept")

    def test_unsupported_claim_is_flagged(self) -> None:
        evidence = [passage("c1", "Chloroplasts carry out photosynthesis in plant cells.")]
        report = self.verifier.verify(
            "The human genome contains exactly forty thousand protein coding genes. [1]", evidence
        )
        self.assertEqual(report.claims[0].support, Support.UNSUPPORTED)
        self.assertTrue(report.unsupported_claims)
        self.assertIn(report.decision(), {"revise", "insufficient_evidence"})

    def test_no_evidence_yields_unverifiable_not_unsupported(self) -> None:
        report = self.verifier.verify("Mitochondria produce ATP through oxidative phosphorylation.", [])
        self.assertEqual(report.claims[0].support, Support.UNVERIFIABLE)

    def test_numbers_absent_from_evidence_downgrade_support(self) -> None:
        evidence = [
            passage("c1", "Human somatic cells are diploid and carry a set of chromosomes in the nucleus.")
        ]
        report = self.verifier.verify("Human somatic cells carry 92 chromosomes in the nucleus. [1]", evidence)
        self.assertNotEqual(report.claims[0].support, Support.SUPPORTED)


class TerminologyTests(unittest.TestCase):
    def test_misspelling_is_an_error(self) -> None:
        issues = check_terminology("The mitochondira make ATP.")
        self.assertEqual(issues[0].kind, "misspelling")
        self.assertEqual(issues[0].severity, "error")

    def test_correct_spelling_containing_a_misspelling_is_not_flagged(self) -> None:
        """'chlorophyll' contains 'chlorophyl'; substring matching flagged it."""

        issues = check_terminology("Chloroplasts contain chlorophyll, the green pigment.")
        self.assertFalse(any(i.kind == "misspelling" for i in issues))
        # The genuine misspelling must still be caught.
        self.assertTrue(
            any(i.kind == "misspelling" for i in check_terminology("It contains chlorophyl."))
        )

    def test_invalid_binomial_is_flagged(self) -> None:
        issues = check_terminology("The bacterium Escherichia sapiens is widely studied.")
        self.assertTrue(any(issue.kind == "invalid_species" for issue in issues))

    def test_valid_binomial_passes(self) -> None:
        issues = check_terminology("Escherichia coli and Homo sapiens are model organisms.")
        self.assertFalse(any(issue.kind == "invalid_species" for issue in issues))

    def test_abbreviation_expansion_required_for_school_level(self) -> None:
        route = QueryRouter().route("Explain respiration", learner_level="high_school")
        report = BiologyVerifier().verify("Cells release energy as ATP during respiration.", [], route)
        self.assertTrue(any(issue.kind == "unexpanded_abbreviation" for issue in report.issues))

    def test_abbreviation_expansion_not_required_for_research_level(self) -> None:
        route = QueryRouter().route("Explain respiration", learner_level="research")
        report = BiologyVerifier().verify("Cells release energy as ATP during respiration.", [], route)
        self.assertFalse(any(issue.kind == "unexpanded_abbreviation" for issue in report.issues))


class ProcessTests(unittest.TestCase):
    def test_correct_mitosis_order_passes(self) -> None:
        answer = "Mitosis proceeds through prophase, metaphase, anaphase, telophase and cytokinesis."
        self.assertEqual(check_process_order(answer, ["mitosis"]), [])

    def test_reversed_order_is_an_error(self) -> None:
        answer = "In mitosis the cell enters anaphase, then metaphase, then prophase and telophase."
        issues = check_process_order(answer, ["mitosis"])
        self.assertTrue(any(issue.kind == "step_order" for issue in issues))
        self.assertEqual(issues[0].severity, "error")

    def test_topic_first_prose_is_not_an_order_error(self) -> None:
        """Mention order is not asserted order when no sequence is claimed."""

        answer = (
            "S phase is when DNA replication occurs. It is part of interphase in the "
            "cell cycle, sitting between G1 and G2, before the cell enters mitosis."
        )
        issues = check_process_order(answer, ["cell cycle"])
        self.assertFalse(any(i.kind == "step_order" for i in issues))

    def test_order_is_still_judged_when_a_sequence_is_asserted(self) -> None:
        answer = (
            "The cell cycle proceeds through the following sequence: first mitosis, "
            "then G2, then S phase, and finally G1."
        )
        issues = check_process_order(answer, ["cell cycle"])
        self.assertTrue(any(i.kind == "step_order" for i in issues))

    def test_step_name_inside_a_compound_term_is_not_a_step(self) -> None:
        """'anaphase-promoting complex' is a protein; 'termination signal' a stop codon."""

        protein = (
            "This checkpoint prevents activation of the anaphase-promoting complex/cyclosome "
            "(APC/C), which normally acts after metaphase."
        )
        self.assertFalse(any(i.kind == "step_order" for i in check_process_order(protein, ["mitosis"])))
        codon = "A codon corresponds to an amino acid or a termination signal. Initiation begins at AUG."
        self.assertFalse(any(i.kind == "step_order" for i in check_process_order(codon, ["translation"])))

    def test_topical_organisation_is_not_a_sequence_claim(self) -> None:
        """A checkpoint explainer is ordered by checkpoint, not chronologically."""

        answer = (
            "#### 3. The spindle assembly checkpoint\n"
            "**Mechanism:** this checkpoint prevents activation of the complex that "
            "triggers the events leading to anaphase. If errors are found, the cell "
            "arrests here for repair or undergoes apoptosis.\n\n"
            "#### 4. The M phase checkpoint\n"
            "**Location:** during metaphase, when chromosomes align at the equator.\n"
            "1. Check chromosome attachment.\n2. Release the anaphase inhibitor."
        )
        self.assertFalse(any(i.kind == "step_order" for i in check_process_order(answer, ["mitosis"])))

    def test_bulleted_structure_list_is_not_a_sequence_claim(self) -> None:
        answer = (
            "The stroma contains:\n*   enzymes for the calvin cycle.\n*   chloroplast DNA.\n"
            "The light-dependent reactions occur in the thylakoids."
        )
        self.assertFalse(
            any(i.kind == "step_order" for i in check_process_order(answer, ["photosynthesis"]))
        )

    def test_missing_steps_are_a_warning(self) -> None:
        answer = "Mitosis involves prophase, metaphase and anaphase before the cell splits."
        issues = check_process_order(answer, ["mitosis"])
        self.assertTrue(any(issue.kind == "missing_steps" for issue in issues))

    def test_wrong_compartment_is_an_error(self) -> None:
        issues = check_process_location("Glycolysis takes place inside the mitochondria of the cell.")
        self.assertTrue(any(issue.kind == "wrong_location" for issue in issues))

    def test_co_occurrence_without_a_locative_claim_is_not_an_error(self) -> None:
        """Naming both terms nearby is not asserting one happens in the other."""

        answer = (
            "Mature red blood cells lack mitochondria entirely, because they rely on "
            "anaerobic glycolysis for their energy instead."
        )
        self.assertEqual(check_process_location(answer), [])

    def test_reverse_phrasing_is_still_caught(self) -> None:
        answer = "The mitochondria is where glycolysis happens in the cell."
        issues = check_process_location(answer)
        self.assertTrue(any(i.kind == "wrong_location" for i in issues))

    def test_right_compartment_passes(self) -> None:
        self.assertEqual(
            check_process_location("Glycolysis takes place in the cytoplasm of the cell."), []
        )

    def test_verifier_picks_up_process_from_the_question(self) -> None:
        report = BiologyVerifier().verify(
            "The cell enters anaphase, then metaphase, then prophase.",
            [],
            QueryRouter().route("Explain mitosis"),
        )
        self.assertTrue(any(issue.kind == "step_order" for issue in report.issues))


class CitationTests(unittest.TestCase):
    def test_dangling_citation_is_an_error(self) -> None:
        coverage, issues = check_citations("As shown in [4].", 2)
        self.assertTrue(any(issue.kind == "dangling_citation" for issue in issues))
        self.assertEqual(coverage, 0.0)

    def test_coverage_is_the_fraction_of_evidence_used(self) -> None:
        coverage, issues = check_citations("First [1]. Second [2].", 4)
        self.assertAlmostEqual(coverage, 0.5)
        self.assertEqual(issues, [])

    def test_uncited_evidence_warns(self) -> None:
        _, issues = check_citations("No citations at all here.", 3)
        self.assertTrue(any(issue.kind == "no_citations" for issue in issues))


class UncertaintyTests(unittest.TestCase):
    def test_hedged_language_is_detected(self) -> None:
        report = BiologyVerifier().verify(
            "This mechanism is thought to involve an as yet uncharacterised transporter protein.", []
        )
        self.assertEqual(report.claims[0].certainty, Certainty.SPECULATION)

    def test_unsupported_absolute_is_surfaced_as_a_warning(self) -> None:
        """Flagged for review, but the unsupported claim is what forces revision."""

        evidence = [passage("c1", "Some enzymes are proteins; ribozymes are catalytic RNA molecules.")]
        report = BiologyVerifier().verify(
            "Every single enzyme in every organism is always a protein molecule. [1]", evidence
        )
        overstated = [i for i in report.issues if i.kind == "overstated"]
        self.assertTrue(overstated)
        self.assertEqual(overstated[0].severity, "warning")
        # The unsupported claim still prevents acceptance, whether the verdict
        # is "revise" or "insufficient_evidence".
        self.assertNotEqual(report.decision(), "accept")

    def test_rhetorical_absolute_in_correct_prose_does_not_block(self) -> None:
        """'Membranes are never static' is correct biology, not an error."""

        evidence = [passage("c1", "The fluid mosaic model describes membranes as dynamic and fluid.")]
        report = BiologyVerifier().verify(
            "Membranes are never static; they are perpetually active, dynamic systems. [1]", evidence
        )
        self.assertFalse([i for i in report.issues if i.severity == "error"])


class NumericalTests(unittest.TestCase):
    def test_correct_final_number_does_not_hide_a_wrong_allele_frequency(self) -> None:
        question = "If 16% show a recessive trait under Hardy-Weinberg equilibrium, find heterozygote frequency."
        answer = ("The frequency of the recessive allele (q) is 0.16. "
                  "q = 0.4; p = 0.6; 2pq = 0.48.")
        report = BiologyVerifier(use_entailment=False).verify(answer, [], question=question)
        self.assertEqual(report.decision(), "revise")
        self.assertTrue(any(c["quantity"] == "q" and c["verdict"] == "incorrect"
                            for c in report.numerical))

    def test_conflicting_final_quantity_is_not_matched_to_only_the_correct_occurrence(self) -> None:
        checks = verify_numerical(
            "If 16% show a recessive trait under Hardy-Weinberg equilibrium, find heterozygote frequency.",
            "q = 0.4; p = 0.6; 2pq = 0.48. Therefore 2pq = 0.32.")
        self.assertTrue(any(c.quantity == "2pq" and c.verdict == "incorrect" for c in checks))

    def test_consistent_named_values_pass(self) -> None:
        checks = verify_numerical(
            "If 16% show a recessive trait under Hardy-Weinberg equilibrium, find heterozygote frequency.",
            "q^2 = 0.16; q = 0.4; p = 0.6; 2pq = 0.48.")
        self.assertFalse(any(c.verdict == "incorrect" for c in checks))

    def test_rejected_wrong_value_is_not_treated_as_an_assertion(self) -> None:
        checks = verify_numerical(
            "If 16% show a recessive trait under Hardy-Weinberg equilibrium, find heterozygote frequency.",
            "Do not use q = 0.16. Instead q = 0.4, p = 0.6, and 2pq = 0.48.")
        self.assertFalse(any(c.verdict == "incorrect" for c in checks))

    def test_expression_prefix_and_sum_are_not_scalar_assignments(self) -> None:
        checks = verify_numerical(
            "If 16% show a recessive trait under Hardy-Weinberg equilibrium, find heterozygote frequency.",
            "p + q = 1. q = 1 - p. q = 0.4; p = 0.6; 2pq = 0.48.")
        self.assertFalse(any(c.verdict == "incorrect" for c in checks))

    def test_named_percentage_is_compared_as_a_fraction(self) -> None:
        checks = verify_numerical(
            "If 16% show a recessive trait under Hardy-Weinberg equilibrium, find heterozygote frequency.",
            "The recessive allele frequency (q) is 40%. p = 60%; 2pq = 48%.")
        self.assertFalse(any(c.verdict == "incorrect" for c in checks))

    def test_hardy_weinberg_correct_answer(self) -> None:
        checks = verify_numerical(
            "In a Hardy-Weinberg population, 16% of individuals are homozygous recessive. "
            "What is the frequency of heterozygotes?",
            "Since q^2 = 0.16, q = 0.4 and p = 0.6, so 2pq = 0.48.",
        )
        headline = [check for check in checks if check.quantity == "2pq"]
        self.assertEqual(len(headline), 1)
        self.assertAlmostEqual(headline[0].expected, 0.48, places=6)
        self.assertEqual(headline[0].verdict, "correct")

    def test_stated_p_is_read_as_the_premise_not_as_q_squared(self) -> None:
        """'p = 0.7 ... homozygous recessive' must not treat 0.7 as q^2."""

        checks = verify_numerical(
            "In Hardy-Weinberg equilibrium, if the dominant allele frequency p = 0.7, "
            "what is the frequency of homozygous recessive individuals?",
            "Since p = 0.7, q = 0.3, and so q squared = 0.09.",
        )
        graded = [c for c in checks if c.verdict in ("correct", "incorrect")]
        self.assertEqual(len(graded), 1)
        self.assertEqual(graded[0].quantity, "q_squared")
        self.assertAlmostEqual(graded[0].expected, 0.09, places=6)
        self.assertEqual(graded[0].verdict, "correct")

    def test_graded_quantity_follows_the_question(self) -> None:
        checks = verify_numerical(
            "With 16% homozygous recessive, what is the heterozygote frequency?",
            "It is 0.48.",
        )
        graded = [c for c in checks if c.verdict in ("correct", "incorrect")]
        self.assertEqual(graded[0].quantity, "2pq")

    def test_hardy_weinberg_wrong_answer_is_caught(self) -> None:
        checks = verify_numerical(
            "In a Hardy-Weinberg population, 16% of individuals are homozygous recessive. "
            "What is the heterozygote frequency?",
            "The heterozygote frequency is 0.32.",
        )
        headline = [check for check in checks if check.quantity == "2pq"][0]
        self.assertEqual(headline.verdict, "incorrect")

    def test_method_without_a_number_is_unstated_not_incorrect(self) -> None:
        checks = verify_numerical(
            "With 16% homozygous recessive under Hardy-Weinberg, find the heterozygote frequency.",
            "Take the square root of the recessive frequency, then apply the two p q term.",
        )
        headline = [check for check in checks if check.quantity == "2pq"][0]
        self.assertEqual(headline.verdict, "unstated")

    def test_michaelis_menten(self) -> None:
        checks = verify_numerical(
            "An enzyme has Vmax of 100 and Km of 5. What is the velocity at a substrate concentration of 15?",
            "The velocity works out to 75.",
        )
        self.assertEqual(len(checks), 1)
        self.assertAlmostEqual(checks[0].expected, 75.0, places=6)
        self.assertEqual(checks[0].verdict, "correct")

    def test_dilution_solves_for_the_missing_term(self) -> None:
        checks = verify_numerical(
            "You dilute a stock solution. C1 is 10 and V1 is 5 and the final concentration C2 is 2. "
            "What is V2?",
            "V2 must be 25.",
        )
        self.assertEqual(checks[0].quantity, "v2")
        self.assertAlmostEqual(checks[0].expected, 25.0, places=6)
        self.assertEqual(checks[0].verdict, "correct")

    def test_doubling_time_growth(self) -> None:
        checks = verify_numerical(
            "A bacterial population with an initial 500 cells and a doubling time of 30 minutes "
            "grows for 120 minutes. What is the population?",
            "After 120 minutes there will be 8000 cells.",
        )
        self.assertAlmostEqual(checks[0].expected, 8000.0, places=6)
        self.assertEqual(checks[0].verdict, "correct")

    def test_carrier_cross_probability(self) -> None:
        checks = verify_numerical(
            "Both parents are carriers of cystic fibrosis. What is the probability their child is affected?",
            "There is a 25% chance the child is affected.",
        )
        self.assertAlmostEqual(checks[0].expected, 0.25, places=6)
        self.assertEqual(checks[0].verdict, "correct")

    def test_unrecognised_question_yields_no_checks(self) -> None:
        self.assertEqual(verify_numerical("Explain what a ribosome does.", "It makes proteins."), [])

    def test_verifier_raises_an_error_issue_for_bad_arithmetic(self) -> None:
        route = QueryRouter().route(
            "In a Hardy-Weinberg population 16% are homozygous recessive, calculate the heterozygote frequency"
        )
        report = BiologyVerifier().verify("The heterozygote frequency is 0.32.", [], route)
        self.assertTrue(any(issue.checker == "numerical" for issue in report.issues))
        self.assertEqual(report.decision(), "revise")


class ReportTests(unittest.TestCase):
    def test_report_is_json_safe_and_has_a_decision(self) -> None:
        import json

        evidence = [passage("c1", "Helicase unwinds DNA during replication.")]
        report = BiologyVerifier().verify("Helicase unwinds DNA during replication. [1]", evidence)
        payload = report.as_dict()
        json.dumps(payload)
        self.assertIn(payload["decision"], {"accept", "revise", "insufficient_evidence"})
        self.assertGreaterEqual(payload["confidence"], 0.0)
        self.assertLessEqual(payload["confidence"], 1.0)

    def test_checkers_can_be_disabled_for_ablation(self) -> None:
        verifier = BiologyVerifier(check_terms=False)
        report = verifier.verify("The mitochondira make energy for the cell here.", [])
        self.assertFalse(any(issue.checker == "terminology" for issue in report.issues))


if __name__ == "__main__":
    unittest.main()
