from __future__ import annotations

import json
import os
import tempfile
import unittest


def _client(env: dict[str, str] | None = None):
    """A TestClient with the runtime pointed at an empty index dir.

    No FAISS index or model is present, so this exercises the graceful-
    degradation path: routing, verification, and extractive generation.
    """

    try:
        from fastapi.testclient import TestClient
    except Exception as exc:  # pragma: no cover - dependency optional in some envs
        raise unittest.SkipTest(f"fastapi/httpx not available: {exc}")

    from aura_bio.api import state
    from aura_bio.api.app import app

    state.reset_runtime()
    tmp = tempfile.mkdtemp()
    os.environ["AURA_INDEX_ROOT"] = tmp
    os.environ["AURA_TRACE_DB"] = os.path.join(tmp, "traces.sqlite3")
    # Force the no-model, no-critic path so the contract tests never depend on
    # a running Ollama server or an external API key.
    os.environ["AURA_GENERATOR"] = "extractive"
    os.environ["AURA_CRITIC"] = "off"
    for key, value in (env or {}).items():
        os.environ[key] = value
    return TestClient(app)


class ApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = _client()

    def tearDown(self) -> None:
        from aura_bio.api import state

        state.reset_runtime()

    def test_health_reports_offline_without_an_index(self) -> None:
        body = self.client.get("/api/v1/health").json()
        self.assertEqual(body["status"], "offline")
        self.assertTrue(body["backend"])
        self.assertFalse(body["index_ready"])

    def test_capabilities_lists_frontend_enums(self) -> None:
        body = self.client.get("/api/v1/capabilities").json()
        self.assertIn("guided", body["teaching_modes"])
        self.assertIn("hybrid", body["retrieval_modes"])
        self.assertGreaterEqual(body["benchmark_questions"], 400)

    def test_corpus_status_reports_real_totals(self) -> None:
        body = self.client.get("/api/v1/corpus/status").json()
        self.assertEqual(body["totals"]["sources"], 9)
        self.assertGreater(body["totals"]["chunks"], 10_000_000)
        self.assertIn("sources", body)

    def test_run_executes_pipeline_and_is_retrievable(self) -> None:
        create = self.client.post(
            "/api/v1/runs",
            json={"query": "Explain how DNA replication occurs", "learner_level": "high_school",
                  "teaching_mode": "guided", "response_length": "balanced",
                  "context_depth": "standard", "source_types": [], "allow_external_critic": False},
        )
        self.assertEqual(create.status_code, 202)
        run_id = create.json()["run_id"]
        run = self.client.get(f"/api/v1/runs/{run_id}").json()
        self.assertEqual(run["query"], "Explain how DNA replication occurs")
        self.assertIn("answer", run)
        self.assertIn("trace", run)
        # routing always runs; a real trace has a routing stage
        stages = {event["stage"] for event in run["trace"]}
        self.assertIn("routing", stages)
        self.assertIn("complete", stages)

    def test_run_answer_reflects_routing(self) -> None:
        run_id = self.client.post(
            "/api/v1/runs",
            json={"query": "Define osmosis", "learner_level": "undergraduate",
                  "teaching_mode": "direct", "response_length": "concise",
                  "context_depth": "none", "source_types": [], "allow_external_critic": False},
        ).json()["run_id"]
        run = self.client.get(f"/api/v1/runs/{run_id}").json()
        self.assertIn(run["answer"]["verification_status"],
                      {"verified", "partial", "unsupported", "pending"})
        self.assertIn(run["answer"]["confidence"], {"high", "medium", "low"})

    def test_missing_run_is_404(self) -> None:
        self.assertEqual(self.client.get("/api/v1/runs/does-not-exist").status_code, 404)

    def test_events_stream_replays_trace_and_answer(self) -> None:
        run_id = self.client.post(
            "/api/v1/runs",
            json={"query": "What are the stages of mitosis?", "learner_level": "high_school",
                  "teaching_mode": "guided", "response_length": "balanced",
                  "context_depth": "standard", "source_types": [], "allow_external_critic": False},
        ).json()["run_id"]
        with self.client.stream("GET", f"/api/v1/runs/{run_id}/events") as response:
            self.assertEqual(response.status_code, 200)
            types = []
            for line in response.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                event = json.loads(line[len("data: "):])
                types.append(event["type"])
        self.assertIn("trace", types)
        self.assertIn("answer.delta", types)
        self.assertEqual(types[-1], "answer.completed")

    def test_retrieval_search_returns_503_without_index(self) -> None:
        response = self.client.post(
            "/api/v1/retrieval/search", json={"query": "photosynthesis", "mode": "hybrid"}
        )
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
