import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle, Archive, BrainCircuit, Check, ChevronDown, Clock3, CloudOff, Cpu,
  DatabaseZap, FileCheck2, GitCompareArrows, Layers3, MessageSquareText, RotateCcw,
  Route, ShieldCheck, Sparkles,
} from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { archivedRun } from "../lib/trace-store";
import type { Run, TraceEvent, TraceStage } from "../types";
import { PageHeader, StatusPill } from "../components/ui";

const stageIcons: Record<TraceStage, typeof Route> = {
  routing: Route,
  retrieval: DatabaseZap,
  evidence: Layers3,
  generation: MessageSquareText,
  verification: ShieldCheck,
  critique: GitCompareArrows,
  revision: RotateCcw,
  complete: Check,
};

export function TracePage() {
  const { runId = "" } = useParams();
  const run = useQuery({
    queryKey: ["run", runId],
    // The backend holds runs in memory, so a restart loses them. Fall back to
    // this browser's archive rather than showing a dead end.
    queryFn: async (): Promise<Run & { fromArchive?: boolean }> => {
      try {
        return await api.getRun(runId);
      } catch (error) {
        const archived = archivedRun(runId);
        if (archived) return { ...archived, fromArchive: true };
        throw error;
      }
    },
    enabled: Boolean(runId),
    retry: false,
  });

  const events = run.data?.trace ?? [];
  const totalLatency = events.reduce((sum, item) => sum + (item.duration_ms ?? 0), 0);
  const tokenUsage = events.reduce((sum, item) => sum + (item.token_usage ?? 0), 0);

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow={`Run ${runId}`}
        title="A transparent answer pipeline"
        description="Inspect stage decisions, evidence movement, timing, and failure boundaries, without exposing private model reasoning."
        action={<Link className="secondary-button" to="/traces">All traces</Link>}
      />

      {run.isError && (
        <div className="error-banner">
          <AlertTriangle size={18} />
          <strong>Trace unavailable</strong>
          <span>Neither the backend nor this browser holds this run.</span>
        </div>
      )}

      {run.data?.fromArchive && (
        <div className="info-banner">
          <Archive size={17} />
          <span>
            Restored from this browser. The backend no longer holds this run,
            most likely because it restarted.
          </span>
        </div>
      )}

      {run.data && <>
        <section className="trace-overview">
          <div>
            <span className="trace-query-label">Original question</span>
            <blockquote>{run.data.query}</blockquote>
            <div className="trace-tags">
              <StatusPill tone="info">{run.data.request.learner_level.replace("_", " ")}</StatusPill>
              <StatusPill tone="neutral">{run.data.request.teaching_mode}</StatusPill>
              <StatusPill tone="neutral">{run.data.request.context_depth} context</StatusPill>
            </div>
          </div>
          <div className="trace-stats">
            <span><Clock3 size={17} /><strong>{(totalLatency / 1000).toFixed(1)}s</strong><small>Pipeline latency</small></span>
            <span><BrainCircuit size={17} /><strong>{tokenUsage}</strong><small>Model tokens</small></span>
            <span><CloudOff size={17} /><strong>{events.filter((event) => event.api_usage).length}</strong><small>External calls</small></span>
            <span><FileCheck2 size={17} /><strong>{run.data.answer?.citations.length ?? 0}</strong><small>Sources cited</small></span>
          </div>
        </section>

        <section className="timeline-section">
          <div className="section-heading">
            <div><span className="eyebrow">Structured events</span><h2>Stage-by-stage trace</h2></div>
            <StatusPill tone="success"><Sparkles size={12} /> Pipeline completed</StatusPill>
          </div>
          <div className="timeline">
            {events.map((event, index) => (
              <TraceRow event={event} key={event.event_id} last={index === events.length - 1} />
            ))}
          </div>
        </section>

        <section className="transparency-note">
          <Cpu size={20} />
          <div>
            <strong>What this trace deliberately excludes</strong>
            <p>AURA shows classifications, selected evidence, verification outcomes, and operational summaries. It does not display hidden chain-of-thought or private reasoning tokens.</p>
          </div>
        </section>
      </>}
    </div>
  );
}

function TraceRow({ event, last }: { event: TraceEvent; last: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const Icon = stageIcons[event.stage];
  return (
    <article className="timeline-row">
      <div className="timeline-rail">
        <span className="timeline-icon"><Icon size={17} /></span>
        {!last && <i />}
      </div>
      <div className="timeline-content">
        <button onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
          <span><strong>{event.stage[0].toUpperCase() + event.stage.slice(1)}</strong><small>{event.summary}</small></span>
          <span className="timeline-meta">
            {event.model && <em>{event.model}</em>}
            {event.duration_ms !== undefined && <b>{formatMs(event.duration_ms)}</b>}
            <StatusPill tone={event.status === "completed" ? "success" : event.status === "failed" ? "danger" : "warning"}>
              {event.status}
            </StatusPill>
            {event.details && <ChevronDown className={expanded ? "is-rotated" : ""} size={16} />}
          </span>
        </button>
        {expanded && event.details && <StageDetail stage={event.stage} details={event.details} />}
      </div>
    </article>
  );
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

/* -- per-stage detail ------------------------------------------------------
   Each stage gets a reading of its own decisions rather than a JSON dump:
   the point of the trace page is that a person can audit the answer. */

type Detail = Record<string, unknown>;

const asRecord = (value: unknown): Detail | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Detail) : null;
const asArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const asNumber = (value: unknown): number | null => (typeof value === "number" ? value : null);

function StageDetail({ stage, details }: { stage: TraceStage; details: Detail }) {
  if (stage === "routing") return <RoutingDetail details={details} />;
  if (stage === "retrieval") return <RetrievalDetail details={details} />;
  if (stage === "evidence") return <EvidenceDetail details={details} />;
  if (stage === "verification") return <VerificationDetail details={details} />;
  return <pre>{JSON.stringify(details, null, 2)}</pre>;
}

function RoutingDetail({ details }: { details: Detail }) {
  const dimensions = ["task_type", "subdomain", "learner_level", "teaching_mode"] as const;
  return (
    <div className="stage-detail">
      <div className="detail-cards">
        {dimensions.map((name) => {
          const entry = asRecord(details[name]);
          if (!entry) return null;
          const confidence = asNumber(entry.confidence);
          const decidedBy = String(entry.decided_by ?? "");
          return (
            <div className="detail-card" key={name}>
              <span className="detail-card__label">{name.replace(/_/g, " ")}</span>
              <strong>{String(entry.label ?? "—").replace(/_/g, " ")}</strong>
              <small>
                {/* "llm" is the trained encoder classifier; "rules" is the
                    hand-written pattern table. Worth distinguishing. */}
                {decidedBy === "llm" ? "learned classifier" : decidedBy || "—"}
                {confidence !== null ? ` · ${confidence.toFixed(2)}` : ""}
              </small>
            </div>
          );
        })}
      </div>
      <dl className="detail-facts">
        <div><dt>Context level</dt><dd>{String(details.context_level ?? "—")}</dd></div>
        <div><dt>Retrieve</dt><dd>{String(details.retrieve_k ?? "—")} candidates</dd></div>
        <div><dt>Rerank to</dt><dd>{String(details.rerank_k ?? "—")}</dd></div>
        <div><dt>Revisions allowed</dt><dd>{String(details.max_revisions ?? "—")}</dd></div>
      </dl>
      {asArray(details.explicit_overrides).length > 0 && (
        <p className="detail-note">
          User-set: {asArray(details.explicit_overrides).map(String).join(", ")}
        </p>
      )}
    </div>
  );
}

function RetrievalDetail({ details }: { details: Detail }) {
  const channels = asRecord(details.channels);
  return (
    <div className="stage-detail">
      <dl className="detail-facts">
        <div><dt>Strategy</dt><dd>{String(details.strategy ?? "hybrid")}</dd></div>
        <div><dt>Candidates</dt><dd>{String(details.candidates ?? "—")}</dd></div>
      </dl>
      {channels && (
        <ul className="detail-chips">
          {Object.entries(channels).map(([name, value]) => (
            <li key={name}>
              <span>{name.replace(/_/g, " ")}</span>
              <b>{typeof value === "object" ? JSON.stringify(value) : String(value)}</b>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function EvidenceDetail({ details }: { details: Detail }) {
  const passages = asArray(details.passages);
  return (
    <div className="stage-detail">
      <p className="detail-note">{String(details.selected ?? passages.length)} passages kept for grounding.</p>
      <ol className="detail-passages">
        {passages.map((raw, index) => {
          const passage = asRecord(raw);
          if (!passage) return null;
          return (
            <li key={index}>
              <strong>{String(passage.title ?? "Untitled")}</strong>
              <small>{String(passage.source_id ?? "")} · {String(passage.chunk_id ?? "")}</small>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

const supportTone: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  supported: "success",
  partially_supported: "warning",
  unsupported: "warning",
  contradictory: "danger",
  unverifiable: "neutral",
};

function VerificationDetail({ details }: { details: Detail }) {
  const support = asRecord(details.claim_support) ?? {};
  const checkers = asRecord(details.checkers_fired) ?? {};
  const issues = asArray(details.issues);
  const claims = asArray(details.claims);
  const grounded = asNumber(details.grounded_fraction);
  const [showClaims, setShowClaims] = useState(false);

  return (
    <div className="stage-detail">
      <dl className="detail-facts">
        <div><dt>Decision</dt><dd>{String(details.decision ?? "—")}</dd></div>
        <div><dt>Claims checked</dt><dd>{String(details.claims_checked ?? claims.length)}</dd></div>
        <div><dt>Grounded</dt><dd>{grounded !== null ? `${(grounded * 100).toFixed(0)}%` : "—"}</dd></div>
        <div><dt>Unsupported</dt><dd>{String(details.unsupported_claims ?? 0)}</dd></div>
      </dl>

      <div className="detail-block">
        <h4>Entailment labels</h4>
        <div className="detail-pills">
          {Object.entries(support).map(([label, count]) => (
            <StatusPill key={label} tone={supportTone[label] ?? "neutral"}>
              {label.replace(/_/g, " ")} · {String(count)}
            </StatusPill>
          ))}
          {!Object.keys(support).length && <small>No claim labels recorded.</small>}
        </div>
      </div>

      <div className="detail-block">
        <h4>Checkers that fired</h4>
        <ul className="detail-chips">
          {Object.entries(checkers).map(([name, count]) => (
            <li key={name}><span>{name.replace(/_/g, " ")}</span><b>{String(count)}</b></li>
          ))}
          {!Object.keys(checkers).length && <small>No checker raised anything.</small>}
        </ul>
      </div>

      {issues.length > 0 && (
        <div className="detail-block">
          <h4>Issues</h4>
          <ul className="detail-issues">
            {issues.map((raw, index) => {
              const issue = asRecord(raw);
              if (!issue) return null;
              return (
                <li key={index} className={`severity-${String(issue.severity)}`}>
                  <strong>{String(issue.checker)} · {String(issue.kind).replace(/_/g, " ")}</strong>
                  <span>{String(issue.detail ?? "")}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {claims.length > 0 && (
        <div className="detail-block">
          <button className="text-button" onClick={() => setShowClaims((value) => !value)}>
            {showClaims ? "Hide" : "Show"} all {claims.length} claims
          </button>
          {showClaims && (
            <ul className="detail-claims">
              {claims.map((raw, index) => {
                const claim = asRecord(raw);
                if (!claim) return null;
                const label = String(claim.support ?? "");
                return (
                  <li key={index}>
                    <StatusPill tone={supportTone[label] ?? "neutral"}>{label.replace(/_/g, " ")}</StatusPill>
                    {claim.verification_kind!=null && <small>{String(claim.verification_kind).replace(/_/g,' ')} · inputs {claim.inputs_verified?'independently checked':'unverified'}</small>}
                    <p>{String(claim.text ?? "")}</p>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
