import type {VisualSpec,VisualSupport} from '../../types';
import {sanitizeVisualSvg} from '../../lib/visual-diagram';
import {api} from '../../lib/api';
import {supportLabels} from './common';
import {uncertaintyLabel} from '../../lib/visual-plot';

const NS='http://www.w3.org/2000/svg';
function supports(spec:VisualSpec):VisualSupport[]{
  const result:VisualSupport[]=[];
  function walk(value:unknown){if(!value||typeof value!=='object')return;
    if(Array.isArray(value)){value.forEach(walk);return;}
    const object=value as Record<string,unknown>;
    if(object.support)result.push(object.support as VisualSupport);
    Object.values(object).forEach(walk);
  }
  walk(spec.payload);return result;
}
export function visualManifest(spec:VisualSpec,generator:Record<string,unknown>={}){
  const bases=supports(spec);
  return {version:1,visual:spec,generator,
    claim_ids:[...new Set(bases.flatMap(b=>b.claim_ids))],citation_ids:[...new Set(bases.flatMap(b=>b.cite_ids))],
    provenance:[...new Set(bases.flatMap(b=>b.provenance))],
    notice:'Local download. Downloaded files cannot be recalled by later source or pack deletion. Source support is not independent scientific truth.'};
}
function element(name:string,attrs:Record<string,string>={}){
  const node=document.createElementNS(NS,name);Object.entries(attrs).forEach(([key,value])=>{
    if(key==='xmlns')node.setAttributeNS('http://www.w3.org/2000/xmlns/',key,value);
    else node.setAttribute(key,value);
  });return node;
}
function text(root:Element,value:string,x:number,y:number,size=16){
  const node=element('text',{x:String(x),y:String(y),'font-family':'Arial, sans-serif','font-size':String(size),fill:'#18201f'});
  node.textContent=value;root.append(node);
}
function wrap(value:string,width=108):string[]{
  const words=value.split(/\s+/);const lines:string[]=[];let line='';
  for(const word of words){if(line&&line.length+word.length+1>width){lines.push(line);line='';}line+=(line?' ':'')+word;}
  if(line)lines.push(line);return lines;
}
function supported(value:string,support?:VisualSupport){
  return support?`${value} [${supportLabels[support.status]}; ${support.cite_ids.join(', ')}]`:value;
}
function factualLines(spec:VisualSpec):string[]{
  if(spec.kind==='comparison')return [
    ['Criterion',...spec.payload.columns.map(c=>supported(c.text,c.support))].join(' | '),
    ...spec.payload.rows.map(row=>[supported(row.criterion.text,row.criterion.support),...spec.payload.columns.map(column=>{
      const cell=row.cells.find(c=>c.column_id===column.id);
      return cell?.status==='stated'?supported(cell.text,cell.support):'Not stated in the selected material';
    })].join(' | '))];
  if(spec.kind==='procedure')return [spec.payload.ordering==='total'?'Source-established order':'Parallel or unspecified order',
    ...spec.payload.steps.map((step,n)=>`${spec.payload.ordering==='total'?n+1+'.':'•'} ${supported(step.text,step.support)}`)];
  if(spec.kind==='plot'&&spec.version===2)return spec.payload.series.flatMap(series=>[`${series.label} · ${series.unit}`,
    ...series.points.map(p=>supported(`${p.group}${p.column?' | column '+p.column:''} | ${p.x??''} | ${p.value??'Not reported'} ${series.unit} | ${uncertaintyLabel(p)}${p.population?' | population '+p.population:''}${p.condition?' | condition '+p.condition:''}`,p.support)),
    'SD/SEM drawing endpoints are derived geometry, not observed bounds or confidence intervals.']);
  if(spec.kind==='plot')return spec.payload.series.flatMap(series=>[`${series.label} · ${series.unit}`,
    ...series.points.map(p=>supported(`${p.group} | ${p.x??''} | ${p.value??'Not reported'} ${series.unit}`,p.support))]);
  if(spec.kind==='diagram'){
    const nodes=new Map(spec.payload.nodes.map(node=>[node.id,node.label]));
    return [...spec.payload.nodes.map(node=>supported(node.label,node.support)),
      ...spec.payload.edges.map((edge,n)=>supported(`${nodes.get(edge.from_id)} → ${edge.label} → ${nodes.get(edge.to_id)}${spec.version===2?' '+spec.payload.edges[n].conditions.join('; '):''}`,edge.support))];
  }
  return [supported(['region','panel','table_row'].includes(spec.payload.highlight_precision)?`Stored source ${spec.payload.highlight_precision}`:'Whole source/unit; no precise claim highlight',spec.payload.support),...(spec.version===2?spec.payload.warnings:[])];
}
export function buildExportSvg(spec:VisualSpec,svgs:SVGElement[]=[],sourceImage?:{href:string;width:number;height:number}):string{
  const root=element('svg',{xmlns:NS,width:'1200',role:'img'});let y=36;
  text(root,spec.title,24,y,24);y+=28;
  if(spec.kind==='source'&&sourceImage){
    if(!/^data:image\/(?:png|jpeg|gif);base64,[A-Za-z0-9+/=]+$/.test(sourceImage.href)||sourceImage.href.length>70_000_000)throw new Error('Unsafe source image');
    const width=Math.min(1152,sourceImage.width),height=width*sourceImage.height/sourceImage.width;
    if(!Number.isFinite(height)||height<=0||height>6000)throw new Error('Unsupported source aspect ratio');
    root.append(element('image',{href:sourceImage.href,x:'24',y:String(y),width:String(width),height:String(height)}));
    const boxes=spec.version===2&&spec.payload.highlights.length?spec.payload.highlights.map(h=>h.bbox):(spec.payload.bbox?[spec.payload.bbox]:[]);
    for(const box of boxes)root.append(element('rect',{x:String(24+box.x0*width),y:String(y+box.y0*height),width:String((box.x1-box.x0)*width),height:String((box.y1-box.y0)*height),fill:'none',stroke:'#176b5b','stroke-width':'3'}));
    y+=height+24;
  }else if(svgs.length){
    for(const svg of svgs){
      const safe=sanitizeVisualSvg(new XMLSerializer().serializeToString(svg));
      const child=new DOMParser().parseFromString(safe,'image/svg+xml').documentElement;
      const box=child.getAttribute('viewBox')?.split(/[ ,]+/).map(Number)??[0,0,640,320];
      if(box.length!==4||!box.every(Number.isFinite)||box[2]<=0||box[3]<=0)throw new Error('Invalid export geometry');
      const height=Math.min(1800,1152*box[3]/box[2]);
      child.setAttribute('x','24');child.setAttribute('y',String(y));child.setAttribute('width','1152');child.setAttribute('height',String(height));
      child.removeAttribute('style');root.append(document.importNode(child,true));y+=height+24;
    }
  }else if(spec.kind==='source'&&spec.payload.asset_id){throw new Error('Source image is unavailable');}
  // A legend alone cannot associate support with a particular cell, step or
  // point. Carry the per-element labels and original citation IDs in artwork.
  for(const line of factualLines(spec).flatMap(line=>wrap(line))){text(root,line,24,y);y+=24;}
  y+=12;text(root,'Solid: source-checked · Interpreted: dashed · Transcriptions/annotations: dotted',24,y,14);y+=22;
  for(const source of spec.sources??[]){
    const locations=source.locators.map(loc=>loc.page?`page ${loc.page}`:loc.slide?`slide ${loc.slide}`:loc.sheet??'source unit').join(', ');
    for(const line of wrap(`${source.citation_id}: ${source.title}${locations?' · '+locations:''} · ${source.provenance}`)){text(root,line,24,y,14);y+=20;}
  }
  if(!spec.sources?.length){text(root,'Sources: '+visualManifest(spec).citation_ids.join(', '),24,y,14);y+=20;}
  text(root,'Source support is not independent truth. Downloads remain after pack deletion.',24,y,14);y+=28;
  if(y>12000)throw new Error('Export exceeds size limit');
  root.setAttribute('height',String(y));root.setAttribute('viewBox',`0 0 1200 ${y}`);
  return new XMLSerializer().serializeToString(root);
}
async function loadImage(url:string){
  return new Promise<HTMLImageElement>((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(new Error('Image unavailable'));image.src=url;});
}
async function sourcePixels(spec:VisualSpec){
  if(spec.kind!=='source'||!spec.payload.asset_id)return undefined;
  const p=spec.payload;
  if(![p.pack_id,p.document_id,p.asset_id].every(id=>/^[a-f0-9]{32}$/.test(id!)))throw new Error('Invalid source');
  const response=await fetch(api.studyPacks.assetUrl(p.pack_id,p.document_id,p.asset_id!),{cache:'no-store'});
  if(!response.ok)throw new Error('Source unavailable');
  const blob=await response.blob();
  if(!['image/png','image/jpeg','image/gif'].includes(blob.type)||blob.size>50*1024*1024)throw new Error('Unsupported source');
  const href=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=reject;reader.readAsDataURL(blob);});
  const image=await loadImage(href);return {href,width:image.naturalWidth,height:image.naturalHeight};
}
async function png(svg:string):Promise<Blob>{
  const url=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'}));
  try{
    const image=await loadImage(url);const canvas=document.createElement('canvas');
    canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
    if(canvas.width*canvas.height>16_000_000)throw new Error('PNG exceeds pixel limit');
    const context=canvas.getContext('2d');if(!context)throw new Error('Canvas unavailable');
    context.fillStyle='white';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(image,0,0);
    return await new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('PNG failed')),'image/png'));
  }finally{URL.revokeObjectURL(url);}
}
export async function downloadVisual(spec:VisualSpec,svg:SVGElement|SVGElement[]=[],format:'svg'|'png'|'json'='svg',generator:Record<string,unknown>={}){
  const elements=Array.isArray(svg)?svg:[svg];
  const artifact=format==='json'?JSON.stringify(visualManifest(spec,generator),null,2):buildExportSvg(spec,elements,await sourcePixels(spec));
  const blob=format==='png'?await png(artifact):new Blob([artifact],{type:format==='json'?'application/json':'image/svg+xml'});
  const url=URL.createObjectURL(blob);
  try{const a=document.createElement('a');a.href=url;a.download=`aura-${spec.kind}-${spec.id.replace(/[^a-zA-Z0-9_-]/g,'')}.${format}`;a.click();}
  finally{setTimeout(()=>URL.revokeObjectURL(url),0);}
}
