import {useEffect,useMemo,useState} from 'react';
import type {NormalizedBox,SourceVisualSpec} from '../../types';
import {api} from '../../lib/api';

export interface OcrWord {text:string;confidence:number;bbox:number[];}
export interface PracticeResult {pack_id:string;document_id:string;asset_id:string;revision_id:string;label_ids:string[];correct:number;attempted:number;provenance:'user_annotation';source_methods:['ocr','user_annotation'];}
function groups(words:OcrWord[]){
  const valid=words.filter(word=>typeof word.text==='string'&&word.text.trim()&&word.text.length<=120&&Number.isFinite(word.confidence)&&word.confidence>=85&&word.confidence<=100&&word.bbox?.length===4&&word.bbox.every(n=>Number.isFinite(n)&&n>=0&&n<=1)&&word.bbox[0]<word.bbox[2]&&word.bbox[1]<word.bbox[3]).sort((a,b)=>a.bbox[1]-b.bbox[1]||a.bbox[0]-b.bbox[0]);
  const result:{id:string;text:string;box:NormalizedBox}[]=[];
  for(const word of valid){
    const [x0,y0,x1,y1]=word.bbox;const last=result.at(-1);
    if(last&&Math.abs(last.box.y0-y0)<.012&&x0>=last.box.x1&&x0-last.box.x1<.035&&(last.text+' '+word.text).length<=120){last.text+=' '+word.text;last.box.x1=x1;last.box.y1=Math.max(last.box.y1,y1);}
    else result.push({id:`label-${result.length+1}`,text:word.text,box:{x0,y0,x1,y1}});
  }
  return result.slice(0,20);
}
export function ocrWordsInSourceFrame(value:unknown,crop:NormalizedBox|null):OcrWord[]{
  if(!Array.isArray(value))return [];
  return value.flatMap(item=>{
    if(!item||typeof item!=='object')return [];
    const word=item as OcrWord;
    if(!Array.isArray(word.bbox)||word.bbox.length!==4||!word.bbox.every(n=>typeof n==='number'&&Number.isFinite(n)))return [];
    const [x0,y0,x1,y1]=word.bbox;
    const bbox=crop?[crop.x0+x0*(crop.x1-crop.x0),crop.y0+y0*(crop.y1-crop.y0),crop.x0+x1*(crop.x1-crop.x0),crop.y0+y1*(crop.y1-crop.y0)]:word.bbox;
    return [{text:word.text,confidence:word.confidence,bbox}];
  });
}
function normalize(value:string){return value.normalize('NFKC').trim().replace(/\s+/g,' ').toLocaleLowerCase();}
function Quiz({source,ocrWords,onPracticeResult,onActiveChange}:{source:SourceVisualSpec;ocrWords:OcrWord[];onPracticeResult:(value:PracticeResult)=>void;onActiveChange?:(active:boolean)=>void}){
  const labels=useMemo(()=>groups(ocrWords),[ocrWords]);
  const [phase,setPhase]=useState<'closed'|'confirm'|'practice'>('closed');
  const [selected,setSelected]=useState<Record<string,boolean>>({});
  const [edited,setEdited]=useState<Record<string,string>>({});
  const [answers,setAnswers]=useState<Record<string,string>>({});
  const [revealed,setRevealed]=useState(false);const [score,setScore]=useState<number|null>(null);
  const [unavailable,setUnavailable]=useState(false);
  const p=source.payload;
  useEffect(()=>{const purge=(event:Event)=>{if((event as CustomEvent<string>).detail===p.pack_id){setUnavailable(true);setAnswers({});setEdited({});onActiveChange?.(false);}};window.addEventListener('study-pack-purged',purge);return()=>{window.removeEventListener('study-pack-purged',purge);};},[p.pack_id,onActiveChange]);
  if(unavailable)return <p role="status">Source unavailable; practice cleared.</p>;
  if(!labels.length||!p.asset_id)return <p className="visual-caption">No OCR labels available for practice. No OCR or model job was started.</p>;
  const active=labels.filter(label=>selected[label.id]&&(edited[label.id]??label.text).trim());
  function check(){
    const correct=active.filter(label=>normalize(answers[label.id]??'')===normalize(edited[label.id]??label.text)).length;
    setScore(correct);onPracticeResult({pack_id:p.pack_id,document_id:p.document_id,asset_id:p.asset_id!,revision_id:p.revision_id,
      label_ids:active.map(l=>l.id),correct,attempted:active.length,provenance:'user_annotation',source_methods:['ocr','user_annotation']});
  }
  return <section className="source-quiz" aria-label="Source label practice">
    {phase==='closed'?<button type="button" onClick={()=>setPhase('confirm')}>Practice labels</button>:phase==='confirm'?<>
      <p>Confirm or correct each OCR label before practice. Suggestions require at least 85% OCR confidence; confidence is not truth.</p>
      {labels.map((label,n)=><fieldset key={label.id}><legend>Region {n+1}</legend><label><input type="checkbox" checked={!!selected[label.id]} onChange={event=>setSelected({...selected,[label.id]:event.target.checked})}/>Use label {n+1}</label><label>Confirm label {n+1}<input type="text" maxLength={120} value={edited[label.id]??label.text} onChange={event=>setEdited({...edited,[label.id]:event.target.value})}/></label></fieldset>)}
      <button type="button" disabled={!active.length} onClick={()=>{setPhase('practice');onActiveChange?.(true);}}>Start practice</button>
    </>:<>
      <p>This is practice, not a secure exam. The original can still be opened or downloaded. Keys are confirmed transcriptions, not verified biology.</p>
      <p id={`quiz-help-${source.id}`}>Each covered region has a number. Use its numbered answer field, or use text-only recall if inspecting the picture is not accessible.</p>
      <details><summary>Text-only recall alternative</summary><p>Recall the transcription you confirmed for each numbered region; the same keyboard answer fields below apply. Reveal labels when ready.</p></details>
      <div className="figure-source"><img src={api.studyPacks.assetUrl(p.pack_id,p.document_id,p.asset_id)} alt="Source figure with numbered covered regions; answer keys are not in the alternative text" crossOrigin="anonymous" onError={()=>setUnavailable(true)}/>{!revealed&&active.map((label,n)=><span key={label.id} className="source-label-mask" aria-label={`Covered region ${n+1}`} style={{left:`${label.box.x0*100}%`,top:`${label.box.y0*100}%`,width:`${(label.box.x1-label.box.x0)*100}%`,height:`${(label.box.y1-label.box.y0)*100}%`}}>{n+1}</span>)}</div>
      {active.map((label,n)=><fieldset key={label.id}><legend>Label {n+1}</legend><label>Your answer for label {n+1}<input type="text" maxLength={120} value={answers[label.id]??''} onChange={event=>{setAnswers({...answers,[label.id]:event.target.value});setScore(null);}}/></label>{revealed&&<p>{edited[label.id]??label.text}</p>}</fieldset>)}
      {score!==null&&<p role="status">{score} of {active.length} confirmed transcriptions matched.</p>}
      <div className="visual-toolbar"><button type="button" disabled={score!==null||active.some(label=>!(answers[label.id]??'').trim())} onClick={check}>Check answers</button><button type="button" onClick={()=>setRevealed(true)}>Reveal labels</button><button type="button" onClick={()=>{setAnswers({});setRevealed(false);setScore(null);}}>Reset answers</button><button type="button" onClick={()=>{setPhase('closed');setSelected({});setEdited({});setAnswers({});onActiveChange?.(false);}}>End practice</button></div>
    </>}
  </section>;
}
export function SourceLabelQuiz(props:{source:SourceVisualSpec;ocrWords:OcrWord[];onPracticeResult:(value:PracticeResult)=>void;onActiveChange?:(active:boolean)=>void}){
  const p=props.source.payload;return <Quiz key={`${p.pack_id}/${p.document_id}/${p.asset_id}/${p.revision_id}`} {...props}/>;
}
