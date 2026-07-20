import { useCallback, useEffect, useReducer, useRef } from "react";
import { api } from "../lib/api";
import type { Answer, RunRequest, RunStreamEvent, TraceEvent } from "../types";

interface RunState {
  runId?: string;
  status: "idle" | "submitting" | "streaming" | "complete" | "failed";
  markdown: string;
  answer?: Answer;
  trace: TraceEvent[];
  error?: string;
}

export const initialRunState: RunState = { status: "idle", markdown: "", trace: [] };

export function runReducer(state: RunState, action: RunStreamEvent | { type: "start"; runId?: string } | { type: "created"; runId: string }) : RunState {
  switch (action.type) {
    case "start":
      return { ...initialRunState, status: "submitting", runId: action.runId };
    case "created":
      return { ...state, runId: action.runId, status: "streaming" };
    case "trace":
      return { ...state, trace: [...state.trace.filter((item) => item.event_id !== action.event.event_id), action.event] };
    case "answer.delta":
      return { ...state, status: "streaming", markdown: state.markdown + action.delta };
    case "answer.completed":
      return { ...state, status: "complete", markdown: action.answer.markdown, answer: action.answer };
    case "run.failed":
      return { ...state, status: "failed", error: action.error };
  }
}

export function useRun() {
  const [state, dispatch] = useReducer(runReducer, initialRunState);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  const start = useCallback(async (request: RunRequest) => {
    controller.current?.abort();
    controller.current = new AbortController();
    dispatch({ type: "start" });
    try {
      const created = await api.createRun(request);
      dispatch({ type: "created", runId: created.run_id });
      await api.streamRun(created.run_id, dispatch, controller.current.signal);
    } catch (error) {
      if (!controller.current.signal.aborted) {
        dispatch({ type: "run.failed", error: error instanceof Error ? error.message : "Run failed" });
      }
    }
  }, []);

  return { state, start, cancel: () => controller.current?.abort() };
}

