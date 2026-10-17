import {useEffect,useId,useRef,useState} from 'react';
import type {DiagramVisualSpec} from '../../types';
import {compileDiagram,prepareDiagramSvg,applyDiagramSemantics} from '../../lib/visual-diagram';
import {supportLabels,VisualLegend} from './common';

export function DiagramVisual({spec,onCitation}:{spec:DiagramVisualSpec;onCitation:(id:string)=>void}){
  const id=useId().replace(/[^a-zA-Z0-9]/g,'');
  const root=useRef<HTMLDivElement>(null);
  const [result,setResult]=useState<{spec:DiagramVisualSpec;svg?:string;failed?:boolean}>();
  const [zoom,setZoom]=useState(1);
  useEffect(()=>{
    let active=true;
    void(async()=>{
      try{
        const mermaid=(await import('mermaid')).default;
        mermaid.initialize({startOnLoad:false,securityLevel:'strict',htmlLabels:false,fontFamily:'Arial, sans-serif',theme:'base',themeVariables:{fontFamily:'Arial, sans-serif'},flowchart:{htmlLabels:false,useMaxWidth:true,curve:'linear'}});
        const rendered=await mermaid.render(`aura${id}`,compileDiagram(spec));
        const svg=applyDiagramSemantics(prepareDiagramSvg(rendered.svg),spec);
        if(active)setResult({spec,svg});
      }catch{if(active)setResult({spec,failed:true});}
    })();
    return()=>{active=false;};
  },[spec,id]);
  const current=result?.spec===spec?result:undefined;
  useEffect(()=>{
    root.current?.querySelectorAll<SVGGElement>('g.node').forEach(element=>{
      const match=element.id.match(new RegExp(`^(?:aura${id}-)?flowchart-v(\\d+)-\\d+$`));
      const node=match?spec.payload.nodes[Number(match[1])]:undefined;
      if(!node)return;
      element.setAttribute('data-visual-node',node.id);element.setAttribute('tabindex','0');element.setAttribute('role','button');
      element.setAttribute('aria-label',`${node.label} · ${supportLabels[node.support.status]}; open source`);
    });
  },[current?.svg,spec]);
  function activate(target:EventTarget|null){
    if(!(target instanceof Element))return;
    const group=target.closest('[data-visual-node]');if(!group||!root.current?.contains(group))return;
    const node=spec.payload.nodes.find(node=>node.id===group.getAttribute('data-visual-node'));
    const cite=node?.support.cite_ids[0];if(cite&&/^cit-[1-9]\d*$/.test(cite))onCitation(cite);
  }
  return <section aria-label="Grounded diagram">
    <p>{spec.description}</p>
    {current?.failed?<p role="status">Diagram unavailable. Read the source-grounded description above.</p>:!current?.svg?<p role="status">Rendering local diagram…</p>:<>
      <div className="visual-toolbar"><label>Diagram zoom <input aria-label="Diagram zoom" type="range" min="1" max="3" step=".25" value={zoom} onChange={e=>setZoom(Number(e.target.value))}/></label></div>
      <div className="visual-scroll" onClick={e=>activate(e.target)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();activate(e.target);}}}>
        <div ref={root} className="visual-diagram" style={{width:`${zoom*100}%`}} dangerouslySetInnerHTML={{__html:current.svg}}/>
      </div>
    </>}
    <VisualLegend/>
  </section>;
}
