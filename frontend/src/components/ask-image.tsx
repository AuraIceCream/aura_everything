import {forwardRef,useEffect,useImperativeHandle,useRef,useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {api,ApiError} from '../lib/api';
import type {ImageAttachment} from '../types';
import {StudyVisualManager,abortableDelay,type VisualPrepareHandle} from './study-figure';

export interface AskImageHandle {prepare:(signal:AbortSignal,stage:(value:string)=>void)=>Promise<ImageAttachment>;}
interface Props {attachment:ImageAttachment|null;onChange:(value:ImageAttachment|null)=>void;onUnavailable:()=>void;disabled?:boolean;question:string;think?:boolean;}

export const AskImage=forwardRef<AskImageHandle,Props>(function AskImage({attachment,onChange,onUnavailable,disabled=false,question,think},ref){
  const client=useQueryClient(); const epoch=useRef(0); const mounted=useRef(true);
  const visual=useRef<VisualPrepareHandle>(null); const [busy,setBusy]=useState(false);
  const [error,setError]=useState(''); const [now,setNow]=useState(Date.now()/1000);
  const [name,setName]=useState('Saved image');
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;epoch.current++;};},[]);
  const id=attachment?.attachment_id;
  useEffect(()=>{
    const paste=(event:ClipboardEvent)=>{
      if(disabled||busy||attachment)return;
      const item=Array.from(event.clipboardData?.items??[]).find(item=>['image/png','image/jpeg'].includes(item.type));
      const file=item?.getAsFile();
      if(file){event.preventDefault();void upload(file);}
    };
    document.addEventListener('paste',paste);
    return()=>document.removeEventListener('paste',paste);
  },[disabled,busy,attachment]);
  function clearPrivate(pack:string){
    client.removeQueries({predicate:q=>q.queryKey.includes(pack)});
    window.dispatchEvent(new CustomEvent('study-pack-purged',{detail:pack}));
  }
  useEffect(()=>{
    if(!attachment)return;
    let active=true;
    const expired=()=>{clearPrivate(attachment.attachment_id);onUnavailable();onChange(null);setError('Temporary image expired. Attach it again; no answer was retained.');};
    const tick=setInterval(()=>{
      const clock=Date.now()/1000;setNow(clock);
      if(attachment.pack.retention==='temporary'&&attachment.pack.expires_at!=null&&clock>=attachment.pack.expires_at) expired();
    },1000);
    const poll=setInterval(()=>{
      void api.attachments.status(attachment.attachment_id).then(current=>{
        if(!active)return;
        onChange(current);
        void client.invalidateQueries({queryKey:['study-figures',current.attachment_id,current.document.document_id]});
      }).catch(e=>{
        if(!active)return;
        if(e instanceof ApiError&&[404,410].includes(e.status)) expired();
        else setError(e instanceof Error?e.message:'Image status unavailable; no inference started.');
      });
    },5000);
    return()=>{active=false;clearInterval(tick);clearInterval(poll);};
  },[id,attachment?.pack.retention,attachment?.pack.expires_at]);
  useImperativeHandle(ref,()=>({prepare:async(signal,stage)=>{
    if(!attachment)throw new Error('Attach an image first.');
    const bound=attachment.attachment_id;
    stage('Preparing source image');
    let current=await api.attachments.status(bound);
    while(['queued','extracting','extracted','indexing'].includes(current.job?.state??'')){
      await abortableDelay(signal);current=await api.attachments.status(bound);
    }
    if(signal.aborted)throw new DOMException('Cancelled','AbortError');
    if(current.job?.state==='failed')throw new Error(current.job.error||'Image extraction failed.');
    if(current.processing)throw new Error('A visual job is already active; inspect it before resuming.');
    if(!visual.current)throw new Error('Wait for source controls to load.');
    await visual.current.prepare(signal,stage);
    stage('Indexing interpreted evidence');
    for(;;){
      if(signal.aborted)throw new DOMException('Cancelled','AbortError');
      current=await api.attachments.status(bound);
      if(current.usable&&!current.processing&&['completed','sparse-ready','hybrid-ready'].includes(current.job?.state??'')){if(!signal.aborted)onChange(current);return current;}
      const failed=current.job?.state==='failed';
      if(failed)throw new Error(current.job?.error||'Indexing failed; retry explicitly.');
      await abortableDelay(signal);
    }
  }}));
  async function upload(file:File){
    const attempt=++epoch.current;setBusy(true);setError('');
    try{
      // Retain the response identity for cleanup even if navigation cancelled intent.
      const value=await api.attachments.upload(file);
      if(!mounted.current||epoch.current!==attempt){
        if(value.pack.retention==='temporary')void api.attachments.remove(value.attachment_id,value.attachment_id).catch(()=>{});
        return;
      }
      onChange(value);
    }catch(e){if(mounted.current&&epoch.current===attempt)setError(e instanceof Error?e.message:'Image upload failed.');}
    finally{if(mounted.current&&epoch.current===attempt)setBusy(false);}
  }
  async function detach(){
    if(!attachment)return;epoch.current++;setBusy(true);setError('');
    try{
      if(attachment.pack.retention==='temporary'){
        const result=await api.attachments.remove(attachment.attachment_id,attachment.attachment_id);
        if(!result.deleted)setError('Removal pending: an active reader must close. Server cleanup will retry.');
      }
      clearPrivate(attachment.attachment_id);onUnavailable();onChange(null);
    }catch(e){setError(e instanceof Error?e.message:'Removal failed; retry explicitly.');}
    finally{setBusy(false);}
  }
  async function save(){
    if(!attachment)return;setBusy(true);setError('');
    try{const pack=await api.attachments.save(attachment.attachment_id,name);onChange({...attachment,pack});await client.invalidateQueries({queryKey:['study-packs']});}
    catch(e){setError(e instanceof Error?e.message:'Save failed.');}finally{setBusy(false);}
  }
  const seconds=Math.max(0,Math.ceil((attachment?.pack.expires_at??now)-now));
  return <section className="ask-image" aria-label="Question image">
    <label>Attach PNG or JPEG<input type="file" accept="image/png,image/jpeg" disabled={disabled||busy||!!attachment} onChange={e=>{const file=e.target.files?.[0];if(file)void upload(file);e.target.value='';}} /></label>
    <p>One image, optionally with one saved context pack. Stored locally; temporary images expire at the shown deadline (one hour by default). Ask explicitly starts processing and answering.</p>
    {busy&&<p role="status">Updating image…</p>}
    {error&&<p role="alert">{error}</p>}
    {attachment&&<>
      <figure>{attachment.preview_asset_id?<img src={api.studyPacks.assetUrl(attachment.attachment_id,attachment.document.document_id,attachment.preview_asset_id)} alt={`Original question image, upright preview: ${attachment.document.filename}`} />:<p role="status">Source preview preparing…</p>}<figcaption>{attachment.document.filename} · {attachment.pack.retention==='temporary'?`${Math.ceil(seconds/60)} min until absolute expiry`:'Saved material · no expiry'} · Interpretations and pixel-derived numbers are unverified.</figcaption><a href={api.studyPacks.originalUrl(attachment.attachment_id,attachment.document.document_id)} download>Download original image</a></figure>
      <div className="study-toolbar">
        <button type="button" disabled={disabled||busy} onClick={()=>void detach()}>Detach image</button>
        {attachment.pack.retention==='temporary'&&<><label>Save image as<input value={name} maxLength={160} disabled={disabled||busy} onChange={e=>setName(e.target.value)} /></label><button type="button" disabled={disabled||busy||!name.trim()} onClick={()=>void save()}>Save as study material</button></>}
      </div>
      <fieldset disabled={disabled||busy}><StudyVisualManager key={attachment.attachment_id} pack={attachment.attachment_id} doc={attachment.document.document_id} question={question} think={think} preparationRef={visual} autoSelectSingle /></fieldset>
    </>}
  </section>;
});
