"""Tool-owned arithmetic and focused revisions; no external model calls."""

import unittest
from dataclasses import dataclass

from aura_bio.critique import Critique, revision_instructions
from aura_bio.generation import build_prompt
from aura_bio.pipeline import AuraBioPipeline
from aura_bio.routing import QueryRouter
from aura_bio.verification import BiologyVerifier, EvidencePassage, VerificationReport
from aura_bio.verification.numerical import hardy_weinberg, verify_numerical


@dataclass
class Passage:
    chunk_id: str = "g"
    text: str = "Glycolysis occurs in the cytoplasm."
    title: str = "Glycolysis"
    source_id: str = "textbook"
    document_id: str = "g"
    section: str = "Intro"
    rrf_score: float = 0.02
    rerank_score: float | None = None


class Searcher:
    def search(self, query, top_k, candidate_k):
        return [Passage()]


class Generator:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def generate(self, route, evidence, instructions, coverage_pool=(),
                 unknown_entities=(), previous_answer=""):
        self.calls.append((tuple(instructions), previous_answer))
        return self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]


QUESTION = ("If 16% of a population shows a recessive trait under Hardy-Weinberg "
            "equilibrium, what is the frequency of heterozygotes?")


class CalculationRenderingTests(unittest.TestCase):
    def render(self, question):
        from aura_bio.generation.calculations import render_validated_calculation
        return render_validated_calculation(question, hardy_weinberg(question, ""))

    def test_result_changes_with_premises_not_question_id(self):
        for percent, expected in ((16, "0.48 (48%)"), (9, "0.42 (42%)"), (1, "0.18 (18%)")):
            question = QUESTION.replace("16%", f"{percent}%")
            with self.subTest(percent=percent):
                text = self.render(question)
                self.assertIn(expected, text)
                self.assertFalse(any(c.verdict == "incorrect" for c in verify_numerical(question, text)))

    def test_explicit_allele_premise_and_requested_quantity_are_respected(self):
        question = ("In Hardy-Weinberg equilibrium, if p = 0.7, "
                    "what is the frequency of homozygous recessive individuals?")
        self.assertIn("0.09 (9%)", self.render(question))

    def test_ambiguous_or_qualitative_questions_are_not_rendered(self):
        questions = (
            "Explain Hardy-Weinberg equilibrium with 16% homozygous recessive.",
            QUESTION.replace("16%", "16% in population A and 9% in population B"),
            QUESTION.replace("16%", "-16%"),
            QUESTION.replace("16%", "160%"),
            QUESTION.replace("heterozygotes?", "heterozygotes and homozygous dominant individuals?"),
            QUESTION.replace("heterozygotes?", "heterozygotes? Explain the assumptions."),
            QUESTION + " What is the frequency of homozygous dominant individuals?",
            "Explain the equilibrium assumptions. " + QUESTION,
            QUESTION.replace("under Hardy-Weinberg equilibrium", "not under Hardy-Weinberg equilibrium"),
            "What is the frequency of heterozygotes under Hardy-Weinberg equilibrium?",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertIsNone(self.render(question))

    def test_inconsistent_solver_values_are_not_rendered(self):
        from dataclasses import replace
        from aura_bio.generation.calculations import render_validated_calculation
        checks = [replace(c, expected=0.24) if c.quantity == "2pq" else c
                  for c in hardy_weinberg(QUESTION, "")]
        self.assertIsNone(render_validated_calculation(QUESTION, checks))

    def test_model_cannot_overwrite_calculation_and_raw_draft_is_preserved(self):
        wrong = "2pq = 0.48. Therefore the frequency of heterozygotes is 0.24."
        generator = Generator([wrong])
        reviewed = []

        class Critic:
            def review(self, route, answer, evidence):
                reviewed.append(answer)
                return Critique(True)

        pipeline = AuraBioPipeline(generator, Searcher(), critic=Critic(),
                                   verifier=BiologyVerifier(use_entailment=False),
                                   accuracy_mode="robust", draft_candidates=1)
        result = pipeline.answer(QUESTION, context_level=2)
        self.assertIn("0.48 (48%)", result.text)
        self.assertNotIn("0.24", result.text)
        self.assertEqual(result.trace.final_record["generated_answer"], wrong)
        self.assertEqual(result.trace.final_record["answer_origin"], "validated_calculation")
        self.assertEqual(reviewed[0], result.text)
        self.assertFalse(any(i["kind"] == "wrong_value" for i in result.trace.final_verification["issues"]))

    def test_socratic_mode_does_not_reveal_a_tool_rendered_solution(self):
        hint = "Which allele frequency must you calculate first?"
        generator = Generator([hint])
        pipeline = AuraBioPipeline(generator, verifier=BiologyVerifier(use_entailment=False),
                                   accuracy_mode="robust", draft_candidates=1)
        result = pipeline.answer(QUESTION, teaching_mode="socratic", context_level=2)
        self.assertEqual(result.text, hint)
        self.assertEqual(result.trace.final_record["answer_origin"], "model")

    def test_raw_draft_truncation_is_not_attributed_to_complete_tool_answer(self):
        generator = Generator(["Incomplete calculation"])
        generator.last_metadata = {"done_reason": "length"}
        pipeline = AuraBioPipeline(generator, verifier=BiologyVerifier(use_entailment=False),
                                   accuracy_mode="robust", draft_candidates=1)
        result = pipeline.answer(QUESTION, context_level=2)
        self.assertIn("0.48 (48%)", result.text)
        self.assertEqual(result.trace.final_record["generation"]["done_reason"], "length")
        self.assertFalse(any(i["kind"] == "truncated_answer" for i in result.trace.final_verification["issues"]))

    def test_tool_rendering_does_not_clear_a_failed_review(self):
        class Rejecting:
            def review(self, route, answer, evidence):
                return Critique(False, process_errors=("Check the equilibrium assumption",), decision="revise")

        pipeline = AuraBioPipeline(Generator(["The result is 24%."]), critic=Rejecting(),
                                   verifier=BiologyVerifier(use_entailment=False),
                                   accuracy_mode="robust", draft_candidates=1)
        result = pipeline.answer(QUESTION, context_level=2)
        self.assertIn("0.48 (48%)", result.text)
        self.assertNotEqual(result.decision, "accept")
        self.assertEqual(result.trace.final_record["critique"]["decision"], "revise")


class FocusedRevisionTests(unittest.TestCase):
    def test_robust_revision_receives_previous_answer_without_extra_flag(self):
        wrong = "Glycolysis occurs in the mitochondria. [1]"
        good = "Glycolysis occurs in the cytoplasm. [1]"
        generator = Generator([wrong, good])
        pipeline = AuraBioPipeline(generator, Searcher(),
                                   verifier=BiologyVerifier(use_entailment=False),
                                   accuracy_mode="robust", draft_candidates=1)
        result = pipeline.answer("Where does glycolysis occur?", context_level=2)
        self.assertEqual(generator.calls[1][1], wrong)
        self.assertEqual(result.text, good)
        self.assertEqual(result.trace.retrieval["revision_context"], True)

    def test_focused_feedback_prioritises_defects_and_stays_bounded(self):
        from aura_bio.generation.prompts import focus_revision_instructions
        instructions = (
            "Cite the supplied passages as [1], [2] where they back a statement.",
            "Cover the missing concept: membrane",
            "Check this claim against the supplied passages: an unrelated detail",
            "Correct this process error: use 2pq, not pq",
            "Correct this terminology error: mitochondria",
            "Fix the wrong value: q is 0.4, not 0.16",
        )
        focused = focus_revision_instructions(instructions)
        self.assertEqual(len(focused), 4)
        self.assertEqual(focused[0], "Fix the wrong value: q is 0.4, not 0.16")
        self.assertIn("Correct this process error: use 2pq, not pq", focused)

    def test_calculation_feedback_does_not_demand_source_citations(self):
        report = BiologyVerifier(use_entailment=False).verify(
            "The frequency of heterozygotes is 0.24.",
            [EvidencePassage("hw", "Hardy-Weinberg equilibrium describes allele frequencies.")],
            question=QUESTION)
        edits = revision_instructions(report, None, require_citations=False)
        self.assertTrue(any("wrong value" in x for x in edits))
        self.assertFalse(any("Cite the supplied" in x for x in edits))

    def test_compact_corrections_precede_context_and_keep_all_passages(self):
        route = QueryRouter().route("Where does glycolysis occur?", context_level=2)
        evidence = [Passage(), Passage(chunk_id="g2", text="Cytoplasmic glycolysis produces pyruvate.")]
        prompt = build_prompt(route, evidence, ("Correct the compartment",),
                              previous_answer="Glycolysis occurs in the mitochondria.", profile="compact")
        self.assertLess(prompt.user.index("Correct the compartment"), prompt.user.index("[1]"))
        self.assertIn("Glycolysis occurs in the mitochondria.", prompt.user)
        self.assertIn(evidence[1].text, prompt.user)
        self.assertLess(len(prompt.system), 600)
