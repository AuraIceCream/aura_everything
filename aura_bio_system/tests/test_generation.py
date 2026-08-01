from __future__ import annotations

import unittest
from dataclasses import dataclass

from aura_bio.generation import build_prompt, format_evidence
from aura_bio.routing import QueryRouter, TeachingMode


@dataclass
class FakeEvidence:
    chunk_id: str
    text: str
    title: str = "DNA replication"
    section: str | None = "Mechanism"
    source_id: str = "wikipedia_biology"


class PromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = QueryRouter()
        self.evidence = [
            FakeEvidence("c1", "Helicase unwinds the double helix."),
            FakeEvidence("c2", "Primase lays down an RNA primer.", section="Priming"),
        ]

    def test_evidence_is_numbered_for_citation(self) -> None:
        formatted = format_evidence(self.evidence)
        self.assertIn("[1]", formatted)
        self.assertIn("[2]", formatted)
        self.assertIn("Helicase unwinds", formatted)

    def test_teaching_mode_changes_structure(self) -> None:
        direct = build_prompt(
            self.router.route("Just tell me what a ribosome is"), self.evidence
        )
        guided = build_prompt(
            self.router.route("Explain how DNA replication occurs for class 12"), self.evidence
        )
        self.assertNotEqual(direct.user, guided.user)
        self.assertIn("Prerequisite", guided.user)
        self.assertIn("concise, direct", direct.user)

    def test_learner_level_guidance_is_present(self) -> None:
        prompt = build_prompt(
            self.router.route("Explain osmosis", learner_level="elementary"), self.evidence
        )
        self.assertIn("everyday words", prompt.user)

    def test_revision_instructions_are_included(self) -> None:
        prompt = build_prompt(
            self.router.route("Explain mitosis"),
            self.evidence,
            instructions=("Fix the step order: anaphase precedes metaphase",),
        )
        self.assertIn("Revise the previous answer", prompt.user)
        self.assertIn("anaphase precedes metaphase", prompt.user)

    def test_no_retrieval_query_states_no_sources(self) -> None:
        prompt = build_prompt(self.router.route("hello"), [])
        self.assertIn("no sources were retrieved", prompt.user)

    def test_messages_shape(self) -> None:
        prompt = build_prompt(self.router.route("Define osmosis"), self.evidence)
        messages = prompt.as_messages()
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("AURA-Bio", messages[0]["content"])


class OffloadFallbackTests(unittest.TestCase):
    """Full GPU offload must degrade rather than lose the question.

    Asking for every layer on the GPU overrides Ollama's own fitting logic, so
    when the card cannot hold the model it aborts instead of sizing down and
    the request fails with a bare HTTP 500. Retrying the identical request
    cannot help; six of six smoke questions were lost this way with 48 MiB of
    VRAM free.
    """

    def setUp(self) -> None:
        import json as _json
        import urllib.request

        from aura_bio.api.generation import OllamaGenerator

        self.sent: list[dict] = []
        self.router = QueryRouter()
        self.generator = OllamaGenerator(model="test:v0", retries=2, timeout=1)
        self._real_urlopen = urllib.request.urlopen
        self._json = _json
        self._urllib = urllib.request

        outer = self

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return outer._json.dumps({"message": {"content": "an answer"}}).encode()

        def fake_urlopen(request, timeout=None):
            options = outer._json.loads(request.data)["options"]
            outer.sent.append(options)
            if "num_gpu" in options:
                raise RuntimeError("HTTP Error 500: Internal Server Error")
            return Response()

        urllib.request.urlopen = fake_urlopen
        # The real loop sleeps between attempts; that is correct in production
        # and pointless here.
        import aura_bio.api.generation as module

        self._real_sleep = module.time.sleep
        module.time.sleep = lambda _s: None
        self._module = module

    def tearDown(self) -> None:
        self._urllib.urlopen = self._real_urlopen
        self._module.time.sleep = self._real_sleep

    def test_final_attempt_drops_num_gpu_and_succeeds(self) -> None:
        answer = self.generator.generate(self.router.route("Define osmosis"), [], ())
        self.assertEqual(answer, "an answer")
        self.assertEqual(len(self.sent), 3)
        # The first attempts ask for full offload; only the last gives it up.
        self.assertEqual([("num_gpu" in o) for o in self.sent], [True, True, False])

    def test_a_degraded_answer_is_counted(self) -> None:
        self.assertEqual(self.generator.degraded_calls, 0)
        self.generator.generate(self.router.route("Define osmosis"), [], ())
        self.assertEqual(self.generator.degraded_calls, 1)

    def test_a_normal_answer_is_not_counted_as_degraded(self) -> None:
        self._urllib.urlopen = self._real_urlopen

        class Response:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

            def read(self_inner):
                return b'{"message": {"content": "fine"}}'

        self._urllib.urlopen = lambda request, timeout=None: Response()
        answer = self.generator.generate(self.router.route("Define osmosis"), [], ())
        self.assertEqual(answer, "fine")
        self.assertEqual(self.generator.degraded_calls, 0)


if __name__ == "__main__":
    unittest.main()
