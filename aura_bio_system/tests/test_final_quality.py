"""Regression cases for compact delivery, selection and critic context."""

import unittest
from dataclasses import dataclass

from aura_bio.critique.external import build_critic_prompt
from aura_bio.generation import build_prompt
from aura_bio.generation.selection import candidate_quality
from aura_bio.pipeline import AuraBioPipeline
from aura_bio.routing import QueryRouter
from aura_bio.verification import BiologyVerifier, EvidencePassage


@dataclass
class Passage:
    chunk_id: str = "g"
    text: str = "Glycolysis occurs in the cytoplasm. " * 12
    title: str = "Glycolysis"
    source_id: str = "textbook"
    document_id: str = "g"
    section: str = "Introduction"
    rrf_score: float = 0.02
    rerank_score: float | None = None


class Searcher:
    def search(self, query, top_k, candidate_k):
        return [Passage()]


class Generator:
    def __init__(self, answer, metadata=None):
        self.answer = answer
        self.last_metadata = metadata or {}

    def generate(self, route, evidence, instructions, coverage_pool=(),
                 unknown_entities=(), previous_answer=""):
        return self.answer


class DeliveryTests(unittest.TestCase):
    def pipeline(self, text, metadata=None):
        return AuraBioPipeline(Generator(text, metadata), Searcher(),
                               verifier=BiologyVerifier(use_entailment=False),
                               accuracy_mode="robust", draft_candidates=1)

    def test_source_context_dump_is_not_approved_as_an_answer(self):
        text = ("Glycolysis occurs in the cytoplasm. [1]\n\n"
                "Relevant source excerpts:\n[1] Glycolysis\n" + Passage().text)
        result = self.pipeline(text).answer("Where does glycolysis occur?", context_level=2)
        self.assertEqual(result.text, text)  # detect, do not silently strip or rewrite
        self.assertNotEqual(result.decision, "accept")
        self.assertTrue(any(i["kind"] == "source_context_echo"
                            for i in result.trace.final_verification["issues"]))

    def test_explicit_request_for_a_source_quote_is_not_penalised(self):
        text = ("Glycolysis occurs in the cytoplasm. [1]\n\n"
                "Relevant source excerpts:\n[1] Glycolysis\n" + Passage().text)
        result = self.pipeline(text).answer("Quote the source about where glycolysis occurs.", context_level=2)
        self.assertFalse(any(i["kind"] == "source_context_echo"
                             for i in result.trace.final_verification["issues"]))

    def test_internal_style_heading_without_copied_source_is_not_an_echo(self):
        text = "Glycolysis occurs in the cytoplasm. [1]\n\nEvidence:\nThe cited passage supports the location."
        result = self.pipeline(text).answer("Where does glycolysis occur?", context_level=2)
        self.assertFalse(any(i["kind"] == "source_context_echo"
                             for i in result.trace.final_verification["issues"]))

    def test_prohibiting_quotes_does_not_exempt_a_source_dump(self):
        from aura_bio.verification.delivery import check_answer_delivery
        text = "Evidence:\n" + Passage().text
        issues = check_answer_delivery(text, [Passage()], {}, "Explain glycolysis. Do not quote the source.")
        self.assertTrue(any(i.kind == "source_context_echo" for i in issues))

    def test_verbatim_definition_without_context_heading_is_not_a_dump(self):
        from aura_bio.verification.delivery import check_answer_delivery
        self.assertEqual(check_answer_delivery(Passage().text, [Passage()], {},
                                               "Explain glycolysis"), [])

    def test_output_budget_exhaustion_cannot_receive_approval(self):
        result = self.pipeline("Glycolysis occurs in the cytoplasm. [1]",
                               {"done_reason": "length"}).answer("Where does glycolysis occur?", context_level=2)
        self.assertNotEqual(result.decision, "accept")
        self.assertTrue(any(i["kind"] == "truncated_answer" and i["severity"] == "error"
                            for i in result.trace.final_verification["issues"]))


class SelectionTests(unittest.TestCase):
    def quality(self, issues=(), critic_errors=0):
        return candidate_quality(
            "Where does glycolysis occur?", "Glycolysis occurs in the cytoplasm. [1]",
            {"claims": [], "issues": list(issues)},
            {"trusted": True, "unsupported_claims": ["review item"] * critic_errors},
            "revise", {"claim_citation_rate": 1.0})[0]

    def test_complete_answer_beats_truncation_despite_fewer_critic_flags(self):
        common = {"kind": "no_supported_inline_citation", "severity": "error"}
        complete = self.quality([common], critic_errors=3)
        truncated = self.quality([common, {"kind": "truncated_answer", "severity": "warning"}], critic_errors=1)
        self.assertGreater(complete, truncated)

    def test_source_dump_cannot_win_by_lower_critic_flag_count(self):
        complete = self.quality(critic_errors=2)
        echo = self.quality([{"kind": "source_context_echo", "severity": "warning"}], critic_errors=0)
        self.assertGreater(complete, echo)

    def test_numeric_error_is_not_offset_by_clean_formatting(self):
        incorrect = self.quality([{"kind": "wrong_value", "severity": "error"}])
        incomplete = self.quality([{"kind": "truncated_answer", "severity": "warning"}])
        self.assertGreater(incomplete, incorrect)

    def test_factual_error_still_loses_when_truncation_is_also_blocking(self):
        incorrect = self.quality([{"kind": "wrong_value", "severity": "error"}])
        incomplete = self.quality([{"kind": "truncated_answer", "severity": "error"}])
        self.assertGreater(incomplete, incorrect)


class CriticContextTests(unittest.TestCase):
    def test_relevant_support_beyond_initial_600_chars_reaches_critic(self):
        route = QueryRouter().route("Explain the action of helicase")
        useful = "Helicase unwinds the DNA double helix during replication."
        irrelevant = "Publisher licensing and contact information is listed here. " * 35
        evidence = [EvidencePassage("h", irrelevant + useful, "Helicase")]
        prompt = build_critic_prompt(route, "Helicase unwinds DNA. [1]", evidence)
        self.assertIn(useful, prompt)
        body = prompt.split("[1] Helicase\n", 1)[1].split("\n\nAnswer to review:", 1)[0]
        self.assertLessEqual(len(body), 600)

    def test_relevant_negation_and_source_number_are_preserved(self):
        route = QueryRouter().route("Does helicase synthesize primers?")
        negation = "Helicase does not synthesize primers; primase synthesizes RNA primers."
        irrelevant = "Publisher permissions are described separately. " * 30
        prompt = build_critic_prompt(route, "Helicase synthesizes primers. [2]", [
            EvidencePassage("a", "DNA replication uses several enzymes.", "Overview"),
            EvidencePassage("b", irrelevant + negation, "Primers"),
        ])
        self.assertIn("[1] Overview", prompt)
        self.assertIn("[2] Primers", prompt)
        self.assertIn(negation, prompt)

    def test_short_source_text_is_not_rewritten(self):
        text = "Helicase unwinds DNA. Primase produces RNA primers."
        prompt = build_critic_prompt(QueryRouter().route("Explain helicase"), "Helicase unwinds DNA.",
                                     [EvidencePassage("h", text, "Replication")])
        self.assertIn(text, prompt)

    def test_selected_sentences_keep_original_order_and_disclose_omissions(self):
        from aura_bio.critique.external import _critic_excerpt
        first = "Helicase unwinds the double helix."
        second = "Helicase does not synthesize RNA primers."
        irrelevant = "Publisher licensing information is listed here. " * 35
        excerpt = _critic_excerpt(first + " " + irrelevant + second,
                                   "Does helicase synthesize primers?", "Helicase synthesizes primers.")
        self.assertLess(excerpt.index(first), excerpt.index(second))
        self.assertIn("other text omitted", excerpt)
        self.assertLessEqual(len(excerpt), 600)

    def test_overlong_unsplittable_excerpt_is_bounded_and_marked_clipped(self):
        from aura_bio.critique.external import _critic_excerpt
        excerpt = _critic_excerpt("Helicase " + "unwinds DNA " * 150, "Explain helicase", "It unwinds DNA.")
        self.assertIn("Excerpt clipped", excerpt)
        self.assertLessEqual(len(excerpt), 600)

    def test_line_wrapped_negation_stays_with_the_statement_it_qualifies(self):
        from aura_bio.critique.external import _critic_excerpt
        source = ("Publisher licensing information is listed here. " * 35
                  + "Helicase synthesizes primers\n"
                  "in the fictional example, but it does not do so in real organisms.")
        excerpt = _critic_excerpt(source, "Does helicase synthesize primers?", "Helicase synthesizes primers.")
        self.assertIn("Helicase synthesizes primers", excerpt)
        self.assertIn("in the fictional example, but it does not do so in real organisms.", excerpt)


class CompactContractTests(unittest.TestCase):
    def test_compact_comparison_has_itemwise_citation_contract(self):
        route = QueryRouter().route("Describe the structure of an artery, vein and capillary")
        prompt = build_prompt(route, [Passage()], profile="compact")
        self.assertIn("one bullet per item", prompt.user.lower())
        self.assertIn("inline [n]", prompt.user)
        self.assertIn("Do not append source excerpts", prompt.user)

    def test_standard_prompt_does_not_get_compact_delivery_contract(self):
        route = QueryRouter().route("Describe the structure of an artery, vein and capillary")
        prompt = build_prompt(route, [Passage()])
        self.assertNotIn("Do not append source excerpts", prompt.user)

    def test_compact_socratic_mode_keeps_guidance_instead_of_revealing_solution(self):
        route = QueryRouter().route("Explain glycolysis", teaching_mode="socratic")
        prompt = build_prompt(route, [Passage()], profile="compact")
        self.assertIn("Do not reveal the full answer", prompt.user)
        self.assertNotIn("one bullet per item", prompt.user)
