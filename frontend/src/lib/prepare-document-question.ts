import {api} from './api';
import {abortableDelay} from '../components/study-figure';

export function needsVisualQuestion(question:string){
  return /\b(?:fig(?:ure)?s?\.?\s*S?\d+(?:\.\d+)?(?:[a-z]|\s*\([a-z]\))?|diagram|graph|plot|image|flowchart|micrograph|gel|tables?\s*S?\d+)(?!\w)/i.test(question);
}

export async function prepareDocumentQuestion(pack:string,question:string,think:boolean,signal:AbortSignal,stage:(text:string)=>void){
  stage('Finding the requested figure and its source page');
  const resolved=await api.studyPacks.resolveVisualQuestion(pack,question,signal);
  if(signal.aborted)throw new DOMException('Cancelled','AbortError');
  if(!resolved.figures.length)return [];
  const ids=resolved.figures.map(f=>f.figure_id);
  stage(`Interpreting ${ids.length} source region(s) for this question`);
  // Ask is explicit local consent, never permission for a hosted upload or
  // unloading another model. Provider selection remains deliberate.
  const job=await api.studyPacks.visualStart(pack,ids,{provider:'ollama',model:'qwen3.5:4b',question,think,
    description_version:2,focus:true,num_predict:think?4096:2048,timeout_seconds:300});
  const cancel=()=>{void api.studyPacks.visualAction(pack,job.job_id,'cancel').catch(()=>{});};
  if(signal.aborted){cancel();throw new DOMException('Cancelled','AbortError');}
  signal.addEventListener('abort',cancel,{once:true});
  try{
    for(;;){
      await abortableDelay(signal);
      const current=await api.studyPacks.visualStatus(pack,job.job_id);
      if(signal.aborted)throw new DOMException('Cancelled','AbortError');
      if(['queued','running'].includes(current.state))continue;
      if(current.state!=='completed')throw new Error(current.error||current.checkpoints.find(c=>c.error)?.error||`Visual job ${current.state}. Inspect it and resume explicitly.`);
      if(current.index_error)throw new Error(current.index_error);
      if(current.indexed)return ids;
      stage('Indexing the new figure interpretation');
    }
  }finally{signal.removeEventListener('abort',cancel);}
}
