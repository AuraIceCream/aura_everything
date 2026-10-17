import { useCallback, useEffect, useReducer, useRef } from "react";
import { api } from "../lib/api";
import { archiveRun, archiveSummary } from "../lib/trace-store";
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

export function runReducer(state: RunState, action: RunStreamEvent | { type: "reset" } | { type: "start"; runId?: string } | { type: "created"; runId: string }) : RunState {
  switch (action.type) {
    case 'reset': return initialRunState;
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
    case 'run.invalidated':
      return {...initialRunState,status:'failed',error:action.message};
  }
}

export function useRun() {
  const [state, dispatch] = useReducer(runReducer, initialRunState);
  const controller = useRef<AbortController | null>(null);
  const privatePacks = useRef<string[]>([]);
  useEffect(() => {
    const purge = (event: Event) => {
      if (privatePacks.current.includes((event as CustomEvent<string>).detail)) {
        controller.current?.abort(); dispatch({ type: 'reset' }); privatePacks.current = [];
      }
    };
    window.addEventListener('study-pack-purged', purge);
    return () => window.removeEventListener('study-pack-purged', purge);
  }, []);
  useEffect(() => () => controller.current?.abort(), []);

  const start = useCallback(async (request: RunRequest) => {
    controller.current?.abort();
    controller.current = new AbortController();
    const active = controller.current;
    privatePacks.current = [request.pack_id,request.context_pack_id].filter((id):id is string=>!!id);
    dispatch({ type: "start" });
    try {
      const created = await api.createRun(request,active.signal);
      if (active.signal.aborted) return;
      dispatch({ type: "created", runId: created.run_id });
      await api.streamRun(created.run_id, (event) => {
        if (!active.signal.aborted) dispatch(event);
        if (event.type==='run.invalidated') active.abort();
      }, active.signal);
      if (active.signal.aborted || request.evidence_scope === 'pack_only') return;
      // Mirror the finished run into this browser so its trace survives a
      // backend restart, which otherwise discards every run it holds.
      try {
        const [full, recent] = await Promise.all([
          api.getRun(created.run_id),
          api.recentRuns(1),
        ]);
        archiveRun(full);
        const summary = recent.runs.find((run) => run.run_id === created.run_id);
        if (summary) archiveSummary(summary);
      } catch {
        /* archiving is best-effort and must never fail the run */
      }
    } catch (error) {
      if (!active.signal.aborted) {
        dispatch({ type: "run.failed", error: error instanceof Error ? error.message : "Run failed" });
      }
    }
  }, []);

  return { state, start, cancel: () => {controller.current?.abort();dispatch({type:'run.failed',error:'Stopped by user; any accepted server work may finish privately.'});}, reset: () => { controller.current?.abort();privatePacks.current=[]; dispatch({ type: 'reset' }); } };
}
