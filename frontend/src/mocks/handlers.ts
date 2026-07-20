import { delay, http, HttpResponse } from "msw";
import { capabilities, corpusStatus, demoRun, health, retrievalResults } from "../lib/mock-data";
import type { RetrievalMode, RunRequest } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export const handlers = [
  http.get(`${API_BASE}/api/v1/health`, () => HttpResponse.json(health)),
  http.get(`${API_BASE}/api/v1/capabilities`, () => HttpResponse.json(capabilities)),
  http.get(`${API_BASE}/api/v1/corpus/status`, () => HttpResponse.json(corpusStatus)),
  http.post(`${API_BASE}/api/v1/runs`, async ({ request }) => {
    await request.json() as RunRequest;
    await delay(120);
    return HttpResponse.json({ run_id: `run-${Date.now()}`, status: "queued" }, { status: 202 });
  }),
  http.get(`${API_BASE}/api/v1/runs/:runId`, ({ params }) =>
    HttpResponse.json({ ...demoRun, run_id: String(params.runId) }),
  ),
  http.post(`${API_BASE}/api/v1/retrieval/search`, async ({ request }) => {
    const body = (await request.json()) as { query: string; mode: RetrievalMode; source_type?: string };
    await delay(260);
    const results = retrievalResults(body.mode).filter(
      (item) => !body.source_type || item.source_type === body.source_type,
    );
    return HttpResponse.json({ query: body.query, mode: body.mode, latency_ms: 184, results });
  }),
  http.get(`${API_BASE}/api/v1/sessions/:sessionId`, () =>
    HttpResponse.json({ session_id: "local-demo", messages: [] }),
  ),
];

