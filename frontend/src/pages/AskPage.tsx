import { ArrowUp, BookOpenCheck, BrainCircuit, ChevronRight, CircleStop, FlaskConical, Layers3, Library, LockKeyhole, Sparkles } from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import { Link, useSearchParams } from "react-router-dom";
import { AnswerView, CitationDrawer, StatusPill } from "../components/ui";
import { useSettings } from "../context/settings";
import { useRun } from "../hooks/use-run";
import type { ImageAttachment, RunRequest, TeachingMode, VisualOutput } from "../types";
import {AskImage,type AskImageHandle} from '../components/ask-image';
import {needsVisualQuestion,prepareDocumentQuestion} from '../lib/prepare-document-question';

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
  const { state, start, cancel, reset } = useRun();
  const [params] = useSearchParams();
  const packs = useQuery({ queryKey: ['study-packs'], queryFn: api.studyPacks.list, refetchInterval: 5000 });
  const [packId, setPackId] = useState(() => params.get('pack_id') ?? '');
  const [privateCriticConsent, setPrivateCriticConsent] = useState(false);
  const [think,setThink]=useState(false);
  const [answerMode,setAnswerMode]=useState<'tutor'|'strict'>('tutor');
  const [visualOutput,setVisualOutput]=useState<VisualOutput>('none');
  const packReady = !packId || !!packs.data?.packs.some((pack) => pack.pack_id === packId && ['sparse-ready', 'hybrid-ready'].includes(pack.state));
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedCitation, setSelectedCitation] = useState<string>();
  const [attachment,setAttachment]=useState<ImageAttachment|null>(null);
  const image=useRef<AskImageHandle>(null); const preparing=useRef<AbortController|null>(null);
  const [imageStage,setImageStage]=useState(''); const [imageError,setImageError]=useState('');
  const isRunning = !!imageStage || state.status === "submitting" || state.status === "streaming";
  useEffect(()=>()=>preparing.current?.abort(),[]);
  function clearAnswer(){preparing.current?.abort();setImageStage('');setSubmittedQuery('');setDrawerOpen(false);setSelectedCitation(undefined);reset();}
  function changeImage(value:ImageAttachment|null){
    if(value?.attachment_id!==attachment?.attachment_id){clearAnswer();setPrivateCriticConsent(false);setImageError('');}
    setAttachment(value);
  }
  const citations = state.answer?.citations ?? [];
  useEffect(() => {
    const purge = (event: Event) => { if ([packId,attachment?.attachment_id].includes((event as CustomEvent<string>).detail)) { clearAnswer();setImageError('A selected private source was removed or expired.');if((event as CustomEvent<string>).detail===packId)setPackId(''); } };
    window.addEventListener('study-pack-purged', purge);
    return () => window.removeEventListener('study-pack-purged', purge);
  }, [packId,attachment?.attachment_id]);
  useEffect(()=>{
    if(packId&&packs.data&&!packs.data.packs.some(p=>p.pack_id===packId&&p.state!=='purge-pending')){
      clearAnswer();setPackId('');setPrivateCriticConsent(false);setImageError('Selected context was removed; previous private answer cleared.');
    }
  },[packId,packs.data]);

  const activeStage = useMemo(() => [...state.trace].reverse().find((item) => item.status === "completed")?.stage, [state.trace]);

  function openCitation(id?: string) {
    setSelectedCitation(id);
    setDrawerOpen(true);
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || isRunning || !packReady) return;
    const request: RunRequest = {
      query: trimmed,
      learner_level: settings.learnerLevel,
      teaching_mode: settings.teachingMode,
      response_length: settings.responseLength,
      context_depth: settings.contextDepth,
      source_types: [],
      allow_external_critic: packId || attachment ? privateCriticConsent : settings.externalCritic,
      evidence_scope: packId || attachment ? 'pack_only' : 'core',
      pack_id: attachment?.attachment_id || packId || null,
      ...(attachment?{attachment_id:attachment.attachment_id,context_pack_id:packId||null}:{}),
      think,
      visual_output:visualOutput,
      ...(packId || attachment ? {answer_mode:answerMode} : {}),
    };
    if(attachment || packId && needsVisualQuestion(trimmed)){
      const active=new AbortController();preparing.current=active;setImageError('');setImageStage('Preparing image');reset();
      try{
        if(attachment){
          if(!image.current)throw new Error('Image controls are not ready; no answer started.');
          await image.current.prepare(active.signal,setImageStage);
        }else{
          request.figure_ids=await prepareDocumentQuestion(packId,trimmed,think,active.signal,setImageStage);
        }
        if(active.signal.aborted)return;
      }catch(e){if(!active.signal.aborted)setImageError(e instanceof Error?e.message:'Image processing failed; resume explicitly.');return;}
      finally{if(preparing.current===active){preparing.current=null;setImageStage('');}}
    }
    setSubmittedQuery(trimmed);
    setQuery("");
    void start(request);
  }

  return (
    <div className={submittedQuery ? "ask-page" : "ask-page is-landing"}>
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

      {!submittedQuery && (
        <section className="prompt-grid" aria-label="Example questions">
          {prompts.map(({ icon: Icon, title, prompt }) => (
            <button key={title} onClick={() => setQuery(prompt)} type="button">
              <Icon size={19} />
              <span><strong>{title}</strong><small>{prompt}</small></span>
              <ChevronRight size={16} />
            </button>
          ))}
        </section>
      )}

      {submittedQuery && (
        <section className="conversation" aria-label="Current conversation">
          <div className="user-message"><span>You</span><p>{submittedQuery}</p></div>
          {isRunning && (
            <div className="run-progress" role="status">
              <span className="orbit-loader" />
              <div><strong>{activeStage ? `${activeStage[0].toUpperCase()}${activeStage.slice(1)} complete` : "Starting answer pipeline"}</strong><span>{state.status === "submitting" ? "Creating a traceable run…" : "Grounding the response in selected evidence…"}</span></div>
              {state.runId && <Link to={`/traces/${state.runId}`}>View trace <ChevronRight size={14} /></Link>}
            </div>
          )}
          {(state.markdown || state.answer) && <AnswerView answer={state.answer} markdown={state.markdown} onCitation={openCitation} privateEvidence={!!packId||!!attachment} />}
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

      <AskImage ref={image} attachment={attachment} onChange={changeImage} onUnavailable={clearAnswer} disabled={isRunning} question={query.trim()} think={think} />
      {imageStage&&<p role="status">{imageStage}… Click stop to cancel this question’s intent.</p>}
      {imageError&&<p className="error-banner" role="alert">{imageError}</p>}
      <form className={submittedQuery ? `composer is-conversation${state.answer?.visuals?.length?' has-visual':''}` : "composer"} onSubmit={event=>void submit(event)}>
        <div className="study-ask-scope"><label htmlFor="study-scope">Answer from</label><select id="study-scope" value={packId} disabled={isRunning} onChange={(event) => { setPackId(event.target.value); setPrivateCriticConsent(false);clearAnswer(); }}><option value="">{attachment?'Image only · no core fallback':'Original biology corpus'}</option>{packs.data?.packs.filter(p=>p.pack_id!==attachment?.attachment_id).map((pack) => <option key={pack.pack_id} value={pack.pack_id}>{pack.name} · {pack.state}</option>)}</select><Link to="/study-packs">Manage material</Link></div>
        {(packId||attachment) && <div className="study-private-note"><p>Pack-only: no memory/core-corpus fallback. Private answers stay out of browser archives.{!packReady && ' Wait for the selected pack to finish indexing.'}</p><label htmlFor="study-answer-mode">Study answer mode</label><select id="study-answer-mode" disabled={isRunning} value={answerMode} onChange={event=>setAnswerMode(event.target.value as 'tutor'|'strict')}><option value="tutor">Tutor · show supported parts</option><option value="strict">Strict · refuse incomplete support</option></select><label><input type="checkbox" disabled={isRunning} checked={privateCriticConsent} onChange={(event) => setPrivateCriticConsent(event.target.checked)} />Allow external critique: sends question, draft and private source excerpts from the image and any selected pack to the configured provider.</label></div>}
        <label><input type="checkbox" checked={think} disabled={isRunning} onChange={event=>setThink(event.target.checked)} />Enable local model thinking</label>
        <div className="field-compact"><label htmlFor="visual-output">Answer visual</label><select id="visual-output" value={visualOutput} disabled={isRunning} onChange={event=>setVisualOutput(event.target.value as VisualOutput)}><option value="none">Off — text only</option><option value="auto">On — automatic</option><option value="source">Source highlight</option><option value="diagram">Diagram</option><option value="comparison">Comparison table</option><option value="procedure">Procedure steps</option><option value="plot">Data plot</option></select></div>
        {visualOutput!=='none'&&<p className="visual-caption">{visualOutput==='auto'?'Chooses a useful grounded visual, or keeps the answer text-only.':'Optional, local and source-grounded. Unsupported visuals are omitted; your text answer remains unchanged.'}{!packId&&!attachment&&' Core visuals require inline-cited NLI-supported facts; source-image views need study material.'}</p>}
        {think&&<p>Extra reasoning uses a larger bounded output/time budget and can be slower. It does not change what counts as verified evidence.</p>}
        <label htmlFor="aura-query" className="sr-only">Ask a biology question</label>
        <textarea id="aura-query" value={query} disabled={isRunning} maxLength={attachment?4000:undefined} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); }
        }} placeholder="Ask a biology question…" rows={2} />
        <div className="composer__controls">
          <div className="field-compact"><label htmlFor="learner-level">Level</label><select id="learner-level" value={settings.learnerLevel} onChange={(event) => update({ learnerLevel: event.target.value as typeof settings.learnerLevel })}><option value="high_school">High school</option><option value="undergraduate">Undergraduate</option><option value="postgraduate">Postgraduate</option><option value="research">Research</option></select></div>
          <div className="field-compact"><label htmlFor="teaching-mode">Teaching style</label><select id="teaching-mode" value={settings.teachingMode} onChange={(event) => update({ teachingMode: event.target.value as TeachingMode })}>{teachingModes.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}</select></div>
          <div className="field-compact"><label htmlFor="context-depth">Evidence</label><select id="context-depth" value={packId && settings.contextDepth === 'none' ? 'standard' : settings.contextDepth} onChange={(event) => update({ contextDepth: event.target.value as typeof settings.contextDepth })}>{!packId && <option value="none">No retrieval</option>}<option value="standard">Standard</option><option value="expanded">Expanded</option><option value="hierarchical">Hierarchical</option></select></div>
          <div className="composer__spacer" />
          {isRunning ? <button type="button" className="send-button is-stop" onClick={()=>{preparing.current?.abort();setImageStage('');cancel();}} aria-label="Stop answer"><CircleStop size={18} /></button> : <button className="send-button" type="submit" disabled={!query.trim() || !packReady} aria-label="Ask AURA"><ArrowUp size={19} /></button>}
        </div>
        <div className="composer__note"><StatusPill tone={(packId||attachment ? privateCriticConsent : settings.externalCritic) ? "warning" : "success"}>{(packId||attachment ? privateCriticConsent : settings.externalCritic) ? "External critique enabled" : "Local answer pipeline"}</StatusPill><span>Enter to send · Shift + Enter for a new line</span></div>
      </form>

      <CitationDrawer citations={citations} selectedId={selectedCitation} open={drawerOpen} onOpenChange={setDrawerOpen} developerMode={settings.developerMode} />
    </div>
  );
}
