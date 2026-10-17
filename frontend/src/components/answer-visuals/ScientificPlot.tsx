import type {PlotVisualV2,VisualPointV2} from '../../types';
import {plotGeometry,uncertaintyLabel,observationLabel} from '../../lib/visual-plot';
import {CitationButtons,SupportBadge} from './common';
import {HeatmapVisual} from './HeatmapVisual';
import {DistributionVisual} from './DistributionVisual';

function words(label:string){const lines:string[]=[];let line='';for(const word of label.split(/\s+/)){if(line.length+word.length>18){if(line)lines.push(line);line='';}for(let n=0;n<word.length;n+=18){if(n)lines.push(line);line=(line?line+' ':'')+word.slice(n,n+18);}}if(line)lines.push(line);return lines;}
export function ScientificPlot({spec,onCitation}:{spec:PlotVisualV2;onCitation:(id:string)=>void}){
  let g:ReturnType<typeof plotGeometry>;
  try{g=plotGeometry(spec);}catch{return <p role="status">Plot unavailable: source observations, units or scale cannot be drawn safely.</p>;}
  const p=spec.payload;const categorical=p.chart_type==='bar'||p.chart_type==='distribution';
  const width=Math.max(900,categorical?g.groups.length*100+150:900),plotHeight=300;
  const bottom=categorical?Math.max(90,...g.groups.map(label=>words(label).length*16+40)):70,height=plotHeight+bottom+65;
  const yTransform=(v:number)=>g.yScale==='log'?Math.log10(v):v;
  const yMin=yTransform(g.yDomain[0]),yMax=yTransform(g.yDomain[1]);
  const y=(v:number)=>35+plotHeight-(yTransform(v)-yMin)/(yMax-yMin||1)*plotHeight;
  const xTransform=(v:number)=>g.xScale==='log'?Math.log10(v):v;
  const xmin=xTransform(g.xDomain[0]),xmax=xTransform(g.xDomain[1]);
  const slot=(width-160)/(g.groups.length||1);
  const x=(point:{group:string;category?:string;x?:number},s:number)=>categorical?110+g.groups.indexOf(point.category??point.group)*slot+slot/2+(s-(g.series.length-1)/2)*Math.min(30,slot/(g.series.length+1)):
    90+(xTransform(point.x!)-xmin)/(xmax-xmin||1)*(width-150);
  return <section aria-label="Source-stated scientific plot">
    <div className="visual-toolbar">{g.series.map(s=><span key={s.id}><span aria-hidden="true" style={{color:s.color}}>● </span>{s.label} · {s.unit}</span>)}</div>
    {p.chart_type==='distribution'&&<DistributionVisual spec={spec}/>}
    <div className="visual-scroll">
      {p.chart_type==='heatmap'?<HeatmapVisual spec={spec} geometry={g} onCitation={onCitation}/>:<svg data-aura-plot="true" viewBox={`0 0 ${width} ${height}`} style={{minWidth:Math.min(width,900),width:'100%'}} role="img" aria-label={`${p.chart_type} plot of source observations; ${p.unit}`}>
        <text x={20} y={20} fontSize="14">{p.unit}{p.y_scale==='log'?' · logarithmic scale':''}</text>
        {[0,.25,.5,.75,1].map(t=>{const value=g.yScale==='log'?10**(yMin+(yMax-yMin)*t):g.yDomain[0]+(g.yDomain[1]-g.yDomain[0])*t;const yy=y(value);return <g key={t}><line x1={85} x2={width-35} y1={yy} y2={yy} stroke="#dce5e0"/><text x={76} y={yy+4} textAnchor="end" fontSize="12">{Number(value.toPrecision(4))}</text></g>;})}
        {g.series.map((series,s)=><g key={series.id}>
          {p.chart_type==='line'&&series.points.map((point,n)=>{const before=series.points[n-1];return point.y!==null&&before?.y!==null&&before?<line key={`edge-${n}`} x1={x(before,s)} y1={y(before.y)} x2={x(point,s)} y2={y(point.y)} stroke={series.color} strokeWidth="2.5"/>:null;})}
          {series.points.map((point,n)=>{
            const xx=x(point,s),yy=point.y===null?y(g.yDomain[0]):y(point.y);
            const source=spec.payload.series[s].points[n];const cite=point.support.cite_ids[0];
            return <g key={source.id} tabIndex={0} role="button" aria-label={`${point.group}: ${point.value??'Not reported'} ${series.unit}; ${uncertaintyLabel(source)}; open source`} onClick={()=>onCitation(cite)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onCitation(cite);}}}>
              <title>{point.group}: {point.value??'Not reported'} {series.unit}; {uncertaintyLabel(source)}; {point.support.cite_ids.join(', ')}</title>
              {point.y===null?<text x={xx} y={yy-10} textAnchor="middle" fontSize="11">Missing</text>:categorical&&!(p.chart_type==='distribution'&&p.distribution_mode==='samples')?<rect x={xx-12} y={Math.min(y(0),yy)} width={24} height={Math.max(1,Math.abs(y(0)-yy))} fill={series.color}/>:<circle data-source-observation={source.id} cx={xx} cy={yy} r={5} fill={series.color}/>}
              {point.error&&<g data-uncertainty={point.error.kind} stroke={series.color} strokeWidth="2"><line x1={xx} x2={xx} y1={y(point.error.lower)} y2={y(point.error.upper)}/>{[point.error.lower,point.error.upper].map((v,i)=><line key={i} x1={xx-7} x2={xx+7} y1={y(v)} y2={y(v)}/>)}</g>}
              {point.y!==null&&categorical&&<text x={xx} y={Math.min(yy,y(point.error?.upper??point.y))-8} textAnchor="middle" fontSize="12">{point.value}</text>}
              {!categorical&&<text x={xx} y={plotHeight+57} textAnchor="middle" fontSize="12">{point.x}</text>}
            </g>;
          })}
        </g>)}
        {categorical&&g.groups.map((group,i)=><text key={group} x={110+i*slot+slot/2} y={plotHeight+65} textAnchor="middle" fontSize="12">{words(group).map((line,n)=><tspan key={n} x={110+i*slot+slot/2} dy={n?16:0}>{line}</tspan>)}</text>)}
        <text x={width/2} y={height-14} textAnchor="middle" fontSize="13">{categorical?'Source groups / bins':`${p.x_label}${p.x_unit?' ('+p.x_unit+')':''}${p.x_scale==='log'?' · logarithmic scale':''}`}</text>
      </svg>}
    </div>
    <p className="visual-caption">Native source observations only. SD/SEM endpoints are derived drawing geometry, not observed bounds or confidence intervals. Lines never bridge missing values.</p>
    <div className="visual-scroll"><table className="visual-data"><caption>Exact original source data · units and uncertainty definitions preserved</caption><thead><tr><th>Series</th><th>Group / row</th>{p.chart_type==='heatmap'&&<th>Column</th>}<th>x</th><th>Value</th><th>Unit</th><th>Uncertainty</th><th>Source</th></tr></thead><tbody>
      {p.series.flatMap(s=>s.points.map((point:VisualPointV2)=><tr key={point.id}><td>{s.label}</td><th scope="row">{observationLabel(point)}</th>{p.chart_type==='heatmap'&&<td>{point.column}</td>}<td>{point.x??'—'} {point.x?p.x_unit:''}</td><td>{point.value??'Not reported'}</td><td>{s.unit}</td><td>{uncertaintyLabel(point)}</td><td><SupportBadge support={point.support}/><CitationButtons support={point.support} onCitation={onCitation}/></td></tr>))}
    </tbody></table></div>
  </section>;
}
