import * as Dialog from "@radix-ui/react-dialog";
import { Check, ExternalLink, FileText, Info, ShieldCheck, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { clsx } from "clsx";
import type { Answer, Citation, Confidence, VerificationStatus } from "../types";

export function StatusPill({
  tone = "neutral",
  children,
}: {
  tone?: "success" | "warning" | "danger" | "info" | "neutral";
  children: React.ReactNode;
}) {
  return <span className={clsx("status-pill", `status-pill--${tone}`)}>{children}</span>;
}

export function ProgressBar({ value, label }: { value: number; label?: string }) {
  return (
    <div className="progress" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value} role="progressbar">
      <span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export function Metric({ label, value, helper }: { label: string; value: string; helper?: string }) {
  return (
    <div className="metric">
      <span className="metric__label">{label}</span>
      <strong>{value}</strong>
      {helper && <span className="metric__helper">{helper}</span>}
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action && <div className="page-header__action">{action}</div>}
    </header>
  );
}

export function AnswerView({ answer, markdown, onCitation }: { answer?: Answer; markdown: string; onCitation: (id: string) => void }) {
  return (
    <article className="answer-card" aria-live="polite">
      <div className="answer-card__heading">
        <div className="assistant-mark"><span>A</span></div>
        <div>
          <strong>AURA response</strong>
          <span>Evidence-grounded biology tutor</span>
        </div>
        {answer && <StatusPill tone={answer.verification_status === "verified" ? "success" : "warning"}>{answer.verification_status}</StatusPill>}
      </div>
      <div className="prose">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeSanitize]}
          components={{
            a: ({ href, children }) => {
              if (href?.startsWith("#citation-")) {
                const id = href.replace("#citation-", "");
                return <button className="citation-marker" onClick={() => onCitation(id)} aria-label={`Open citation ${String(children)}`}>{children}</button>;
              }
              const safe = href?.startsWith("https://") || href?.startsWith("http://");
              return safe ? <a href={href} target="_blank" rel="noreferrer">{children}</a> : <span>{children}</span>;
            },
          }}
        >
          {markdown || "Preparing a grounded response…"}
        </ReactMarkdown>
      </div>
      {answer && (
        <div className="answer-footer">
          <div className="answer-signals">
            <Signal label="Confidence" value={answer.confidence} />
            <Signal label="Verification" value={answer.verification_status} />
            <Signal label="Revision" value={answer.revised ? "Applied" : "Not needed"} />
            <Signal label="Latency" value={`${(answer.latency_ms / 1000).toFixed(1)}s`} />
          </div>
          <p><Info size={14} /> {answer.confidence_rationale}</p>
        </div>
      )}
    </article>
  );
}

function Signal({ label, value }: { label: string; value: Confidence | VerificationStatus | string }) {
  return <span><small>{label}</small><strong>{value}</strong></span>;
}

export function CitationDrawer({
  citations,
  selectedId,
  open,
  onOpenChange,
  developerMode,
}: {
  citations: Citation[];
  selectedId?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  developerMode: boolean;
}) {
  const ordered = selectedId
    ? [...citations].sort((a, b) => Number(b.citation_id === selectedId) - Number(a.citation_id === selectedId))
    : citations;
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="drawer-overlay" />
        <Dialog.Content className="evidence-drawer" aria-describedby="evidence-description">
          <div className="drawer-header">
            <div>
              <span className="eyebrow">Evidence</span>
              <Dialog.Title>Sources used</Dialog.Title>
              <Dialog.Description id="evidence-description">Passages selected to support this answer.</Dialog.Description>
            </div>
            <Dialog.Close className="icon-button" aria-label="Close evidence"><X size={18} /></Dialog.Close>
          </div>
          <div className="evidence-list">
            {ordered.map((citation) => (
              <article className={clsx("evidence-card", citation.citation_id === selectedId && "is-selected")} key={citation.citation_id}>
                <div className="evidence-card__top">
                  <span className="source-rank">{citation.rank}</span>
                  <div><strong>{citation.source_title}</strong><span>{citation.section}</span></div>
                  <StatusPill tone="info">{citation.source_type}</StatusPill>
                </div>
                <blockquote>{citation.excerpt}</blockquote>
                <div className="score-row">
                  {citation.dense_score !== undefined && <span>Dense <strong>{citation.dense_score.toFixed(2)}</strong></span>}
                  {citation.rerank_score !== undefined && <span>Rerank <strong>{citation.rerank_score.toFixed(2)}</strong></span>}
                </div>
                <footer>
                  <span><ShieldCheck size={14} /> {citation.license_id}</span>
                  {citation.url && <a href={citation.url} target="_blank" rel="noreferrer">Open source <ExternalLink size={13} /></a>}
                </footer>
                {developerMode && <div className="developer-detail"><FileText size={14} /><code>{citation.chunk_id}</code><code>{citation.source_path}</code></div>}
              </article>
            ))}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function Toggle({ checked, onCheckedChange, label, description }: { checked: boolean; onCheckedChange: (value: boolean) => void; label: string; description: string }) {
  return (
    <label className="toggle-row">
      <span><strong>{label}</strong><small>{description}</small></span>
      <button type="button" className={clsx("switch", checked && "is-on")} role="switch" aria-checked={checked} onClick={() => onCheckedChange(!checked)}>
        <span>{checked && <Check size={11} />}</span>
      </button>
    </label>
  );
}

