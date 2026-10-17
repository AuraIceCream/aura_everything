from dataclasses import dataclass
import unittest

from aura_bio.critique import Critique, revision_instructions, combine_decision
from aura_bio.pipeline import AuraBioPipeline
from aura_bio.routing import QueryRouter
from aura_bio.verification import BiologyVerifier, VerificationReport


@dataclass
class Passage:
    chunk_id: str
    text: str
    title: str = "Glycolysis"
    source_id: str = "textbook"
    document_id: str = "glycolysis"
    section: str = "Introduction"
    rrf_score: float = 0.02
    rerank_score: float | None = None
    channel: str = "core_bm25"


class Searcher:
    def __init__(self, passages):
        self.passages = passages

    def search(self, query, top_k, candidate_k):
        return self.passages[:top_k]


class Generator:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def generate(self, route, evidence, instructions, coverage_pool=(),
                 unknown_entities=(), previous_answer=""):
        self.calls.append((tuple(instructions), previous_answer))
        return self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]


class CriticFeedbackTests(unittest.TestCase):
    def test_critic_cannot_accept_while_reporting_a_process_error(self):
        report = VerificationReport(grounded_fraction=1.0)
        critique = Critique(True, process_errors=("Metaphase follows prophase",), decision="accept")
        self.assertEqual(combine_decision(report, critique), "revise")

    def test_revisions_address_the_critic_reasons_for_rejection(self):
        critique = Critique(
            answer_supported=False, decision="revise",
            unsupported_claims=("Capillary walls consist of red blood cells",),
            terminology_errors=("mitochondira is misspelled",),
            process_errors=("Metaphase must precede anaphase",),
        )
        instructions = " ".join(revision_instructions(VerificationReport(), critique))
        self.assertIn("Capillary walls consist of red blood cells", instructions)
        self.assertIn("mitochondira is misspelled", instructions)
        self.assertIn("Metaphase must precede anaphase", instructions)

    def test_untrusted_critic_cannot_inject_revision_content(self):
        critique = Critique(False, process_errors=("invent a pathway",), trusted=False)
        self.assertNotIn("invent", " ".join(revision_instructions(VerificationReport(), critique)))


class CandidateSelectionTests(unittest.TestCase):
    def test_question_calculation_reaches_every_robust_draft(self):
        generator = Generator(["The heterozygote frequency is 0.48."])
        answer = self.pipeline(generator).answer(
            "If 16% of a population shows a recessive trait under Hardy-Weinberg "
            "equilibrium, what is the frequency of heterozygotes?", context_level=2)
        for instructions, _ in generator.calls:
            content = " ".join(instructions)
            self.assertIn("2pq = 0.48", content)
            self.assertIn("q = 0.4", content)
            self.assertIn("question", content)
        self.assertTrue(answer.trace.retrieval["calculations"])

    def test_calculation_survives_critic_feedback_in_revision(self):
        class Rejecting:
            def review(self, route, answer, evidence):
                return Critique(False, process_errors=("Correct the explanation",), decision="revise")

        generator = Generator(["The heterozygote frequency is 0.32."])
        self.pipeline(generator, Rejecting(), drafts=1).answer(
            "If 16% show a recessive trait under Hardy-Weinberg equilibrium, "
            "what is the frequency of heterozygotes?", context_level=2)
        self.assertGreater(len(generator.calls), 1)
        self.assertIn("2pq = 0.48", " ".join(generator.calls[-1][0]))

    def test_calculation_is_not_injected_when_numeric_checks_are_disabled(self):
        generator = Generator(["The heterozygote frequency is 0.48."])
        pipeline = self.pipeline(generator)
        pipeline.verifier.check_numbers = False
        answer = pipeline.answer(
            "If 16% show a recessive trait under Hardy-Weinberg equilibrium, "
            "what is the frequency of heterozygotes?", context_level=2)
        self.assertEqual(answer.trace.retrieval.get("calculations", []), [])
        self.assertNotIn("2pq = 0.48", " ".join(generator.calls[0][0]))

    def test_unrecognised_question_has_no_computed_values(self):
        generator = Generator(["Glycolysis occurs in the cytoplasm. [1]"])
        answer = self.pipeline(generator).answer("Where does glycolysis occur?", context_level=2)
        self.assertEqual(answer.trace.retrieval.get("calculations", []), [])
        self.assertNotIn("Deterministic", " ".join(generator.calls[0][0]))

    def test_verification_records_the_backend_that_actually_ran(self):
        from aura_bio.verification import EvidencePassage

        report = BiologyVerifier(use_entailment=False).verify(
            "Glycolysis occurs in the cytoplasm. [1]",
            [EvidencePassage("g", "Glycolysis occurs in the cytoplasm.")])
        self.assertEqual(report.as_dict()["support_backend"], "lexical")

    def pipeline(self, generator, critic=None, drafts=2):
        return AuraBioPipeline(
            generator=generator,
            searcher=Searcher([Passage("g", "Glycolysis occurs in the cytoplasm and produces two net ATP.")]),
            verifier=BiologyVerifier(use_entailment=False), critic=critic,
            accuracy_mode="robust", draft_candidates=drafts,
        )

    def test_good_draft_survives_a_worse_alternative(self):
        good = "Glycolysis occurs in the cytoplasm and produces two net ATP. [1]"
        generator = Generator([good, "Glycolysis occurs in the mitochondria and produces ten net ATP. [1]"])
        answer = self.pipeline(generator).answer("Where does glycolysis occur and what is its net ATP yield?", context_level=2)
        self.assertEqual(answer.text, good)
        self.assertEqual(answer.decision, "accept")
        self.assertEqual(answer.trace.selected_revision, 0)
        self.assertEqual(answer.trace.final_verification["decision"], "accept")
        self.assertEqual(len(answer.trace.revisions), 2)

    def test_revisions_are_ranked_instead_of_blindly_returning_the_last(self):
        class Rejecting:
            def review(self, route, answer, evidence):
                return Critique(False, process_errors=("Clarify the mechanism",), decision="revise")

        first = "Glycolysis occurs in the mitochondria and produces two net ATP. [1]"
        second = "Glycolysis occurs in the mitochondria and produces ten net ATP. [1]"
        generator = Generator([first, second])
        answer = self.pipeline(generator, Rejecting(), drafts=1).answer("Where does glycolysis occur and what is its net ATP yield?", context_level=2)
        self.assertEqual(answer.text, first)
        self.assertEqual(answer.decision, "revise")
        self.assertEqual(answer.trace.selected_revision, 0)

    def test_empty_completion_is_never_the_accepted_best_candidate(self):
        generator = Generator(["", "Glycolysis occurs in the cytoplasm and produces two net ATP. [1]"])
        answer = self.pipeline(generator).answer("Where does glycolysis occur?", context_level=2)
        self.assertTrue(answer.text)
        self.assertEqual(answer.decision, "accept")

    def test_critic_feedback_can_trigger_targeted_revision(self):
        class Critic:
            def review(self, route, answer, evidence):
                if "mitochondria" in answer:
                    return Critique(False, process_errors=("Glycolysis occurs in the cytoplasm",), decision="revise")
                return Critique(True)

        good = "Glycolysis occurs in the cytoplasm and produces two net ATP. [1]"
        generator = Generator(["Glycolysis occurs in the mitochondria. [1]", good])
        answer = self.pipeline(generator, Critic(), drafts=1).answer("Where does glycolysis occur?", context_level=2)
        self.assertEqual(answer.text, good)
        self.assertIn("Glycolysis occurs in the cytoplasm", " ".join(generator.calls[1][0]))


class DiversityTests(unittest.TestCase):
    def test_diversity_never_promotes_a_very_low_relevance_distractor(self):
        from aura_bio.retrieval.reranker import select_diverse_evidence

        passages = [Passage("a", "An artery carries blood away from the heart.", rerank_score=0.95),
                    Passage("v", "A vein returns blood to the heart.", title="Vein", document_id="vein", rerank_score=0.8),
                    Passage("noise", "This software compares artery and vein markup examples.",
                            title="Markup", document_id="software", rerank_score=0.001)]
        chosen = select_diverse_evidence("Compare an artery and a vein", passages, max_passages=5)
        self.assertEqual({p.chunk_id for p in chosen}, {"a", "v"})

    def test_single_document_can_supply_more_distinct_evidence_when_no_alternative_exists(self):
        from aura_bio.retrieval.reranker import select_diverse_evidence

        passages = [Passage("a", "An artery carries blood away from the heart.", title="Vessels", document_id="vessels"),
                    Passage("v", "A vein returns blood and has valves.", title="Vessels", document_id="vessels"),
                    Passage("c", "A capillary wall is one cell thick for diffusion.", title="Vessels", document_id="vessels")]
        chosen = select_diverse_evidence("Describe artery, vein and capillary walls", passages, max_passages=3)
        self.assertEqual({p.chunk_id for p in chosen}, {"a", "v", "c"})

    def test_compression_does_not_modify_candidates_kept_for_audit(self):
        from aura_bio.retrieval.strategies import compress_evidence

        text = ("A long publisher notice is unrelated to biology. "
                "Helicase unwinds the DNA double helix during replication. "
                "Another publisher notice describes licensing restrictions. "
                "A third publisher notice describes contact information.")
        original = Passage("a", text)
        [trimmed] = compress_evidence("helicase DNA replication", [original], max_sentences=1)
        self.assertEqual(original.text, text)
        self.assertNotIn("publisher", trimmed.text)

    def test_selection_can_recover_a_complementary_passage_beyond_final_top_k(self):
        from aura_bio.retrieval.reranker import CrossEncoderReranker

        class Scores:
            def predict(self, pairs):
                return [0.99 - 0.01 * index for index in range(len(pairs))]

        passages = [Passage(f"a{index}", "An artery has a thick muscular wall.", title="Artery", document_id="artery")
                    for index in range(6)]
        passages.append(Passage("v", "A vein has valves and a thinner wall.", title="Vein", document_id="vein"))
        generator = Generator(["Arteries have thick muscular walls, while veins have thinner walls and valves. [1] [2]"])
        answer = AuraBioPipeline(generator, Searcher(passages),
                                 verifier=BiologyVerifier(use_entailment=False),
                                 reranker=CrossEncoderReranker(scorer=Scores()),
                                 accuracy_mode="robust", draft_candidates=1).answer(
                                     "Compare an artery and a vein", context_level=1)
        self.assertIn("v", [p["chunk_id"] for p in answer.trace.evidence])

    def test_redundant_top_hits_do_not_exclude_other_comparison_subjects(self):
        from aura_bio.retrieval.reranker import select_diverse_evidence

        artery = "An artery carries blood away from the heart and has a thick muscular wall."
        passages = [
            Passage("a1", artery, title="Artery", document_id="artery"),
            Passage("a2", artery + " Arterial pressure is high.", title="Artery", document_id="artery"),
            Passage("v", "A vein returns blood to the heart and contains valves.", title="Vein", document_id="vein"),
            Passage("c", "A capillary has a wall one endothelial cell thick for exchange.", title="Capillary", document_id="capillary"),
        ]
        chosen = select_diverse_evidence("Describe the structure of an artery, vein, and capillary", passages, max_passages=3)
        self.assertEqual({p.chunk_id for p in chosen}, {"a1", "v", "c"})

    def test_exact_duplicates_are_removed_across_sources(self):
        from aura_bio.retrieval.reranker import select_diverse_evidence

        passages = [Passage("a", "Glycolysis occurs in the cytoplasm."),
                    Passage("b", "Glycolysis occurs in the cytoplasm.", source_id="other", document_id="other")]
        self.assertEqual(len(select_diverse_evidence("Glycolysis", passages, max_passages=4)), 1)

    def test_budget_is_hard_even_for_the_first_passage(self):
        from aura_bio.retrieval.reranker import select_diverse_evidence

        passages = [Passage("big", "word " * 100), Passage("small", "Glycolysis occurs in the cytoplasm.")]
        chosen = select_diverse_evidence("Glycolysis", passages, max_passages=4, max_chars=100)
        self.assertEqual([p.chunk_id for p in chosen], ["small"])
        self.assertLessEqual(sum(len(p.text) for p in chosen), 100)


class QueryExpansionTests(unittest.TestCase):
    def test_list_question_expands_all_subjects_with_shared_context(self):
        from aura_bio.retrieval.strategies import query_variants

        query = "Describe the structure of an artery, vein, and capillary"
        parts = query_variants(query)
        self.assertEqual(parts[0], query)
        for subject in ("artery", "vein", "capillary"):
            self.assertTrue(any(subject in p and "structure" in p and "," not in p for p in parts[1:]))

    def test_single_topic_is_not_expanded_with_invented_facts(self):
        from aura_bio.retrieval.strategies import query_variants

        self.assertEqual(query_variants("Define osmosis"), ["Define osmosis"])


class TracePresentationTests(unittest.TestCase):
    def test_final_payload_uses_the_selected_answers_issues(self):
        from aura_bio.api.mapping import answer_payload
        from aura_bio.pipeline import Answer
        from aura_bio.tracing import Trace

        trace = Trace(query="Where does glycolysis occur?", selected_revision=1)
        trace.revisions = [
            {"phase": "draft", "verification": {"grounded_fraction": 0.2, "claims": [], "issues": [{"severity": "error", "detail": "wrong draft"}]}},
            {"phase": "draft", "verification": {"grounded_fraction": 1.0, "claims": [], "issues": []}},
        ]
        payload = answer_payload(Answer("Glycolysis occurs in the cytoplasm.", "accept", 1.0, trace), "local")
        self.assertEqual(payload["limitations"], [])
        self.assertFalse(payload["revised"])


if __name__ == "__main__":
    unittest.main()
