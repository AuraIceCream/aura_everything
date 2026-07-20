import { Activity, ArrowUp, BookOpenCheck, BrainCircuit, ChevronRight, CircleStop, Clock3, FlaskConical, Layers3, Library, LockKeyhole, Sparkles, Workflow } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AnswerView, CitationDrawer, StatusPill } from "../components/ui";
import { useSettings } from "../context/settings";
import { useRun } from "../hooks/use-run";
import { demoProcesses, demoRuns } from "../lib/mock-data";
import type { Citation, RunRequest, TeachingMode } from "../types";

const prompts = [
  { icon: BrainCircuit, title: "Explain a mechanism", prompt: "How does the electron transport chain create ATP?" },
  { icon: FlaskConical, title: "Compare processes", prompt: "Compare mitosis and meiosis at an undergraduate level." },
  { icon: BookOpenCheck, title: "Prepare for an exam", prompt: "Give me an exam-ready explanation of operon regulation." },
];

const teachingModes: { value: TeachingMode; label: string }[] = [
  { value: "direct", label: "Direct answer" },
  { value: "guided", label: "Guided explanation" },
  { value: "socratic", label: "Socratic" },
  { value: "exam", label: "Exam mode" },
  { value: "revision", label: "Revision notes" },
  { value: "research", label: "Research mode" },
  { value: "teach_back", label: "Teach-back" },
];

export function AskPage() {
  const { settings, update } = useSettings();
  const { state, start, cancel } = useRun();
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedCitation, setSelectedCitation] = useState<string>();
  const isRunning = state.status === "submitting" || state.status === "streaming";
  const citations = state.answer?.citations ?? [];

  const activeStage = useMemo(() => [...state.trace].reverse().find((item) => item.status === "completed")?.stage, [state.trace]);

  function openCitation(id?: string) {
    setSelectedCitation(id);
    setDrawerOpen(true);
  }

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || isRunning) return;
    const request: RunRequest = {
      query: trimmed,
      learner_level: settings.learnerLevel,
      teaching_mode: settings.teachingMode,
      response_length: settings.responseLength,
      context_depth: settings.contextDepth,
      source_types: [],
      allow_external_critic: settings.externalCritic,
    };
    setSubmittedQuery(trimmed);
    setQuery("");
    void start(request);
  }

  return (
    <div className="ask-page">
      <section className="ask-hero">
        <div className="ask-hero__copy">
          <span className="eyebrow"><Sparkles size={14} /> Adaptive biology tutor</span>
          <h1>Understand biology.<br /><em>Inspect the evidence.</em></h1>
          <p>Ask at your level, choose how you want to learn, and see exactly which sources support the answer.</p>
        </div>
        <div className="trust-strip">
          <span><LockKeyhole size={15} /> Private by default</span>
          <span><Library size={15} /> Curated corpus</span>
          <span><Layers3 size={15} /> Hybrid retrieval</span>
        </div>
      </section>

      {!submittedQuery && <WorkspaceSnapshot />}

      {submittedQuery && (
        <section className="conversation" aria-label="Current conversation">
          <div className="user-message"><span>You</span><p>{submittedQuery}</p></div>
          {isRunning && (
            <div className="run-progress" role="status">
              <span className="orbit-loader" />
              <div><strong>{activeStage ? `${activeStage[0].toUpperCase()}${activeStage.slice(1)} complete` : "Starting answer pipeline"}</strong><span>{state.status === "submitting" ? "Creating a traceable run…" : "Grounding the response in selected evidence…"}</span></div>
              <Link to={`/traces/${state.runId ?? "run-demo-4821"}`}>View trace <ChevronRight size={14} /></Link>
            </div>
          )}
          {(state.markdown || state.answer) && <AnswerView answer={state.answer} markdown={state.markdown} onCitation={openCitation} />}
          {state.answer && (
            <div className="source-summary">
              <div><span className="eyebrow">Evidence set</span><strong>{citations.length} sources support this response</strong></div>
              <div className="source-chips">
                {citations.map((citation) => <button key={citation.citation_id} onClick={() => openCitation(citation.citation_id)}><span>{citation.rank}</span>{citation.source_title}</button>)}
              </div>
              <button className="text-button" onClick={() => openCitation()}>Inspect all evidence <ChevronRight size={14} /></button>
            </div>
          )}
          {state.status === "failed" && <div className="error-banner"><strong>The run stopped safely.</strong><span>{state.error}. Your question remains in this browser session; retry when the backend is available.</span></div>}
        </section>
      )}

      {!submittedQuery && (
        <section className="prompt-grid" aria-label="Example questions">
          {prompts.map(({ icon: Icon, title, prompt }) => (
            <button key={title} onClick={() => setQuery(prompt)}><Icon size={19} /><span><strong>{title}</strong><small>{prompt}</small></span><ChevronRight size={16} /></button>
          ))}
        </section>
      )}

      <form className={submittedQuery ? "composer is-conversation" : "composer"} onSubmit={submit}>
        <label htmlFor="aura-query" className="sr-only">Ask a biology question</label>
        <textarea id="aura-query" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); }
        }} placeholder="Ask a biology question…" rows={2} />
        <div className="composer__controls">
          <div className="field-compact"><label htmlFor="learner-level">Level</label><select id="learner-level" value={settings.learnerLevel} onChange={(event) => update({ learnerLevel: event.target.value as typeof settings.learnerLevel })}><option value="high_school">High school</option><option value="undergraduate">Undergraduate</option><option value="postgraduate">Postgraduate</option><option value="research">Research</option></select></div>
          <div className="field-compact"><label htmlFor="teaching-mode">Teaching style</label><select id="teaching-mode" value={settings.teachingMode} onChange={(event) => update({ teachingMode: event.target.value as TeachingMode })}>{teachingModes.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}</select></div>
          <div className="field-compact"><label htmlFor="context-depth">Evidence</label><select id="context-depth" value={settings.contextDepth} onChange={(event) => update({ contextDepth: event.target.value as typeof settings.contextDepth })}><option value="none">No retrieval</option><option value="standard">Standard</option><option value="expanded">Expanded</option><option value="hierarchical">Hierarchical</option></select></div>
          <div className="composer__spacer" />
          {isRunning ? <button type="button" className="send-button is-stop" onClick={cancel} aria-label="Stop answer"><CircleStop size={18} /></button> : <button className="send-button" type="submit" disabled={!query.trim()} aria-label="Ask AURA"><ArrowUp size={19} /></button>}
        </div>
        <div className="composer__note"><StatusPill tone={settings.externalCritic ? "warning" : "success"}>{settings.externalCritic ? "External GLM critique enabled" : "On-device generation"}</StatusPill><span>Enter to send · Shift + Enter for a new line</span></div>
      </form>

      <CitationDrawer citations={citations} selectedId={selectedCitation} open={drawerOpen} onOpenChange={setDrawerOpen} developerMode={settings.developerMode} />
    </div>
  );
}

function WorkspaceSnapshot() {
  const [selectedId, setSelectedId] = useState(demoProcesses[0].process_id);
  const selected = demoProcesses.find((process) => process.process_id === selectedId) ?? demoProcesses[0];

  return (
    <section className="workspace-snapshot" aria-label="Mock pipeline and recent runs">
      <div className="snapshot-pipeline">
        <header className="snapshot-heading">
          <div><span className="eyebrow"><Activity size={13} /> Mock workspace</span><h2>Pipeline pulse</h2><p>Select a stage to inspect its current simulated state.</p></div>
          <span className="live-indicator"><i />2 processes active</span>
        </header>
        <div className="pipeline-route" role="tablist" aria-label="Mock pipeline processes">
          {demoProcesses.map((process, index) => (
            <button key={process.process_id} type="button" role="tab" aria-selected={selectedId === process.process_id} className={selectedId === process.process_id ? "is-selected" : ""} onClick={() => setSelectedId(process.process_id)}>
              <span className="route-index">0{index + 1}</span>
              <span><strong>{process.label}</strong><small>{process.status}</small></span>
              <b>{process.progress}%</b>
            </button>
          ))}
        </div>
        <div className="process-focus" aria-live="polite">
          <div className="progress-ring" style={{ background: `conic-gradient(var(--teal) ${selected.progress * 3.6}deg, #e4e9e6 0deg)` }}><span>{selected.progress}<small>%</small></span></div>
          <div><span className="focus-status"><i />{selected.status}</span><h3>{selected.detail}</h3><p>{selected.helper}. This is preview data and will switch to the live status endpoint when the backend is connected.</p></div>
          <Workflow size={26} />
        </div>
      </div>

      <aside className="snapshot-runs">
        <header><div><span className="eyebrow">Recent demos</span><h2>Pipeline runs</h2></div><Link to="/traces/run-demo-4821">View trace <ChevronRight size={14} /></Link></header>
        <div className="snapshot-run-list">
          {demoRuns.map((run, index) => (
            <Link to={`/traces/${run.run_id}`} key={run.run_id}>
              <span className="run-sequence">{String(index + 1).padStart(2, "0")}</span>
              <span><strong>{run.query}</strong><small><Clock3 size={11} />{run.duration} · {run.teaching_mode.replace("_", "-")}</small></span>
              <span className={run.external_critic_used ? "run-route external" : "run-route"}>{run.external_critic_used ? "GLM" : "Device"}</span>
            </Link>
          ))}
        </div>
      </aside>
    </section>
  );
}
