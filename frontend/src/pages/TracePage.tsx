import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, BrainCircuit, Check, ChevronDown, Clock3, CloudOff, Cpu, DatabaseZap, FileCheck2, GitCompareArrows, Layers3, MessageSquareText, RotateCcw, Route, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { TraceEvent, TraceStage } from "../types";
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
  const { runId = "run-demo-4821" } = useParams();
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.getRun(runId) });
  const totalLatency = run.data?.trace.reduce((sum, item) => sum + (item.duration_ms ?? 0), 0) ?? 0;
  const tokenUsage = run.data?.trace.reduce((sum, item) => sum + (item.token_usage ?? 0), 0) ?? 0;
  return (
    <div className="page-stack">
      <PageHeader eyebrow={`Run ${runId}`} title="A transparent answer pipeline" description="Inspect stage decisions, evidence movement, timing, and failure boundaries—without exposing private model reasoning." action={<Link className="secondary-button" to="/ask">Open conversation</Link>} />
      {run.isError && <div className="error-banner"><AlertTriangle size={18} /><strong>Trace unavailable</strong><span>The backend could not restore this run.</span></div>}
      {run.data && <>
        <section className="trace-overview">
          <div><span className="trace-query-label">Original question</span><blockquote>{run.data.query}</blockquote><div className="trace-tags"><StatusPill tone="info">{run.data.request.learner_level.replace("_", " ")}</StatusPill><StatusPill tone="neutral">{run.data.request.teaching_mode}</StatusPill><StatusPill tone="neutral">{run.data.request.context_depth} context</StatusPill></div></div>
          <div className="trace-stats"><span><Clock3 size={17} /><strong>{(totalLatency / 1000).toFixed(1)}s</strong><small>Pipeline latency</small></span><span><BrainCircuit size={17} /><strong>{tokenUsage}</strong><small>Model tokens</small></span><span><CloudOff size={17} /><strong>{run.data.trace.filter((event) => event.api_usage).length}</strong><small>External calls</small></span><span><FileCheck2 size={17} /><strong>{run.data.answer?.citations.length ?? 0}</strong><small>Sources cited</small></span></div>
        </section>
        <section className="timeline-section">
          <div className="section-heading"><div><span className="eyebrow">Structured events</span><h2>Stage-by-stage trace</h2></div><StatusPill tone="success"><Sparkles size={12} /> Pipeline completed</StatusPill></div>
          <div className="timeline">{run.data.trace.map((event, index) => <TraceRow event={event} key={event.event_id} last={index === run.data.trace.length - 1} />)}</div>
        </section>
        <section className="transparency-note"><Cpu size={20} /><div><strong>What this trace deliberately excludes</strong><p>AURA shows classifications, selected evidence, verification outcomes, and operational summaries. It does not display hidden chain-of-thought or private reasoning tokens.</p></div></section>
      </>}
    </div>
  );
}

function TraceRow({ event, last }: { event: TraceEvent; last: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const Icon = stageIcons[event.stage];
  return <article className="timeline-row"><div className="timeline-rail"><span className="timeline-icon"><Icon size={17} /></span>{!last && <i />}</div><div className="timeline-content"><button onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}><span><strong>{event.stage[0].toUpperCase() + event.stage.slice(1)}</strong><small>{event.summary}</small></span><span className="timeline-meta">{event.model && <em>{event.model}</em>}{event.duration_ms !== undefined && <b>{event.duration_ms} ms</b>}<StatusPill tone={event.status === "completed" ? "success" : event.status === "failed" ? "danger" : "warning"}>{event.status}</StatusPill>{event.details && <ChevronDown className={expanded ? "is-rotated" : ""} size={16} />}</span></button>{expanded && event.details && <pre>{JSON.stringify(event.details, null, 2)}</pre>}</div></article>;
}
