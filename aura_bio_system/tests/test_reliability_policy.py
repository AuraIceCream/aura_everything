"""Regression cases from the 15-question trace review; no models or API calls."""

import unittest
from types import SimpleNamespace
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from aura_bio.api.mapping import answer_payload
from aura_bio.critique import Critique, combine_decision, parse_critique
from aura_bio.evaluation.schema import AnswerKey, BenchmarkQuestion, Difficulty
from aura_bio.evaluation.scorer import score_answer
from aura_bio.generation.selection import candidate_quality
from aura_bio.pipeline import AuraBioPipeline
from aura_bio.verification import BiologyVerifier, VerificationReport, verify_numerical


class Generator:
    def __init__(self, answer):
        self.answer = answer

    def generate(self, route, evidence, instructions, coverage_pool=(),
                 unknown_entities=(), previous_answer=""):
        return self.answer


class Searcher:
    def search(self, query, top_k, candidate_k):
        return [SimpleNamespace(chunk_id="g", text="Glycolysis occurs in the cytoplasm.",
                                title="Glycolysis", source_id="textbook", document_id="g",
                                section="Intro", rrf_score=0.02, rerank_score=None)]


class ReliabilityTests(unittest.TestCase):
    def pipeline(self, answer, critic=None, mode="robust"):
        return AuraBioPipeline(Generator(answer), Searcher(), critic=critic,
                               verifier=BiologyVerifier(use_entailment=False),
                               accuracy_mode=mode, draft_candidates=1)

    def test_untrusted_critic_is_degraded_not_approval(self):
        report = VerificationReport(grounded_fraction=1.0)
        self.assertEqual(combine_decision(report, parse_critique("broken JSON")), "degraded")

    def test_wrongly_typed_critic_boolean_cannot_become_approval(self):
        critique = parse_critique('{"answer_supported": "false", "decision": "accept"}')
        self.assertFalse(critique.trusted)
        self.assertEqual(combine_decision(VerificationReport(), critique), "degraded")

    def test_unreviewed_candidate_cannot_outrank_a_checked_candidate(self):
        unchecked, _ = candidate_quality("glycolysis", "Glycolysis occurs in the cytoplasm.",
                                         {"claims": [], "issues": []},
                                         {"trusted": False}, "degraded", {})
        checked, _ = candidate_quality("glycolysis", "Glycolysis occurs in the cytoplasm.",
                                       {"claims": [], "issues": []},
                                       {"trusted": True, "process_errors": ["Clarify the mechanism"]},
                                       "revise", {})
        self.assertGreater(checked, unchecked)

    def test_critic_exception_is_visible_in_both_pipeline_modes(self):
        class Unavailable:
            def review(self, route, answer, evidence):
                raise TimeoutError("provider unavailable")

        for mode in ("standard", "robust"):
            with self.subTest(mode=mode):
                result = self.pipeline("Glycolysis occurs in the cytoplasm. [1]", Unavailable(), mode).answer(
                    "Where does glycolysis occur?", context_level=2)
                self.assertEqual(result.decision, "degraded")
                self.assertEqual(result.trace.final_record["critique"]["failure_kind"], "TimeoutError")
                self.assertEqual(answer_payload(result, "local")["verification_status"], "partial")
                self.assertTrue(any("critic" in x.lower() for x in answer_payload(result, "local")["limitations"]))

    def test_robust_uncited_answer_is_not_approved_or_silently_cited(self):
        text = "Glycolysis occurs in the cytoplasm."
        result = self.pipeline(text).answer("Where does glycolysis occur?", context_level=2)
        self.assertEqual(result.decision, "revise")
        self.assertEqual(result.text, text)
        self.assertTrue(any(x["kind"] == "no_supported_inline_citation"
                            for x in result.trace.final_verification["issues"]))

    def test_supported_inline_citation_can_be_approved(self):
        result = self.pipeline("Glycolysis occurs in the cytoplasm. [1]").answer(
            "Where does glycolysis occur?", context_level=2)
        self.assertEqual(result.decision, "accept")

    def test_references_list_does_not_replace_inline_support(self):
        result = self.pipeline("Glycolysis occurs in the cytoplasm.\nReferences:\n[1]").answer(
            "Where does glycolysis occur?", context_level=2)
        self.assertNotEqual(result.decision, "accept")

    def test_citation_to_an_unrelated_passage_is_not_support(self):
        from aura_bio.verification import EvidencePassage
        from aura_bio.verification.provenance import enforce_inline_support

        passages = [EvidencePassage("g", "Glycolysis occurs in the cytoplasm."),
                    EvidencePassage("p", "Photosynthesis occurs in chloroplasts.")]
        answer = "Glycolysis occurs in the cytoplasm. [2]"
        report = BiologyVerifier(use_entailment=False).verify(answer, passages)
        enforce_inline_support(answer, passages, report)
        self.assertEqual(report.decision(), "revise")

    def test_question_derived_calculation_is_not_forced_to_invent_a_source(self):
        result = self.pipeline("The frequency of heterozygotes is 0.48.").answer(
            "If 16% show a recessive trait under Hardy-Weinberg equilibrium, "
            "what is the frequency of heterozygotes?", context_level=2)
        self.assertFalse(any(x["kind"] == "no_supported_inline_citation"
                             for x in result.trace.final_verification["issues"]))

    def test_citation_to_a_second_supporting_passage_can_be_approved(self):
        from aura_bio.verification import EvidencePassage
        from aura_bio.verification.provenance import enforce_inline_support

        passages = [EvidencePassage("g1", "Glycolysis occurs in the cytoplasm."),
                    EvidencePassage("g2", "Glycolysis occurs in the cytoplasm of cells.")]
        answer = "Glycolysis occurs in the cytoplasm. [2]"
        report = BiologyVerifier(use_entailment=False).verify(answer, passages)
        enforce_inline_support(answer, passages, report)
        self.assertEqual(report.decision(), "accept")
        self.assertEqual(report.checker_status["inline_citations"], "supported")


class NumericConclusionTests(unittest.TestCase):
    def question(self, expected=0.48, text=None):
        return BenchmarkQuestion("numeric", text or
                                 "If 16% show a recessive trait under Hardy-Weinberg equilibrium, find heterozygote frequency.",
                                 "genetics", "calculation", "high_school", Difficulty.MEDIUM,
                                 AnswerKey(numeric=expected))

    def test_wrong_conclusion_cannot_pass_using_a_correct_number_in_working(self):
        answer = "2pq = 0.48. Therefore the frequency of heterozygotes for the ALPL gene is 0.24, or 24%."
        self.assertFalse(score_answer(self.question(), answer).numeric_correct)
        self.assertTrue(any(c.quantity == "2pq" and c.verdict == "incorrect"
                            for c in verify_numerical(self.question().question, answer)))

    def test_correct_conclusion_percent_is_accepted(self):
        self.assertTrue(score_answer(self.question(), "q = 0.4; p = 0.6. Therefore 48% are heterozygotes.").numeric_correct)

    def test_correct_conclusion_fraction_is_accepted(self):
        self.assertTrue(score_answer(self.question(0.25, "Find the probability."),
                                     "Therefore the probability is 1/4.").numeric_correct)

    def test_correct_unrelated_solver_result_cannot_override_declared_target(self):
        question = self.question(0.75, "In a heterozygous x heterozygous cross, find the dominant phenotype fraction.")
        self.assertFalse(score_answer(question, "The recessive fraction is 0.25.").numeric_correct)

    def test_rescoring_preserves_original_answers_and_trace(self):
        from aura_bio.evaluation.rescore import rescore_file

        question = self.question()
        with TemporaryDirectory() as temp:
            source = Path(temp) / "old.jsonl"
            original = {"id": question.id, "answer": "2pq = 0.48. Therefore the frequency is 24%.",
                        "score": {"overall": 1.0}, "trace": {"decision": "accept"}, "error": None}
            source.write_text(json.dumps(original) + "\n", encoding="utf-8")
            before = source.read_bytes()
            out, summary = rescore_file(source, {question.id: question}, "corrected")
            row = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(row["answer"], original["answer"])
            self.assertEqual(row["trace"], original["trace"])
            self.assertFalse(row["score"]["numeric_correct"])
            self.assertEqual(summary["questions"], 1)
            self.assertTrue(row["rescoring"]["trace_not_rerun"])

    def test_rescoring_refuses_to_overwrite_existing_output(self):
        from aura_bio.evaluation.rescore import rescore_file

        question = self.question()
        with TemporaryDirectory() as temp:
            source = Path(temp) / "old.jsonl"
            source.write_text(json.dumps({"id": question.id, "answer": "0.48", "error": None}) + "\n", encoding="utf-8")
            out, _ = rescore_file(source, {question.id: question}, "corrected")
            before = out.read_bytes()
            with self.assertRaises(FileExistsError):
                rescore_file(source, {question.id: question}, "corrected")
            self.assertEqual(out.read_bytes(), before)

    def test_rescoring_keeps_failed_requests_at_zero(self):
        from aura_bio.evaluation.rescore import rescore_file

        question = self.question()
        with TemporaryDirectory() as temp:
            source = Path(temp) / "failed.jsonl"
            source.write_text(json.dumps({"id": question.id, "answer": "",
                                          "error": "TimeoutError"}) + "\n", encoding="utf-8")
            out, summary = rescore_file(source, {question.id: question}, "corrected")
            row = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(row["score"]["overall"], 0.0)
            self.assertEqual(summary["overall_mean"], 0.0)
            self.assertEqual(summary["errors"], 1)
