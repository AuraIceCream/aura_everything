import type {PlotVisualV2} from '../../types';
import type {PlotGeometry} from '../../lib/visual-plot';
import {observationLabel} from '../../lib/visual-plot';

export function HeatmapVisual({spec,geometry,onCitation}:{spec:PlotVisualV2;geometry:PlotGeometry;onCitation:(id:string)=>void}){
  const points=spec.payload.series.flatMap(s=>s.points);
  const values=points.flatMap(p=>p.value===null?[]:[Number(p.value)]);const min=Math.min(...values),max=Math.max(...values);
  const width=220+geometry.columns.length*140,height=130+geometry.groups.length*58;
  return <svg data-aura-plot="true" viewBox={`0 0 ${width} ${height}`} style={{minWidth:width,width:'100%'}} role="img" aria-label="Source matrix; missing values are not zero">
    {geometry.columns.map((column,i)=><text key={column} x={210+i*140} y={24} textAnchor="middle" fontSize="13">{column}</text>)}
    {geometry.groups.map((row,r)=><g key={row}><text x={8} y={64+r*58} fontSize="13">{row}</text>
      {geometry.columns.map((column,c)=>{
        const p=points.find(p=>observationLabel(p)===row&&p.column===column);const missing=!p||p.value===null;
        const t=missing?0:max===min?.6:(Number(p.value)-min)/(max-min);
        const fill=missing?'#edf0ef':`rgb(${Math.round(225-202*t)},${Math.round(243-136*t)},${Math.round(236-145*t)})`;
        const label=!p?'Not supplied':p.value===null?'Not reported':p.value;
        return <g key={column} data-missing={missing?'true':undefined} data-source-value={p?.value??undefined}>
          <rect x={146+c*140} y={38+r*58} width={128} height={48} fill={fill} stroke={missing?'#89958f':'#fff'} strokeDasharray={missing?'4 3':undefined}/>
          <text x={210+c*140} y={66+r*58} textAnchor="middle" fontSize="13" fill={!missing&&t>.6?'white':'#18201f'}>{label}</text>
          {p&&<title>{row}; {column}: {label} {spec.payload.unit}; {p.support.cite_ids.join(', ')}</title>}
          {p&&<rect x={146+c*140} y={38+r*58} width={128} height={48} fill="transparent" tabIndex={0} role="button" aria-label={`${row}; ${column}: ${label}; open source`} onClick={()=>onCitation(p.support.cite_ids[0])} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onCitation(p.support.cite_ids[0]);}}}/>}
        </g>;
      })}</g>)}
    <text x={146} y={height-24} fontSize="13">Color scale: {values.length?`${min} (light) to ${max} (dark) ${spec.payload.unit}`:'no measured values'} · dashed: missing</text>
  </svg>;
}
