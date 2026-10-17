import { AlertTriangle, CircleCheck, Quote, RotateCcw, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import type { RecentRun } from "../types";
import { StatusPill } from "./ui";

/**
 * Teaching-quality and failure-review panels.
 *
 * Both read the pipeline's own traces through `GET /api/v1/runs`, so every
 * figure describes work the system actually did in this session. They are
 * empty until something has been asked, which is the honest state.
 */

function mean(values: number[]): number {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
}

function pct(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
}

export function TeachingQualityPanel({ runs }: { runs: RecentRun[] }) {
  const answered = runs.filter((run) => run.status === "completed");

  if (!answered.length) {
    return (
      <section className="panel">
        <header className="panel-header">
          <div>
            <span className="eyebrow">Teaching quality</span>
            <h2>Answer characteristics</h2>
          </div>
        </header>
        <p className="activity-empty">
          No runs yet. Ask a question and its measured quality appears here.
        </p>
      </section>
    );
  }

  const citationRate = mean(
    answered.map((run) => run.provenance?.claim_citation_rate ?? 0),
  );
  const citationValidity = mean(
    answered.map((run) => run.provenance?.citation_validity ?? 0),
  );
  const unsupported = mean(
    answered.map((run) => run.provenance?.unsupported_assertion_rate ?? 0),
  );
  const confidence = mean(answered.map((run) => run.confidence));
  const evidence = mean(answered.map((run) => run.evidence_count));
  const revised = answered.filter((run) => run.revised).length;

  // Which register each answer was actually pitched at. Learner level selects
  // the prompt's guidance, so this is the clearest evidence that adaptive
  // teaching is doing something rather than being nominally configured.
  const levels = new Map<string, number>();
  const modes = new Map<string, number>();
  for (const run of answered) {
    const level = run.learner_level ?? "unknown";
    const mode = run.teaching_mode ?? "unknown";
    levels.set(level, (levels.get(level) ?? 0) + 1);
    modes.set(mode, (modes.get(mode) ?? 0) + 1);
  }

  return (
    <section className="panel">
      <header className="panel-header">
        <div>
          <span className="eyebrow">Teaching quality</span>
          <h2>Answer characteristics</h2>
        </div>
        <StatusPill tone="info">{answered.length} runs</StatusPill>
      </header>

      <div className="quality-grid">
        <article className="quality-tile">
          <span className="quality-icon"><Quote size={16} /></span>
          <strong>{pct(citationRate)}</strong>
          <small>Claims carrying a citation</small>
        </article>
        <article className="quality-tile">
          <span className="quality-icon"><ShieldCheck size={16} /></span>
          <strong>{pct(citationValidity)}</strong>
          <small>Valid citation references · not independent truth verification</small>
        </article>
        <article className="quality-tile">
          <span className="quality-icon"><AlertTriangle size={16} /></span>
          <strong>{pct(unsupported)}</strong>
          <small>Claims with no citation</small>
        </article>
        <article className="quality-tile">
          <span className="quality-icon"><CircleCheck size={16} /></span>
          <strong>{confidence.toFixed(2)}</strong>
          <small>Mean verifier confidence</small>
        </article>
        <article className="quality-tile">
          <span className="quality-icon"><RotateCcw size={16} /></span>
          <strong>{revised}</strong>
          <small>Answers revised after verification</small>
        </article>
        <article className="quality-tile">
          <span className="quality-icon"><Quote size={16} /></span>
          <strong>{evidence.toFixed(1)}</strong>
          <small>Mean passages cited per answer</small>
        </article>
      </div>

      <div className="quality-split">
        <div>
          <h3>Level adapted to</h3>
          <ul className="quality-bars">
            {[...levels.entries()].sort((a, b) => b[1] - a[1]).map(([level, count]) => (
              <li key={level}>
                <span>{level.replace(/_/g, " ")}</span>
                <i style={{ width: `${(count / answered.length) * 100}%` }} />
                <b>{count}</b>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Teaching style used</h3>
          <ul className="quality-bars">
            {[...modes.entries()].sort((a, b) => b[1] - a[1]).map(([mode, count]) => (
              <li key={mode}>
                <span>{mode.replace(/_/g, " ")}</span>
                <i style={{ width: `${(count / answered.length) * 100}%` }} />
                <b>{count}</b>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

export function FailureReviewPanel({ runs }: { runs: RecentRun[] }) {
  // Anything the pipeline did not simply accept is worth a look: a revision, a
  // refusal to answer from the available evidence, or a hard failure.
  const flagged = runs.filter(
    (run) => run.status !== "completed" || run.decision !== "accept" || run.revised,
  );

  const categories = new Map<string, number>();
  for (const run of flagged) {
    const key = run.failure_category ?? (run.revised ? "revised" : run.decision);
    categories.set(key, (categories.get(key) ?? 0) + 1);
  }

  return (
    <section className="panel">
      <header className="panel-header">
        <div>
          <span className="eyebrow">Failure review</span>
          <h2>Runs worth inspecting</h2>
        </div>
        <StatusPill tone={flagged.length ? "warning" : "success"}>
          {flagged.length} of {runs.length}
        </StatusPill>
      </header>

      {!runs.length && (
        <p className="activity-empty">No runs yet.</p>
      )}
      {runs.length > 0 && !flagged.length && (
        <p className="activity-empty">
          Every run so far was accepted without revision.
        </p>
      )}

      {flagged.length > 0 && (
        <>
          <div className="failure-categories">
            {[...categories.entries()].sort((a, b) => b[1] - a[1]).map(([name, count]) => (
              <span key={name} className="failure-chip">
                {name.replace(/_/g, " ")} <b>{count}</b>
              </span>
            ))}
          </div>
          <div className="failure-list">
            {flagged.map((run) => (
              <Link to={`/traces/${run.run_id}`} key={run.run_id} className="failure-row">
                <div>
                  <strong>{run.query}</strong>
                  <small>
                    {run.decision}
                    {run.revised ? ` · ${run.passes} passes` : ""}
                    {run.failure_category ? ` · ${run.failure_category.replace(/_/g, " ")}` : ""}
                    {" · "}
                    {(run.latency_ms / 1000).toFixed(1)}s
                  </small>
                </div>
                <StatusPill tone={run.status === "completed" ? "warning" : "danger"}>
                  {run.status === "completed" ? "review" : "failed"}
                </StatusPill>
              </Link>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
