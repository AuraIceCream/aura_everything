from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from aura_bio.critique import Critique, combine_decision, parse_critique, revision_instructions
from aura_bio.pipeline import AuraBioPipeline
from aura_bio.routing import QueryRouter
from aura_bio.tracing import FAILURE_CATEGORIES, Trace, TraceStore, classify_failure
from aura_bio.verification import BiologyVerifier, EvidencePassage


@dataclass
class FakeEvidence:
    chunk_id: str
    text: str
    source_id: str = "wikipedia_biology"
    title: str = "Helicase"
    section: str | None = "Mechanism"
    url: str | None = "https://example.test/a"
    channel: str = "dense+core_bm25"
    rerank_score: float | None = None


class FakeSearcher:
    def __init__(self, evidence: Sequence[FakeEvidence]) -> None:
        self.evidence = list(evidence)
        self.calls: list[tuple[str, int, int]] = []

    def search(self, query: str, top_k: int, candidate_k: int) -> list[FakeEvidence]:
        self.calls.append((query, top_k, candidate_k))
        return self.evidence[:top_k]


@dataclass
class ScriptedGenerator:
    """Returns each scripted answer in turn, recording what it was told."""

    answers: list[str]
    seen_instructions: list[tuple[str, ...]] = field(default_factory=list)
    seen_evidence: list[int] = field(default_factory=list)
    seen_coverage: list[int] = field(default_factory=list)
    seen_unknown: list[tuple[str, ...]] = field(default_factory=list)

    def generate(self, route, evidence, instructions, coverage_pool=(), unknown_entities=()) -> str:
        self.seen_instructions.append(tuple(instructions))
        self.seen_evidence.append(len(evidence))
        self.seen_coverage.append(len(coverage_pool))
        self.seen_unknown.append(tuple(unknown_entities))
        index = min(len(self.seen_instructions) - 1, len(self.answers) - 1)
        return self.answers[index]


GOOD = "Helicase unwinds the double helix at the origin of replication. [1]"
BAD = "Helicase always dissolves every chromosome in the mitochondira instantly. [1]"

EVIDENCE = [
    FakeEvidence(
        "c1",
        "Helicase unwinds the double helix at the origin of replication, "
        "separating the parental strands during DNA replication.",
    ),
    FakeEvidence("c2", "Primase synthesises a short RNA primer for DNA polymerase.", source_id="pmc_oa_comm_xml"),
]


class PipelineTests(unittest.TestCase):
    def test_end_to_end_accept(self) -> None:
        generator = ScriptedGenerator([GOOD])
        pipeline = AuraBioPipeline(generator=generator, searcher=FakeSearcher(EVIDENCE))
        answer = pipeline.answer("How does helicase work in DNA replication?")
        self.assertEqual(answer.decision, "accept")
        self.assertEqual(answer.text, GOOD)
        self.assertEqual(len(answer.trace.revisions), 1)
        self.assertTrue(answer.sources)
        self.assertEqual(answer.sources[0]["source"], "wikipedia_biology")

    def test_bad_draft_triggers_one_revision(self) -> None:
        generator = ScriptedGenerator([BAD, GOOD])
        pipeline = AuraBioPipeline(generator=generator, searcher=FakeSearcher(EVIDENCE))
        answer = pipeline.answer("How does helicase work in DNA replication?")
        self.assertEqual(len(answer.trace.revisions), 2)
        self.assertEqual(answer.decision, "accept")
        # The revision prompt must name the actual defects, not just say "fix".
        self.assertTrue(generator.seen_instructions[1])
        self.assertTrue(
            any("mitochondira" in item for item in generator.seen_instructions[1])
        )

    def test_revision_budget_is_respected(self) -> None:
        generator = ScriptedGenerator([BAD])
        pipeline = AuraBioPipeline(generator=generator, searcher=FakeSearcher(EVIDENCE))
        answer = pipeline.answer("How does helicase work in DNA replication?")
        budget = answer.trace.route["max_revisions"]
        self.assertEqual(len(answer.trace.revisions), budget + 1)
        self.assertNotEqual(answer.decision, "accept")

    def test_level_zero_query_skips_retrieval(self) -> None:
        searcher = FakeSearcher(EVIDENCE)
        pipeline = AuraBioPipeline(generator=ScriptedGenerator(["Hello, ask me a biology question."]), searcher=searcher)
        answer = pipeline.answer("hello")
        self.assertEqual(searcher.calls, [])
        self.assertEqual(answer.trace.evidence, [])

    def test_stage_timings_are_recorded(self) -> None:
        pipeline = AuraBioPipeline(generator=ScriptedGenerator([GOOD]), searcher=FakeSearcher(EVIDENCE))
        trace = pipeline.answer("How does helicase work in DNA replication?").trace
        self.assertIn("routing", trace.stage_ms)
        self.assertIn("retrieval", trace.stage_ms)
        self.assertIn("generation", trace.stage_ms)
        self.assertIn("verification", trace.stage_ms)
        self.assertGreaterEqual(trace.latency_ms, 0.0)

    def test_trace_is_json_serialisable(self) -> None:
        pipeline = AuraBioPipeline(generator=ScriptedGenerator([GOOD]), searcher=FakeSearcher(EVIDENCE))
        json.dumps(pipeline.answer("Explain DNA replication").trace.as_dict())

    def test_failing_critic_does_not_break_the_request(self) -> None:
        class Broken:
            def review(self, route, answer, evidence):
                raise RuntimeError("critic API down")

        pipeline = AuraBioPipeline(
            generator=ScriptedGenerator([GOOD]), searcher=FakeSearcher(EVIDENCE), critic=Broken()
        )
        answer = pipeline.answer("How does helicase work in DNA replication?")
        self.assertEqual(answer.decision, "accept")
        self.assertIsNone(answer.trace.revisions[0]["critique"])

    def test_critic_can_force_a_revision(self) -> None:
        class Strict:
            def review(self, route, answer, evidence):
                return Critique(
                    answer_supported=True,
                    missing_concepts=("role of primase",),
                    decision="revise",
                    model="stub",
                )

        generator = ScriptedGenerator([GOOD, GOOD])
        pipeline = AuraBioPipeline(
            generator=generator, searcher=FakeSearcher(EVIDENCE), critic=Strict()
        )
        answer = pipeline.answer("How does helicase work in DNA replication?")
        self.assertEqual(len(answer.trace.revisions), 2)
        self.assertTrue(
            any("primase" in item for item in generator.seen_instructions[1])
        )


class CritiqueParsingTests(unittest.TestCase):
    def test_parses_fenced_json(self) -> None:
        payload = """Here is my review:
```json
{"answer_supported": true, "missing_concepts": ["role of helicase"],
 "teaching_quality_score": 4, "decision": "revise"}
```
"""
        critique = parse_critique(payload, model="gemini-flash")
        self.assertTrue(critique.trusted)
        self.assertEqual(critique.decision, "revise")
        self.assertEqual(critique.missing_concepts, ("role of helicase",))
        self.assertEqual(critique.teaching_quality_score, 4)

    def test_garbage_becomes_untrusted_not_an_accept(self) -> None:
        critique = parse_critique("I could not evaluate this.", model="stub")
        self.assertFalse(critique.trusted)
        self.assertEqual(critique.decision, "revise")

    def test_score_is_clamped(self) -> None:
        critique = parse_critique('{"teaching_quality_score": 99, "decision": "accept"}')
        self.assertEqual(critique.teaching_quality_score, 5)

    def test_unknown_decision_defaults_to_revise(self) -> None:
        self.assertEqual(parse_critique('{"decision": "looks fine"}').decision, "revise")

    def test_untrusted_critic_cannot_block_a_clean_answer(self) -> None:
        report = BiologyVerifier().verify(
            "Helicase unwinds DNA during replication. [1]",
            [EvidencePassage("c1", "Helicase unwinds DNA during replication.")],
        )
        self.assertEqual(report.decision(), "accept")
        self.assertEqual(combine_decision(report, parse_critique("nonsense")), "accept")

    def test_critic_cannot_approve_over_a_verifier_error(self) -> None:
        report = BiologyVerifier().verify("Glycolysis occurs in the mitochondria of the cell.", [])
        approving = Critique(answer_supported=True, decision="accept", model="stub")
        self.assertEqual(combine_decision(report, approving), "revise")


class TraceStoreTests(unittest.TestCase):
    def test_records_and_reads_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = TraceStore(root / "traces.sqlite3", root / "traces.jsonl")
            try:
                pipeline = AuraBioPipeline(
                    generator=ScriptedGenerator([GOOD]),
                    searcher=FakeSearcher(EVIDENCE),
                    store=store,
                )
                pipeline.answer("How does helicase work in DNA replication?")
                recent = store.recent()
                self.assertEqual(len(recent), 1)
                self.assertEqual(recent[0]["decision"], "accept")
                lines = (root / "traces.jsonl").read_text(encoding="utf-8").strip().split("\n")
                self.assertEqual(len(lines), 1)
            finally:
                store.close()

    def test_failure_is_recorded_and_exported_only_when_approved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = TraceStore(root / "traces.sqlite3")
            try:
                pipeline = AuraBioPipeline(
                    generator=ScriptedGenerator([BAD]),
                    searcher=FakeSearcher(EVIDENCE),
                    store=store,
                )
                answer = pipeline.answer("How does helicase work in DNA replication?")
                self.assertIsNotNone(answer.trace.failure_category)
                self.assertIn(answer.trace.failure_category, FAILURE_CATEGORIES)
                export = root / "failures.jsonl"
                self.assertEqual(store.export_failures(export, approved_only=True), 0)
                self.assertEqual(store.export_failures(export, approved_only=False), 1)
                record = json.loads(export.read_text(encoding="utf-8").strip())
                self.assertEqual(record["approved_for_training"], 0)
            finally:
                store.close()

    def test_unknown_failure_category_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = TraceStore(Path(temporary) / "t.sqlite3")
            try:
                with self.assertRaises(ValueError):
                    store.record_failure(Trace(query="q"), "not_a_category")
            finally:
                store.close()

    def test_process_error_is_classified(self) -> None:
        trace = Trace(query="Explain mitosis")
        trace.route = QueryRouter().route("Explain mitosis").as_dict()
        report = BiologyVerifier().verify(
            "In mitosis the cell enters anaphase, then metaphase, then prophase.",
            [],
            QueryRouter().route("Explain mitosis"),
        )
        trace.revisions = [{"verification": report.as_dict()}]
        self.assertEqual(classify_failure(trace), "process_order_error")


class RevisionInstructionTests(unittest.TestCase):
    def test_instructions_are_deduplicated(self) -> None:
        report = BiologyVerifier().verify("The mitochondira make ATP. The mitochondira are organelles.", [])
        instructions = revision_instructions(report, None)
        self.assertEqual(len(instructions), len(set(instructions)))

    def test_no_findings_means_no_instructions(self) -> None:
        report = BiologyVerifier().verify(
            "Helicase unwinds DNA during replication. [1]",
            [EvidencePassage("c1", "Helicase unwinds DNA during replication.")],
        )
        self.assertEqual(revision_instructions(report, None), ())


if __name__ == "__main__":
    unittest.main()
