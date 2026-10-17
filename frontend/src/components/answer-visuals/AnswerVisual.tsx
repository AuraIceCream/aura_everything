import type {AnswerVisualResult} from '../../types';
import {SourceVisual} from './SourceVisual';
import {DiagramVisual} from './DiagramVisual';
import {ComparisonVisual} from './ComparisonVisual';
import {ProcedureVisual} from './ProcedureVisual';
import {PlotVisual} from './PlotVisual';
import {useRef,useState} from 'react';
import {downloadVisual} from './export';

export function AnswerVisual({visual,onCitation}:{visual:AnswerVisualResult;onCitation:(id:string)=>void}){
  const root=useRef<HTMLElement>(null);const [exportError,setExportError]=useState('');
  if(visual.status!=='ready'||!visual.spec)return <p className="visual-limitation" role="status">{visual.limitations[0]??'This optional visual is unavailable. The text answer is unchanged.'}</p>;
  const spec=visual.spec;
  return <section ref={root} className="answer-visual" aria-label={spec.title}>
    <h3>{spec.title}</h3>{spec.kind!=='diagram'&&<p>{spec.description}</p>}
    {spec.kind==='source'&&<SourceVisual spec={spec} onCitation={onCitation}/>}
    {spec.kind==='diagram'&&<DiagramVisual spec={spec} onCitation={onCitation}/>}
    {spec.kind==='comparison'&&<ComparisonVisual spec={spec} onCitation={onCitation}/>}
    {spec.kind==='procedure'&&<ProcedureVisual spec={spec} onCitation={onCitation}/>}
    {spec.kind==='plot'&&<PlotVisual spec={spec} onCitation={onCitation}/>}
    <div className="visual-toolbar">{(['svg','png','json'] as const).map(format=><button type="button" key={format} onClick={()=>{setExportError('');const svgs=Array.from(root.current?.querySelectorAll<SVGElement>('.visual-diagram > svg,.visual-chart svg.recharts-surface,svg[data-aura-plot="true"]')??[]);void downloadVisual(spec,svgs,format,visual.metadata).catch(()=>setExportError('Export unavailable. Your text answer and sources are unchanged.'));}}>Download {format.toUpperCase()}</button>)}</div>
    {exportError&&<p role="status">{exportError}</p>}
    <small>Downloads are local files and cannot be recalled by later pack deletion.</small>
  </section>;
}
