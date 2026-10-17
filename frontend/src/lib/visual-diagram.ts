import DOMPurify from 'dompurify';
import type {DiagramVisualSpec,VisualSupport} from '../types';

export function strokePattern(status:VisualSupport['status']):string{
  return status==='native_verified'?'0':status==='interpreted'?'6 4':'2 4';
}
const badges:Record<VisualSupport['status'],string>={native_verified:'Source checked',interpreted:'Interpreted',ocr_transcribed:'OCR',user_annotated:'Annotation',native_unverified:'Transcription'};
function escaped(text:string):string{
  return Array.from(text.replace(/\s/g,' ')).map(char=>/[\p{L}\p{N} ]/u.test(char)?char:`#${char.codePointAt(0)};`).join('');
}
export function compileDiagram(spec:DiagramVisualSpec):string{
  const {nodes,edges}=spec.payload;
  if(!nodes.length||nodes.length>20||edges.length>30||new Set(nodes.map(n=>n.id)).size!==nodes.length)throw new Error('Invalid bounded graph');
  const ids=new Map(nodes.map((node,n)=>[node.id,`v${n}`]));
  const lines=[`flowchart ${spec.version===2?spec.payload.orientation:'TD'}`];
  nodes.forEach((node,n)=>{
    if(node.label.length>120)throw new Error('Label too long');
    const role=spec.version===2?spec.payload.nodes[n].role:'entity';
    const [open,close]=role==='condition'?['{','}']:role==='process'?['(',')']:['[',']'];
    const label=spec.version===2?escaped(node.label):`${escaped(node.label)} (${badges[node.support.status]})`;
    lines.push(`v${n}${open}"${label}"${close}`);
    const fill=role==='condition'?'#fff6df':role==='process'?'#edf4fc':'#f7fbf9';
    lines.push(`style v${n} fill:${fill},stroke:#176b5b,color:#18201f,stroke-width:2px,stroke-dasharray:${strokePattern(node.support.status)}`);
  });
  if(spec.version===2){
    if(spec.payload.groups.length>8)throw new Error('Too many groups');
    const grouped=new Set<string>();
    spec.payload.groups.forEach((group,n)=>{
      lines.push(`subgraph g${n}["${escaped(group.label)}${group.mode==='presentation'?' (layout only)':''}"]`);
      for(const id of group.node_ids){if(!ids.has(id)||grouped.has(id))throw new Error('Invalid group membership');grouped.add(id);lines.push(ids.get(id)!);}
      lines.push('end');
      lines.push(`style g${n} fill:#f1f5f4,stroke:#6a837a,stroke-dasharray:${group.support?strokePattern(group.support.status):'2 4'}`);
    });
  }
  edges.forEach((edge,n)=>{
    if(!ids.has(edge.from_id)||!ids.has(edge.to_id)||edge.label.length>120)throw new Error('Invalid edge');
    const label=edge.label+(spec.version===2&&spec.payload.edges[n].conditions.length?' · '+spec.payload.edges[n].conditions.join('; '):'');
    const arrow=spec.version===2&&edge.relation==='associated_with'?'---':'-->';
    const visible=spec.version===2?escaped(label):`${escaped(label)} (${badges[edge.support.status]})`;
    lines.push(`${ids.get(edge.from_id)} ${spec.version===2?`e${n}@`:''}${arrow}|"${visible}"| ${ids.get(edge.to_id)}`);
    lines.push(`linkStyle ${n} stroke:#176b5b,stroke-width:2px,stroke-dasharray:${strokePattern(edge.support.status)}`);
  });
  return lines.join('\n');
}

export function applyDiagramSemantics(raw:string,spec:DiagramVisualSpec):string{
  const safe=sanitizeVisualSvg(raw);if(spec.version===1)return safe;
  const doc=new DOMParser().parseFromString(safe,'image/svg+xml');const root=doc.documentElement;
  const ns='http://www.w3.org/2000/svg';const prefix=(root.id||'aura').replace(/[^a-zA-Z0-9_-]/g,'');
  const defs=doc.createElementNS(ns,'defs');root.prepend(defs);
  for(const [name,path] of [['inhibition','M2 0 L2 10'],['activation','M0 0 L10 5 L0 10 Z'],['containment','M0 5 L5 0 L10 5 L5 10 Z']]){
    const marker=doc.createElementNS(ns,'marker');marker.id=`${prefix}-${name}`;
    Object.entries({viewBox:'0 0 10 10',refX:'9',refY:'5',markerWidth:'10',markerHeight:'10',orient:'auto',markerUnits:'userSpaceOnUse'}).forEach(([k,v])=>marker.setAttribute(k,v));
    const shape=doc.createElementNS(ns,'path');shape.setAttribute('d',path);shape.setAttribute('stroke','#176b5b');shape.setAttribute('stroke-width','2');shape.setAttribute('fill',name==='activation'?'#176b5b':'none');marker.append(shape);defs.append(marker);
  }
  const paths=[...root.querySelectorAll<SVGPathElement>('path.flowchart-link')];
  if(paths.length!==spec.payload.edges.length)throw new Error('Rendered edges do not match checked graph');
  spec.payload.edges.forEach((edge,n)=>{
    const path=paths.find(p=>p.id===`e${n}`||p.getAttribute('data-id')===`e${n}`);
    if(!path)throw new Error('Unidentified checked edge');
    path.removeAttribute('marker-start');path.removeAttribute('marker-end');
    const marker=edge.relation==='associated_with'?null:edge.relation==='inhibits'?'inhibition':edge.relation==='part_of'?'containment':'activation';
    if(marker)path.setAttribute('marker-end',`url(#${prefix}-${marker})`);
    path.setAttribute('stroke-dasharray',strokePattern(edge.support.status));
    path.style.strokeDasharray=strokePattern(edge.support.status);
    path.setAttribute('data-relation',edge.relation);
  });
  return sanitizeVisualSvg(new XMLSerializer().serializeToString(root));
}

export function sanitizeVisualSvg(raw:string):string{
  if(raw.length>2_000_000||/<!DOCTYPE|<!ENTITY/i.test(raw))throw new Error('Unsafe SVG');
  const parsed=new DOMParser().parseFromString(raw,'image/svg+xml');
  if(parsed.querySelector('parsererror')||parsed.documentElement.localName!=='svg')throw new Error('Invalid SVG');
  const forbidden=new Set(['script','foreignobject','a','image','iframe','object','embed','animate','set','animatetransform','animatemotion']);
  const safeCss=(css:string)=>{
    const remaining=css.replace(/url\(\s*["']?#[\w:.-]+["']?\s*\)/gi,'');
    if(/url\s*\(|@import|expression\s*\(|javascript:|behavior\s*:|-moz-binding/i.test(remaining))throw new Error('Unsafe SVG CSS');
  };
  for(const element of [parsed.documentElement,...parsed.querySelectorAll('*')]){
    if(forbidden.has(element.localName.toLowerCase()))throw new Error('Unsafe SVG element');
    if(element.localName==='style')safeCss(element.textContent??'');
    for(const attribute of Array.from(element.attributes)){
      const key=attribute.name.toLowerCase();
      if(key.startsWith('on')||['src','href','xlink:href'].includes(key))throw new Error('Unsafe SVG resource');
      if(key==='style'||/url\s*\(/i.test(attribute.value))safeCss(attribute.value);
    }
  }
  const sanitized=DOMPurify.sanitize(new XMLSerializer().serializeToString(parsed.documentElement),{
    USE_PROFILES:{svg:true,svgFilters:true},FORBID_TAGS:[...forbidden],FORBID_ATTR:['href','xlink:href'],
  });
  return String(sanitized);
}

export function prepareDiagramSvg(raw:string):string{
  const safe=sanitizeVisualSvg(raw);
  const parsed=new DOMParser().parseFromString(safe,'image/svg+xml');
  // Mermaid's non-HTML text renderer leaves decimal label entities literal.
  // Decode exactly one compilation layer, only into text nodes. Re-parsing the
  // decoded value as HTML or Mermaid would reintroduce label injection.
  for(const label of parsed.querySelectorAll('text')){
    const original=label.textContent??'';
    if(!/&#\d+;/.test(original))continue;
    const decoded=original.replace(/&#(\d{1,7});/g,(_match,number:string)=>{
      const code=Number(number);if(code<32||code>0x10ffff||code>=0xd800&&code<=0xdfff)throw new Error('Invalid label character');
      return String.fromCodePoint(code);
    });
    const leaves=Array.from(label.querySelectorAll('tspan')).filter(span=>!span.querySelector('tspan'));
    if(!leaves.length){label.textContent=decoded;continue;}
    // Entity sequences can wrap across tspans. Preserve the existing text
    // positions, but distribute decoded characters without losing any labels.
    const budget=Math.max(8,...leaves.map(span=>span.textContent?.length??0));
    const characters=Array.from(decoded);let start=0;
    leaves.forEach((span,n)=>{const end=n===leaves.length-1?characters.length:Math.min(characters.length,start+budget);span.textContent=characters.slice(start,end).join('');start=end;});
  }
  return new XMLSerializer().serializeToString(parsed.documentElement);
}
