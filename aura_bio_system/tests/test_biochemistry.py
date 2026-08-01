"""Regression tests for the recomputing checkers (SRS 16).

Every case that asserts *silence* is prose taken from real generated answers,
not written for the test. That distinction is the project's most expensive
lesson: each of these checkers passed a synthetic suite and then fired on
correct prose the first time it met the benchmark output, and the fixes are
pinned here so they cannot regress.
"""

from __future__ import annotations

import unittest

from aura_bio.verification.chemistry import check_chemical_equations, check_units
from aura_bio.verification.pathways import check_pathway_stoichiometry
from aura_bio.verification.provenance import measure_provenance
from aura_bio.verification.checkers import EvidencePassage
from aura_bio.verification.sequences import check_sequences


class SequenceTests(unittest.TestCase):
    def test_codon_assignment_is_recomputed(self) -> None:
        self.assertFalse(check_sequences("The codon AUG codes for methionine."))
        issues = check_sequences("The codon AUG codes for leucine.")
        self.assertTrue(issues)
        self.assertEqual(issues[0].kind, "wrong_codon")

    def test_stop_and_start_codons(self) -> None:
        self.assertFalse(check_sequences("UAA is a stop codon."))
        self.assertTrue(check_sequences("AUG is a stop codon."))
        self.assertTrue(check_sequences("GGC is the start codon."))

    def test_complement_is_recomputed(self) -> None:
        self.assertFalse(check_sequences("The complement of ATCG is TAGC."))
        self.assertFalse(check_sequences("The reverse complement of AATTCC is GGAATT."))
        self.assertTrue(check_sequences("The complement of ATCG is TTTT."))

    def test_gc_content_is_recomputed(self) -> None:
        self.assertFalse(check_sequences("For the sequence GGCCGGCC the GC content is 100%."))
        self.assertTrue(check_sequences("For the sequence GGCCGGCC the GC content is 25%."))

    def test_illegal_letters_in_a_stated_sequence(self) -> None:
        self.assertTrue(check_sequences("The sequence ATCGATCGZZQQ was amplified."))

    def test_real_output_about_reading_frames_stays_silent(self) -> None:
        """From bio-0417. ATG starts translation; the sentence also names a stop.

        A forty-character proximity window read this as "ATG is a stop codon".
        Only a direct copula may bind a codon to a claim about it.
        """

        answer = (
            "Translation begins at the start codon (`ATG` in DNA, `AUG` in mRNA), "
            "and ends at a Stop Codon such as TAA."
        )
        self.assertEqual(check_sequences(answer), [])

    def test_real_output_about_open_reading_frames_stays_silent(self) -> None:
        """From bio-0081. CONTAINING is 80% ACGTUN letters but is a word."""

        answer = (
            "By definition, any sequence containing a Start codon followed "
            "immediately by non-stop nucleotides constitutes an Open Reading Frame."
        )
        self.assertEqual(check_sequences(answer), [])

    def test_ordinary_biology_prose_stays_silent(self) -> None:
        for answer in (
            "DNA replication is semiconservative and requires a primer.",
            "Mitochondria produce ATP through oxidative phosphorylation.",
            "The cell cycle has G1, S, G2 and M phases.",
        ):
            self.assertEqual(check_sequences(answer), [], answer)


class ChemistryTests(unittest.TestCase):
    def test_balanced_equations_pass(self) -> None:
        self.assertFalse(check_chemical_equations("6CO2 + 6H2O -> C6H12O6 + 6O2"))
        self.assertFalse(check_chemical_equations("C6H12O6 + 6O2 -> 6CO2 + 6H2O"))

    def test_unbalanced_equation_is_an_error(self) -> None:
        issues = check_chemical_equations("6CO2 + 6H2O -> C6H12O6 + 3O2")
        self.assertTrue(issues)
        self.assertEqual(issues[0].severity, "error")

    def test_biological_abbreviations_are_never_balanced(self) -> None:
        """A formula parser reads ATP as astatine-phosphorus.

        Equations naming species that are not molecular formulas cannot be
        balanced by element, so they are skipped rather than guessed at.
        """

        for equation in (
            "ADP + Pi -> ATP during phosphorylation",
            "NADH + H + O2 -> NAD + H2O in the electron transport chain",
            "Glucose + O2 -> CO2 + H2O",
            "DNA -> RNA -> protein is the central dogma",
        ):
            self.assertEqual(check_chemical_equations(equation), [], equation)

    def test_scale_errors_in_physiological_quantities(self) -> None:
        self.assertFalse(check_units("The resting membrane potential is about -70 mV."))
        self.assertTrue(check_units("The resting membrane potential is about -70 V."))

    def test_correct_physiological_values_pass(self) -> None:
        for answer in (
            "Human body temperature is 37 degrees C.",
            "Blood pH is 7.4.",
            "Resting heart rate is about 70 bpm.",
            "The action potential peak is around +40 mV.",
        ):
            self.assertEqual(check_units(answer), [], answer)


class PathwayTests(unittest.TestCase):
    def test_net_and_gross_atp_are_both_correct(self) -> None:
        self.assertFalse(check_pathway_stoichiometry(
            "Glycolysis produces a net gain of 2 ATP per glucose."))
        self.assertFalse(check_pathway_stoichiometry(
            "Glycolysis produces 4 ATP in total, for a net of 2 ATP."))

    def test_wrong_net_atp_is_caught(self) -> None:
        self.assertTrue(check_pathway_stoichiometry(
            "Glycolysis produces a net gain of 4 ATP per glucose."))

    def test_unstated_basis_is_left_alone(self) -> None:
        """4 ATP is the gross figure and 2 the net; without a basis, neither."""

        self.assertEqual(check_pathway_stoichiometry("Glycolysis produces 4 ATP."), [])
        self.assertEqual(check_pathway_stoichiometry("The Krebs cycle produces 6 NADH."), [])

    def test_per_turn_and_per_glucose_both_accepted(self) -> None:
        self.assertFalse(check_pathway_stoichiometry(
            "Each turn of the Krebs cycle produces 3 NADH and 1 FADH2."))
        self.assertFalse(check_pathway_stoichiometry(
            "The Krebs cycle produces 6 NADH per glucose."))
        self.assertTrue(check_pathway_stoichiometry(
            "Each turn of the Krebs cycle produces 6 NADH."))

    def test_respiration_total_accepts_every_textbook_figure(self) -> None:
        for value in (30, 32, 34, 36, 38):
            self.assertEqual(
                check_pathway_stoichiometry(
                    f"Aerobic respiration yields about {value} ATP per glucose."),
                [], str(value),
            )
        self.assertTrue(check_pathway_stoichiometry(
            "Aerobic respiration yields about 150 ATP per glucose."))

    def test_aneuploidy_context_disables_the_chromosome_count(self) -> None:
        """From bio-0101, where 47 is the correct answer.

        The disqualifying context is stated in an earlier sentence than the
        number, so the veto has to look at the whole answer.
        """

        answer = (
            "Down syndrome is caused by trisomy 21. Nondisjunction during meiosis "
            "causes one gamete to carry an extra copy of chromosome 21. When "
            "fertilisation occurs with a normal gamete, the resulting embryo has "
            "47 chromosomes total rather than the standard human count of 46."
        )
        self.assertEqual(check_pathway_stoichiometry(answer), [])
        self.assertTrue(check_pathway_stoichiometry("A human somatic cell has 92 chromosomes."))

    def test_atp_outside_a_pathway_claim_is_ignored(self) -> None:
        self.assertEqual(
            check_pathway_stoichiometry(
                "Active transport uses 2 ATP to move ions across the membrane."), [])


class ProvenanceTests(unittest.TestCase):
    evidence = (
        EvidencePassage("c1", "Helicase unwinds the DNA double helix at the replication "
                              "origin by breaking hydrogen bonds between base pairs.",
                        "Replication", "wikipedia_biology"),
        EvidencePassage("c2", "DNA polymerase adds nucleotides to the growing strand in the "
                              "5' to 3' direction using the template.",
                        "Polymerase", "wikipedia_biology"),
    )

    def test_every_claim_cited(self) -> None:
        answer = (
            "Helicase unwinds the double helix at the origin by breaking hydrogen bonds. [1]\n"
            "DNA polymerase extends the new strand in the 5' to 3' direction. [2]"
        )
        report = measure_provenance(answer, self.evidence)
        self.assertEqual(report.claim_citation_rate, 1.0)
        self.assertEqual(report.unsupported_assertion_rate, 0.0)
        self.assertEqual(report.distinct_sources, 1)

    def test_no_citations_is_fully_unsupported(self) -> None:
        answer = (
            "Helicase unwinds the double helix at the origin by breaking hydrogen bonds.\n"
            "DNA polymerase extends the new strand in the 5' to 3' direction."
        )
        report = measure_provenance(answer, self.evidence)
        self.assertEqual(report.claim_citation_rate, 0.0)
        self.assertEqual(report.unsupported_assertion_rate, 1.0)

    def test_citation_validity_separates_cited_from_supported(self) -> None:
        """A citation that points somewhere irrelevant is still a citation.

        This is the distinction check_citations cannot make, and the reason
        provenance is reported as two numbers rather than one.
        """

        answer = (
            "The mitochondrion is the site of oxidative phosphorylation in "
            "eukaryotic cells. [1]"
        )
        report = measure_provenance(answer, self.evidence)
        self.assertEqual(report.claim_citation_rate, 1.0)
        self.assertEqual(report.citation_validity, 0.0)

    def test_dangling_citation_is_counted(self) -> None:
        answer = "DNA polymerase extends the new strand in the 5' to 3' direction. [9]"
        report = measure_provenance(answer, self.evidence)
        self.assertEqual(report.dangling_citations, 1)


if __name__ == "__main__":
    unittest.main()
