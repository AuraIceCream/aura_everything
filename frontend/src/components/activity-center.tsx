import { useQuery } from "@tanstack/react-query";
import { Activity, ChevronRight, Cloud, FlaskConical } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";

/**
 * Recent activity, read from the backend.
 *
 * This panel previously rendered bundled sample runs and a simulated
 * progress feed. It now shows what the system has actually answered in this
 * session, so an empty panel truthfully means "nothing has been asked yet"
 * rather than showing invented activity.
 */
export function ActivityCenter() {
  const runs = useQuery({
    queryKey: ["recent-runs"],
    queryFn: () => api.recentRuns(8),
    refetchInterval: 15_000,
  });

  const recent = runs.data?.runs ?? [];
  const revised = recent.filter((run) => run.revised).length;

  return (
    <details className="activity-center">
      <summary aria-label="Open recent runs">
        <Activity size={15} />
        <span>Recent activity</span>
        <i>{recent.length}</i>
      </summary>
      <div className="activity-popover">
        <header>
          <div>
            <span className="eyebrow">This session</span>
            <h2>Pipeline runs</h2>
          </div>
          <span className="simulation-badge">{runs.data?.total ?? 0} total</span>
        </header>

        <section className="activity-section">
          <div className="activity-heading">
            <span>Recent runs</span>
            <small>{revised} revised</small>
          </div>
          <div className="recent-runs">
            {runs.isLoading && <p className="activity-empty">Loading…</p>}
            {runs.isError && (
              <p className="activity-empty">Backend unreachable.</p>
            )}
            {!runs.isLoading && !runs.isError && recent.length === 0 && (
              <p className="activity-empty">
                No runs yet. Ask a question to populate this.
              </p>
            )}
            {recent.map((run) => (
              <Link to={`/traces/${run.run_id}`} key={run.run_id}>
                <span className="run-icon">
                  <FlaskConical size={15} />
                </span>
                <span className="run-copy">
                  <strong>{run.query}</strong>
                  <small>
                    {(run.teaching_mode ?? "guided").replace("_", "-")} ·{" "}
                    {(run.latency_ms / 1000).toFixed(1)}s ·{" "}
                    {run.external_critic_used ? "GLM reviewed" : "on-device review"}
                    {run.revised ? " · revised" : ""}
                  </small>
                </span>
                <ChevronRight size={15} />
              </Link>
            ))}
          </div>
        </section>

        <footer>
          <Cloud size={14} />
          <span>Live data from the local backend</span>
        </footer>
      </div>
    </details>
  );
}
