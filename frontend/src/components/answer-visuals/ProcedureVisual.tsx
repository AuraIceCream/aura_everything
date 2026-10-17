import type {ProcedureVisualSpec} from '../../types';
import {CitationButtons,SupportBadge} from './common';
export function ProcedureVisual({spec,onCitation}:{spec:ProcedureVisualSpec;onCitation:(id:string)=>void}){
  const List=spec.payload.ordering==='total'?'ol':'ul';
  return <section aria-label="Procedure steps">{spec.payload.ordering!=='total'&&<p>Ordering is parallel or unspecified; no total sequence is implied.</p>}
    <List className="visual-steps">{spec.payload.steps.map(step=><li key={step.id}><span>{step.text}</span><SupportBadge support={step.support}/><CitationButtons support={step.support} onCitation={onCitation}/></li>)}</List>
  </section>;
}
