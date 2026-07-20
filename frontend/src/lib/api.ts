import type {
  Capabilities,
  CorpusStatus,
  HealthStatus,
  RetrievalMode,
  RetrievalResponse,
  Run,
  RunRequest,
  RunStreamEvent,
} from "../types";
import { streamDemoRun } from "./mock-data";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS !== "false";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthStatus>("/api/v1/health"),
  capabilities: () => request<Capabilities>("/api/v1/capabilities"),
  corpusStatus: () => request<CorpusStatus>("/api/v1/corpus/status"),
  createRun: (payload: RunRequest) =>
    request<{ run_id: string; status: string }>("/api/v1/runs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getRun: (runId: string) => request<Run>(`/api/v1/runs/${encodeURIComponent(runId)}`),
  retrievalSearch: (query: string, mode: RetrievalMode, sourceType?: string) =>
    request<RetrievalResponse>("/api/v1/retrieval/search", {
      method: "POST",
      body: JSON.stringify({ query, mode, source_type: sourceType || null }),
    }),
  streamRun: (
    runId: string,
    onEvent: (event: RunStreamEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> => {
    if (USE_MOCKS) return streamDemoRun(onEvent, signal);
    return new Promise((resolve, reject) => {
      const source = new EventSource(`${API_BASE}/api/v1/runs/${encodeURIComponent(runId)}/events`);
      const abort = () => {
        source.close();
        resolve();
      };
      signal?.addEventListener("abort", abort, { once: true });
      source.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as RunStreamEvent;
          onEvent(event);
          if (event.type === "answer.completed" || event.type === "run.failed") {
            source.close();
            signal?.removeEventListener("abort", abort);
            resolve();
          }
        } catch (error) {
          source.close();
          reject(error);
        }
      };
      source.onerror = () => {
        if (source.readyState === EventSource.CLOSED) reject(new Error("Run stream disconnected"));
      };
    });
  },
};

