import {useEffect,useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {api} from '../../lib/api';
import type {SourceVisualSpec} from '../../types';
import {RegionImage} from '../study-crop';
import {locatorLabel} from '../study-source';
import {CitationButtons,SupportBadge} from './common';
import {SourceLabelQuiz,ocrWordsInSourceFrame} from './SourceLabelQuiz';

export function SourceVisual({spec,onCitation}:{spec:SourceVisualSpec;onCitation:(id:string)=>void}){
  const p=spec.payload;
  const safe=p.resolved&&[p.pack_id,p.document_id,p.unit_id,p.revision_id,...(p.asset_id?[p.asset_id]:[])].every(id=>/^[a-f0-9]{32}$/.test(id));
  const [unavailable,setUnavailable]=useState(false);
  const [practicing,setPracticing]=useState(false);
  const unit=useQuery({queryKey:['study-unit',p.pack_id,p.document_id,p.revision_id],queryFn:()=>api.studyPacks.unit(p.pack_id,p.document_id,p.revision_id),enabled:safe&&!unavailable,retry:false});
  const figure=unit.data?.provenance_details?.figure_id;
  const ocrRevisions=useQuery({queryKey:['figure-ocr-revisions',p.pack_id,p.document_id,figure,p.asset_checksum],queryFn:()=>api.studyPacks.revisions(p.pack_id,p.document_id,String(figure)),enabled:safe&&!unavailable&&typeof figure==='string'&&unit.data?.provenance!=='ocr',retry:false});
  useEffect(()=>{setUnavailable(false);const purge=(event:Event)=>{if((event as CustomEvent<string>).detail===p.pack_id)setUnavailable(true);};window.addEventListener('study-pack-purged',purge);return()=>window.removeEventListener('study-pack-purged',purge);},[p.pack_id,p.document_id,p.revision_id]);
  if(!safe||unavailable||unit.error)return <p role="alert">Source unavailable. No substitute image was selected.</p>;
  if(unit.isPending)return <p role="status">Loading cited source…</p>;
  if(!unit.data||unit.data.unit_id!==p.revision_id||unit.data.document_id!==p.document_id||p.asset_id&&!unit.data.asset_ids.includes(p.asset_id))return <p role="alert">Source unavailable. The immutable revision no longer matches.</p>;
  const ocr=unit.data.provenance==='ocr'?unit.data:ocrRevisions.data?.revisions.find(revision=>revision.active&&revision.provenance==='ocr'&&revision.asset_ids.includes(p.asset_id??'')&&JSON.stringify(revision.provenance_details?.bbox??null)===JSON.stringify(p.bbox));
  const raw=(ocr?.metadata.ocr as {words?:unknown}|undefined)?.words;
  const words=ocrWordsInSourceFrame(raw,(ocr?.provenance_details?.bbox as import('../../types').NormalizedBox|undefined)??null);
  const quizSource:SourceVisualSpec=!ocr?spec:spec.version===2?
    {...spec,payload:{...spec.payload,revision_id:ocr.unit_id}}:
    {...spec,payload:{...spec.payload,revision_id:ocr.unit_id}};
  return <section className="source-visual" aria-label="Cited source visual">
    <div className="visual-heading"><SupportBadge support={p.support}/><CitationButtons support={p.support} onCitation={onCitation}/></div>
    <p>{p.locators.map(locatorLabel).join(' · ')} · {p.highlight_precision==='table_row'?'Source-owned table row':p.highlight_precision==='panel'?'Source-owned panel':p.highlight_precision==='region'?'Known upright source region':p.asset_id?'Whole source · no precise claim highlight':'Source unit · no pixel-region grounding'}</p>
    {spec.version===2&&spec.payload.warnings.map(w=><p key={w} role="status">{w}</p>)}
    {!practicing&&(p.asset_id?<RegionImage sourceUrl={api.studyPacks.assetUrl(p.pack_id,p.document_id,p.asset_id)} bbox={p.bbox??undefined} highlights={spec.version===2?spec.payload.highlights:[]} alt="Cited upright source pixels; highlights are separate overlays" onError={()=>setUnavailable(true)}/>:<pre>{unit.data.text}</pre>)}
    <p className="visual-caption">Source pixels remain unchanged. A region identifies material to inspect, not independent verification.</p>
    {!practicing&&<details><summary>Read the cited source unit</summary><pre>{unit.data.text}</pre><small>Immutable revision {p.revision_id.slice(0,8)} · generation {p.generation}</small></details>}
    <SourceLabelQuiz source={quizSource} ocrWords={words} onActiveChange={setPracticing} onPracticeResult={result=>window.dispatchEvent(new CustomEvent('aura-practice-result',{detail:result}))}/>
    <a href={api.studyPacks.originalUrl(p.pack_id,p.document_id)} download>Download original</a>
  </section>;
}
