import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, Clock3 } from "lucide-react";
import { Link } from "react-router-dom";
import { StatusPill } from "../components/ui";
import { api } from "../lib/api";
import { mergeRuns } from "../lib/trace-store";

/**
 * Index of runs the backend still holds, newest first.
 *
 * The sidebar used to link straight at a hardcoded sample run id, which 404s
 * against a real backend. This page lists what actually exists instead.
 */
export function TraceIndexPage() {
  const runs = useQuery({
    queryKey: ["recent-runs", "index"],
    queryFn: () => api.recentRuns(50),
    refetchInterval: 20_000,
  });

  // Server runs first, then anything this browser archived that the backend
  // has since dropped, so history survives a restart.
  const rows = mergeRuns(runs.data?.runs ?? []);

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Pipeline traces</span>
          <h1>Every run, stage by stage</h1>
          <p>
            Each run records what was routed, retrieved, generated, and verified.
            Traces are held in memory by the backend and reset when it restarts.
          </p>
        </div>
        <StatusPill tone="info">{runs.data?.total ?? 0} held</StatusPill>
      </header>

      {runs.isError && (
        <div className="error-banner">
          <AlertTriangle size={18} />
          <strong>Backend unreachable</strong>
          <span>Start the API to inspect traces.</span>
        </div>
      )}

      {!runs.isLoading && rows.length === 0 && (
        <div className="empty-state">
          <h2>No runs yet</h2>
          <p>Ask a question and its full trace will appear here.</p>
          <Link className="text-button" to="/ask">
            Go to Ask AURA <ChevronRight size={14} />
          </Link>
        </div>
      )}

      <div className="trace-index-list">
        {rows.map((run) => (
          <Link to={`/traces/${run.run_id}`} key={run.run_id} className="trace-index-row">
            <div className="trace-index-row__main">
              <strong>{run.query}</strong>
              <small>
                <Clock3 size={11} />
                {(run.latency_ms / 1000).toFixed(1)}s · {run.evidence_count} sources ·{" "}
                {(run.learner_level ?? "unknown").replace("_", " ")} ·{" "}
                {(run.teaching_mode ?? "guided").replace("_", "-")}
                {run.revised ? " · revised" : ""}
                {run.archived ? " · from this browser" : ""}
              </small>
            </div>
            <StatusPill
              tone={
                run.decision === "accept"
                  ? "success"
                  : run.decision === "revise"
                    ? "warning"
                    : "danger"
              }
            >
              {run.decision}
            </StatusPill>
            <ChevronRight size={16} />
          </Link>
        ))}
      </div>
    </div>
  );
}
