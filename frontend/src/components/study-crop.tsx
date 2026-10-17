import { useState } from 'react';
import type { NormalizedBox } from '../types';

export function RegionImage({sourceUrl,bbox,highlights=[],alt,onError}:{sourceUrl:string;bbox?:NormalizedBox;highlights?:{id:string;bbox:NormalizedBox}[];alt:string;onError?:()=>void}) {
  const boxes=highlights.length?highlights:(bbox?[{id:'source',bbox}]:[]);
  return <div className="figure-source"><img src={sourceUrl} alt={alt} crossOrigin="anonymous" onError={onError} />{boxes.map(({id,bbox:b})=><span key={id} className="figure-region" aria-label={id==='source'?'Selected upright source region':`Selected upright source region ${id}`} style={{left:`${b.x0*100}%`,top:`${b.y0*100}%`,width:`${(b.x1-b.x0)*100}%`,height:`${(b.y1-b.y0)*100}%`}} />)}</div>;
}

export function StudyCrop({sourceUrl,initial,onSave}:{sourceUrl:string;initial:NormalizedBox;onSave:(box:NormalizedBox)=>void}) {
  const [box,setBox]=useState(initial);
  const valid=Object.values(box).every(Number.isFinite) && box.x0>=0 && box.y0>=0 && box.x1<=1 && box.y1<=1 && box.x0<box.x1 && box.y0<box.y1;
  return <section className="study-crop" aria-label="Manual upright source crop">
    <p>Crop the upright page or embedded image (not a full PPTX slide). Values run from 0 to 1; keep panels and legends.</p>
    <RegionImage sourceUrl={sourceUrl} bbox={valid?box:undefined} alt="Upright source for manual crop" />
    <div className="study-toolbar">{([['x0','Left'],['y0','Top'],['x1','Right'],['y1','Bottom']] as const).map(([key,label])=><label key={key}>{label}<input type="number" min="0" max="1" step="0.01" value={Number.isNaN(box[key])?'':box[key]} onChange={e=>setBox({...box,[key]:e.target.valueAsNumber})} /></label>)}</div>
    {!valid && <p role="alert">Use a nonempty crop inside the image.</p>}
    <button disabled={!valid} onClick={()=>onSave(box)}>Save crop</button>
  </section>;
}
