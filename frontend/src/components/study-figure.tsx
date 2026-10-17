import { useEffect, useImperativeHandle, useRef, useState, type Ref } from 'react';
import { useQuery,useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { StudyFigure,VisualConfig,VisualPayloadPreview } from '../types';
import { StudyCrop } from './study-crop';
import { StudyUnitContent,locatorLabel } from './study-source';

export const methodLabel=(method?:string)=>({native_text:'Native extracted text',ocr:'OCR transcription · numbers unverified',vlm:'Model-described figure · interpreted',user_annotation:'User annotation · not independently verified'}[method??'native_text']??'Unknown source method');

function FigureEditor({pack,doc,figure}:{pack:string;doc:string;figure:StudyFigure}) {
  const client=useQueryClient(); const [crop,setCrop]=useState(false); const [text,setText]=useState(''); const [error,setError]=useState('');
  const revisions=useQuery({queryKey:['study-figure-revisions',pack,doc,figure.figure_id],queryFn:()=>api.studyPacks.revisions(pack,doc,figure.figure_id)});
  async function save(work:()=>Promise<unknown>) {
    try { setError(''); await work(); await client.invalidateQueries({queryKey:['study-figures',pack,doc]}); await client.invalidateQueries({queryKey:['study-figure-revisions',pack,doc,figure.figure_id]}); }
    catch(e) {setError(e instanceof Error?e.message:'Could not save revision.');}
  }
  return <section className="study-preview" aria-label="Figure interpretation revisions">
    <p>{locatorLabel(figure.locator)} · {figure.frame}</p>
    <img src={api.studyPacks.figureUrl(pack,doc,figure.figure_id)} alt="Selected source crop, not a generated image" />
    <button onClick={()=>setCrop(!crop)}>Manual crop / override skip</button>
    {crop && <StudyCrop sourceUrl={api.studyPacks.assetUrl(pack,doc,figure.asset_id)} initial={figure.bbox} onSave={box=>void save(()=>api.studyPacks.crop(pack,doc,figure.figure_id,box))} />}
    <label>Your correction (creates a separate, unverified revision)<textarea value={text} maxLength={10000} onChange={e=>setText(e.target.value)} /></label>
    <button disabled={!text.trim()} onClick={()=>void save(()=>api.studyPacks.annotate(pack,doc,figure.figure_id,text))}>Save user annotation</button>
    {(error||revisions.error) && <p role="alert">{error||revisions.error?.message}</p>}
    {revisions.data?.revisions.map(unit=><details key={unit.unit_id}><summary>{methodLabel(unit.provenance)} · {unit.active?'active':'immutable earlier revision'}</summary><StudyUnitContent pack={pack} doc={doc} unit={unit} /></details>)}
  </section>;
}

export interface VisualPrepareHandle { prepare:(signal:AbortSignal,stage:(value:string)=>void)=>Promise<void>; }
export function abortableDelay(signal:AbortSignal) {
  return new Promise<void>((resolve,reject)=>{
    if(signal.aborted) {reject(new DOMException('Cancelled','AbortError'));return;}
    const cancel=()=>{clearTimeout(timer);reject(new DOMException('Cancelled','AbortError'));};
    const timer=setTimeout(()=>{signal.removeEventListener('abort',cancel);resolve();},1000);
    signal.addEventListener('abort',cancel,{once:true});
  });
}
export function StudyVisualManager({pack,doc,question='',think,preparationRef,autoSelectSingle=false}:{pack:string;doc:string;question?:string;think?:boolean;preparationRef?:Ref<VisualPrepareHandle>;autoSelectSingle?:boolean}) {
  const client=useQueryClient(); const [selected,setSelected]=useState<string[]>([]); const [provider,setProvider]=useState<VisualConfig['provider']>('ollama');
  const [model,setModel]=useState('qwen3.5:4b'); const [swap,setSwap]=useState(false); const [error,setError]=useState(''); const [busy,setBusy]=useState(false);
  const [ownThink,setOwnThink]=useState(false);
  const [job,setJob]=useState<string|null>(null); const [editor,setEditor]=useState<StudyFigure|null>(null); const [preview,setPreview]=useState<VisualPayloadPreview|null>(null); const [approve,setApprove]=useState(false);
  const figures=useQuery({queryKey:['study-figures',pack,doc],queryFn:()=>api.studyPacks.figures(pack,doc)});
  const history=useQuery({queryKey:['study-visual-history',pack,doc],queryFn:()=>api.studyPacks.visualList(pack,doc)});
  const status=useQuery({queryKey:['study-visual-job',pack,job],queryFn:()=>api.studyPacks.visualStatus(pack,job!),enabled:!!job,refetchInterval:q=>['queued','running'].includes(q.state.data?.state??'queued')?1000:false});
  const external=figures.data?.external_allowed??false;
  const thinking=provider==='ollama'&&(think??ownThink);
  const config:VisualConfig={provider,model,managed_swap:swap,think:thinking,num_predict:thinking?4096:2048,timeout_seconds:thinking?600:180,...(question?{question}:{}),...(provider==='groq'?{consent:{external_allowed:external,images:approve,hints:approve,disclosure_version:'visual-v1'}}:{})};
  // Preview config must match start config, including the explicit consent fields.
  const previewConfig:VisualConfig={...config,...(provider==='groq'?{consent:{external_allowed:external,images:true,hints:true,disclosure_version:'visual-v1'}}:{})};
  function changed() {setPreview(null);setApprove(false);}
  const selectedOnce=useRef(false);
  useEffect(()=>{if(autoSelectSingle&&!selectedOnce.current&&figures.data?.figures.length===1){selectedOnce.current=true;setSelected([figures.data.figures[0].figure_id]);}},[autoSelectSingle,figures.data]);
  useEffect(()=>{setPreview(null);setApprove(false);},[question]);
  useImperativeHandle(preparationRef,()=>({prepare:async(signal,stage)=>{
    let boundSelection=[...selected];
    if(!boundSelection.length&&autoSelectSingle&&!selectedOnce.current){
      const ready=await api.studyPacks.figures(pack,doc);
      if(ready.figures.length===1){boundSelection=[ready.figures[0].figure_id];selectedOnce.current=true;setSelected(boundSelection);}
    }
    if(!boundSelection.length||boundSelection.length>20) throw new Error('Select the image or a manual crop before Ask.');
    if(provider==='groq'&&(!external||!preview||!approve)) throw new Error('Preview and approve this question’s exact hosted payload first.');
    if(signal.aborted) throw new DOMException('Cancelled','AbortError');
    stage(provider==='ocr'?'Transcribing image':'Interpreting image');
    const result=await api.studyPacks.visualStart(pack,boundSelection,{...config},preview?.preview_hash);
    if(signal.aborted){await api.studyPacks.visualAction(pack,result.job_id,'cancel').catch(()=>{});throw new DOMException('Cancelled','AbortError');}
    setJob(result.job_id);
    const cancel=()=>{void api.studyPacks.visualAction(pack,result.job_id,'cancel').catch(()=>{});};
    signal.addEventListener('abort',cancel,{once:true});
    try {
      for(;;){
        await abortableDelay(signal);
        const current=await api.studyPacks.visualStatus(pack,result.job_id);
        if(signal.aborted) throw new DOMException('Cancelled','AbortError');
        if(['queued','running'].includes(current.state)) continue;
        if(current.state!=='completed') throw new Error(current.error||current.checkpoints.find(c=>c.error)?.error||`Visual job ${current.state}; inspect and resume explicitly.`);
        return;
      }
    } finally {signal.removeEventListener('abort',cancel);}
  }}));
  async function action(work:()=>Promise<unknown>) {
    try {setBusy(true);setError('');await work();await client.invalidateQueries({queryKey:['study-figures',pack,doc]});await client.invalidateQueries({queryKey:['study-visual-history',pack,doc]});}
    catch(e) {setError(e instanceof Error?e.message:'Visual action failed.');} finally {setBusy(false);}
  }
  const completed=status.data?.checkpoints.filter(c=>c.state==='completed').length??0;
  return <section className="study-visual query-panel" aria-label="Explicit visual processing">
    <h3>Figures & transcription</h3><p>Native text stays automatic. OCR and vision run only when you start a selected pass. Interpretations never certify themselves or their numbers.</p>
    {(error||figures.error||status.error||history.error) && <p role="alert">{error||figures.error?.message||status.error?.message||history.error?.message}</p>}
    {figures.data?.warnings?.map(warning=><p role="alert" key={warning}>{warning}</p>)}
    <div className="study-toolbar">
      <label>Visual provider<select value={provider} onChange={e=>{const value=e.target.value as VisualConfig['provider'];setProvider(value);setModel(value==='ocr'?'eng':value==='groq'?'qwen/qwen3.8-27b':'qwen3.5:4b');changed();}}><option value="ollama">Local Ollama vision</option><option value="ocr">Local Tesseract OCR</option><option value="groq">Groq · external, opt-in</option></select></label>
      <label>{provider==='ocr'?'Installed OCR language':'Exact model ID'}<input value={model} maxLength={160} onChange={e=>{setModel(e.target.value);changed();}} /></label>
      {provider==='ollama' && <label><input type="checkbox" checked={swap} onChange={e=>{setSwap(e.target.checked);changed();}} />Allow unloading AURA’s managed generator only</label>}
      {provider==='ollama' && think===undefined && <label><input type="checkbox" checked={ownThink} onChange={e=>{setOwnThink(e.target.checked);changed();}} />Enable vision thinking · up to 4,096 output tokens / 10 minutes</label>}
    </div>
    {provider==='ollama' && <p>Free VRAM and the installed vision capability/digest are checked at Start. Busy/missing models defer visibly; there are no downloads or automatic switches.</p>}
    {provider==='groq' && <div className="study-confirm"><p>Selected crops and OCR/caption hints leave your device. Provider logs/retention are outside local purge. API key comes only from the server environment. Default job budget: 50,000 tokens.</p>
      <label><input type="checkbox" checked={external} disabled={busy} onChange={e=>void action(async()=>{await api.studyPacks.visualPermission(pack,e.target.checked);changed();})} />Allow external processing for this pack</label>
      <button disabled={busy||!external||!selected.length} onClick={()=>void action(async()=>{setPreview(await api.studyPacks.visualPreview(pack,selected,previewConfig));setApprove(false);})}>Preview exact hosted payload</button>
      {preview && <><p>{preview.disclosure}</p><p>Question focus also sent: {question||'(none)'}</p>{preview.figures.map(f=><details key={f.figure_id}><summary>{f.image_bytes.toLocaleString()} image bytes · {f.crop_sha256.slice(0,12)}</summary><img src={api.studyPacks.figureUrl(pack,doc,f.figure_id)} alt="Exact selected crop for external processing" /><pre>OCR hint: {f.ocr_hint || '(none)'}{'\n'}Caption hint: {f.caption_hint || '(none)'}</pre></details>)}<label><input type="checkbox" checked={approve} onChange={e=>setApprove(e.target.checked)} />Approve exactly these crops and hints for this job</label></>}
    </div>}
    <div className="study-figure-list">{figures.data?.figures.map((f,i)=><article key={f.figure_id}><label><input type="checkbox" aria-label={`Select figure ${i+1}`} checked={selected.includes(f.figure_id)} onChange={e=>{setSelected(e.target.checked?[...selected,f.figure_id]:selected.filter(id=>id!==f.figure_id));changed();}} /><span>{f.figure_label&&`Fig. ${f.figure_label} · `}{locatorLabel(f.locator)} · {f.reason}</span></label><small>{f.exclusion_reason?`Suggested skip: ${f.exclusion_reason} (manual selection overrides)`:'Eligible'}</small><button onClick={()=>setEditor(f)}>Inspect figure {i+1}</button></article>)}</div>
    {figures.data?.figures.length===0 && <p>No previewable figure candidates in this document.</p>}
    <p>{selected.length} selected · 20 maximum per default job; run another explicit pass for remaining figures.</p>
    {!preparationRef && <button disabled={busy||!model.trim()||!selected.length||selected.length>20||provider==='groq'&&(!external||!preview||!approve)} onClick={()=>void action(async()=>{const result=await api.studyPacks.visualStart(pack,selected,config,preview?.preview_hash);setJob(result.job_id);})}>Start visual pass</button>}
    {preparationRef && <p>Click Ask to run the selected pass, index its result, then answer. Upload and polling never start inference.</p>}
    {!!history.data?.jobs.length && <details><summary>Visual job history · inspect before resuming</summary>{history.data.jobs.map(previous=><button key={previous.job_id} onClick={()=>setJob(previous.job_id)}>Inspect job {previous.job_id.slice(0,8)} · {previous.state}</button>)}</details>}
    {job && <div role="status"><p>{status.data?.state??'queued'} · {completed}/{status.data?.checkpoints.length??selected.length} completed · {status.data?.tokens_used??0} tokens</p><p>{status.data?.error}</p>
      {status.data?.checkpoints.map(cp=><p key={cp.item_id}>{cp.state} · {cp.attempts} attempt(s) {cp.error} {cp.resume_at && `Earliest explicit resume: ${new Date(cp.resume_at*1000).toLocaleString()}`}</p>)}
      {(['queued','running'].includes(status.data?.state??'queued')?['pause','cancel']:['paused','partial','failed'].includes(status.data?.state??'')?['resume','cancel']:[]).map(kind=><button key={kind} disabled={busy} onClick={()=>void action(async()=>{await api.studyPacks.visualAction(pack,job,kind as 'pause'|'cancel'|'resume');await client.invalidateQueries({queryKey:['study-visual-job',pack,job]});})}>{kind==='resume'?'Resume unfinished figures':kind==='pause'?'Pause visual job':'Cancel visual job'}</button>)}
    </div>}
    {editor && <FigureEditor key={editor.figure_id} pack={pack} doc={doc} figure={editor} />}
  </section>;
}
