import { BrainCircuit, KeyRound, LockKeyhole, RotateCcw, Server, ShieldCheck, SlidersHorizontal, UserRound } from "lucide-react";
import { PageHeader, StatusPill, Toggle } from "../components/ui";
import { useSettings } from "../context/settings";
import type { LearnerLevel, TeachingMode } from "../types";

export function SettingsPage() {
  const { settings, update, reset } = useSettings();
  return (
    <div className="page-stack settings-page">
      <PageHeader eyebrow="Workspace preferences" title="Shape how AURA teaches" description="These choices stay in this browser. Secrets and corpus documents are never stored here." action={<button className="secondary-button" onClick={reset}><RotateCcw size={15} />Reset defaults</button>} />
      <div className="settings-layout">
        <div className="settings-main">
          <SettingsSection icon={UserRound} title="Learning profile" description="Defaults used when a new question does not specify its audience.">
            <div className="form-grid"><Field label="Academic level"><select value={settings.learnerLevel} onChange={(event) => update({ learnerLevel: event.target.value as LearnerLevel })}><option value="high_school">High school</option><option value="undergraduate">Undergraduate</option><option value="postgraduate">Postgraduate</option><option value="research">Research-oriented</option></select></Field><Field label="Default teaching style"><select value={settings.teachingMode} onChange={(event) => update({ teachingMode: event.target.value as TeachingMode })}><option value="direct">Direct answer</option><option value="guided">Guided explanation</option><option value="socratic">Socratic mode</option><option value="exam">Exam mode</option><option value="revision">Revision notes</option><option value="research">Research mode</option><option value="teach_back">Teach-back</option></select></Field><Field label="Response length"><select value={settings.responseLength} onChange={(event) => update({ responseLength: event.target.value as typeof settings.responseLength })}><option value="concise">Concise</option><option value="balanced">Balanced</option><option value="detailed">Detailed</option></select></Field><Field label="Retrieval depth"><select value={settings.contextDepth} onChange={(event) => update({ contextDepth: event.target.value as typeof settings.contextDepth })}><option value="none">No retrieval</option><option value="standard">Standard</option><option value="expanded">Expanded</option><option value="hierarchical">Hierarchical</option></select></Field></div>
          </SettingsSection>
          <SettingsSection icon={BrainCircuit} title="Models and inspection" description="Keep on-device generation primary and reveal operational details only when useful.">
            <Field label="Local generator"><select value={settings.localModel} onChange={(event) => update({ localModel: event.target.value })}><option>Qwen 3.6 local</option><option>Qwen 3.6 compact</option></select></Field>
            <Toggle checked={settings.developerMode} onCheckedChange={(value) => update({ developerMode: value })} label="Developer mode" description="Show chunk IDs, source paths, scores, and structured trace payloads." />
          </SettingsSection>
          <SettingsSection icon={KeyRound} title="External processing" description="External critique is optional and never receives private or unlicensed material.">
            <Toggle checked={settings.externalCritic} onCheckedChange={(value) => update({ externalCritic: value })} label="Allow Z.AI / GLM critic" description="Send a short, licensed evidence excerpt only when the on-device verifier is uncertain." />
            <div className="key-note"><LockKeyhole size={17} /><div><strong>Keys remain on the backend</strong><span>The browser receives capability status, never the API key itself.</span></div><StatusPill tone="success">Protected</StatusPill></div>
          </SettingsSection>
        </div>
        <aside className="privacy-card"><div className="privacy-card__icon"><ShieldCheck size={28} /></div><span className="eyebrow">Privacy posture</span><h2>Private by default.<br />External when enabled.</h2><p>The corpus and generator stay on-device. Licensed evidence excerpts may reach GLM only when you deliberately enable external critique.</p><ul><li><Server size={15} />On-device FastAPI and Qwen</li><li><LockKeyhole size={15} />No browser-held secrets</li><li><SlidersHorizontal size={15} />Per-run GLM opt-in</li></ul><div className={settings.externalCritic ? "privacy-status is-external" : "privacy-status"}><span /><strong>{settings.externalCritic ? "External critique enabled" : "External critique disabled"}</strong></div></aside>
      </div>
    </div>
  );
}

function SettingsSection({ icon: Icon, title, description, children }: { icon: typeof UserRound; title: string; description: string; children: React.ReactNode }) {
  return <section className="settings-section"><header><span><Icon size={19} /></span><div><h2>{title}</h2><p>{description}</p></div></header><div className="settings-section__body">{children}</div></section>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="form-field"><span>{label}</span>{children}</label>;
}
