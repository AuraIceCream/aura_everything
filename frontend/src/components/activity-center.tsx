import { Activity, ChevronRight, CirclePause, CirclePlay, Cloud, Cpu, FlaskConical } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { demoProcesses, demoRuns } from "../lib/mock-data";
import type { ProcessSummary } from "../types";

export function ActivityCenter() {
  const [processes, setProcesses] = useState(demoProcesses);
  const activeCount = processes.filter((process) => process.status === "running").length;

  function toggleProcess(processId: string) {
    setProcesses((current) => current.map((process) => {
      if (process.process_id !== processId || process.status === "queued" || process.status === "completed") return process;
      return { ...process, status: process.status === "running" ? "paused" : "running" };
    }));
  }

  return (
    <details className="activity-center">
      <summary aria-label="Open demo runs and processes">
        <Activity size={15} />
        <span>Demo activity</span>
        <i>{activeCount}</i>
      </summary>
      <div className="activity-popover">
        <header>
          <div><span className="eyebrow">Simulation feed</span><h2>Runs &amp; processes</h2></div>
          <span className="simulation-badge">Mock data</span>
        </header>

        <section className="activity-section">
          <div className="activity-heading"><span>Processes</span><small>{activeCount} active</small></div>
          <div className="process-list">
            {processes.map((process) => <ProcessRow key={process.process_id} process={process} onToggle={() => toggleProcess(process.process_id)} />)}
          </div>
        </section>

        <section className="activity-section">
          <div className="activity-heading"><span>Recent demo runs</span><small>{demoRuns.length} shown</small></div>
          <div className="recent-runs">
            {demoRuns.map((run) => (
              <Link to={`/traces/${run.run_id}`} key={run.run_id}>
                <span className="run-icon"><FlaskConical size={15} /></span>
                <span className="run-copy"><strong>{run.query}</strong><small>{run.teaching_mode.replace("_", "-")} · {run.duration}{run.external_critic_used ? " · GLM reviewed" : " · on-device review"}</small></span>
                <ChevronRight size={15} />
              </Link>
            ))}
          </div>
        </section>

        <footer><Cloud size={14} /><span>Frontend simulation using the planned backend contract</span></footer>
      </div>
    </details>
  );
}

function ProcessRow({ process, onToggle }: { process: ProcessSummary; onToggle: () => void }) {
  const canToggle = process.status === "running" || process.status === "paused";
  return (
    <article className={`process-row process-row--${process.status}`}>
      <div className="process-row__top">
        <span className="process-icon"><Cpu size={15} /></span>
        <span><strong>{process.label}</strong><small>{process.detail}</small></span>
        <button type="button" disabled={!canToggle} onClick={onToggle} aria-label={`${process.status === "running" ? "Pause" : "Resume"} ${process.label}`}>
          {process.status === "running" ? <CirclePause size={17} /> : <CirclePlay size={17} />}
        </button>
      </div>
      <div className="process-progress" role="progressbar" aria-label={`${process.label} progress`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={process.progress}>
        <span style={{ width: `${process.progress}%` }} />
      </div>
      <div className="process-row__meta"><span>{process.status}</span><small>{process.helper}</small><b>{process.progress}%</b></div>
    </article>
  );
}
