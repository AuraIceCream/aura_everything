from __future__ import annotations

import unittest

from aura_bio.critique import CRITIC_CASES, compare_critics, format_comparison_table
from aura_bio.critique.external import CriticResult, build_critic_prompt
from aura_bio.critique.schema import parse_critique
from aura_bio.routing import QueryRouter
from aura_bio.verification import EvidencePassage


class StubCritic:
    """A deterministic critic: revises iff the answer contradicts an oracle set.

    Stands in for a real API so the comparison harness can be tested offline.
    """

    def __init__(self, name: str, oracle: bool, latency: float = 12.0) -> None:
        self.name = name
        self.oracle = oracle  # if True, always returns the correct verdict
        self.latency = latency

    def review_detailed(self, route, answer, evidence):
        from aura_bio.critique.comparison import CRITIC_CASES as cases

        should = next((c.should_revise for c in cases if c.answer == answer), False)
        verdict = should if self.oracle else False  # non-oracle rubber-stamps "accept"
        payload = (
            '{"answer_supported": %s, "decision": "%s", "teaching_quality_score": 4, '
            '"academic_level_match": true, "unsupported_claims": [], "terminology_errors": [], '
            '"process_errors": [], "missing_concepts": []}'
            % ("false" if verdict else "true", "revise" if verdict else "accept")
        )
        return CriticResult(parse_critique(payload, self.name), self.latency, 120, 60, payload)


class PromptTests(unittest.TestCase):
    def test_prompt_includes_question_answer_and_numbered_evidence(self) -> None:
        route = QueryRouter().route("Explain helicase")
        prompt = build_critic_prompt(
            route, "Helicase unwinds DNA.", [EvidencePassage("c", "Helicase unwinds the double helix.", "Helicase")]
        )
        self.assertIn("Explain helicase", prompt)
        self.assertIn("[1]", prompt)
        self.assertIn("Helicase unwinds DNA.", prompt)
        self.assertIn("JSON", prompt)


class ComparisonTests(unittest.TestCase):
    def test_oracle_critic_beats_rubber_stamp(self) -> None:
        good = StubCritic("oracle", oracle=True)
        lazy = StubCritic("rubber-stamp", oracle=False)
        result = compare_critics([good, lazy])
        self.assertEqual(result["cases"], len(CRITIC_CASES))
        by_name = {c["critic"]: c for c in result["critics"]}
        self.assertEqual(by_name["oracle"]["decision_accuracy"], 1.0)
        # A critic that accepts everything misses every answer that needs revising.
        self.assertGreater(by_name["rubber-stamp"]["false_accept_rate"], 0.0)
        self.assertLess(by_name["rubber-stamp"]["decision_accuracy"], 1.0)

    def test_rubber_stamp_has_zero_false_revises(self) -> None:
        lazy = StubCritic("rubber-stamp", oracle=False)
        result = compare_critics([lazy])
        self.assertEqual(result["critics"][0]["false_revise_rate"], 0.0)

    def test_verifier_only_baseline_is_reported(self) -> None:
        result = compare_critics([StubCritic("x", oracle=True)])
        self.assertIn("verifier_only_accuracy", result)
        self.assertGreaterEqual(result["verifier_only_accuracy"], 0.0)

    def test_table_renders(self) -> None:
        result = compare_critics([StubCritic("oracle", oracle=True)])
        table = format_comparison_table(result)
        self.assertIn("Decision acc.", table)
        self.assertIn("Deterministic verifier alone", table)

    def test_cases_are_balanced(self) -> None:
        revise = sum(1 for c in CRITIC_CASES if c.should_revise)
        sound = sum(1 for c in CRITIC_CASES if not c.should_revise)
        self.assertGreaterEqual(revise, 4)
        self.assertGreaterEqual(sound, 4)


class ParseTests(unittest.TestCase):
    def test_glm_style_json_object_parses(self) -> None:
        critique = parse_critique('{"answer_supported": false, "decision": "revise"}', "zai:glm-4.7-flash")
        self.assertTrue(critique.trusted)
        self.assertEqual(critique.decision, "revise")

    def test_empty_response_is_untrusted(self) -> None:
        self.assertFalse(parse_critique("", "gemini:gemini-2.5-flash").trusted)


if __name__ == "__main__":
    unittest.main()
