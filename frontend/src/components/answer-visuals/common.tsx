import type {VisualSupport} from '../../types';

export const supportLabels:Record<VisualSupport['status'],string>={native_verified:'Source-checked',interpreted:'Interpreted',ocr_transcribed:'OCR transcription',user_annotated:'User annotation',native_unverified:'Native transcription'};
export function SupportBadge({support}:{support:VisualSupport}){
  return <span className="visual-support" data-support={support.status} title="Source support is not independent scientific truth">{supportLabels[support.status]}</span>;
}
export function CitationButtons({support,onCitation}:{support:VisualSupport;onCitation:(id:string)=>void}){
  return <span className="visual-citations">{support.cite_ids.map(id=><button type="button" key={id} onClick={()=>onCitation(id)} aria-label={`Open ${id}`}>[{id.replace('cit-','')}]</button>)}</span>;
}
export function VisualLegend(){return <p className="visual-legend"><span>Solid: source-checked</span><span>Dashed: interpreted</span><span>Dotted: transcription/annotation</span><small>Source support is not independent scientific truth.</small></p>;}
