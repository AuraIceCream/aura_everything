import {Bar,BarChart,CartesianGrid,Line,LineChart,ResponsiveContainer,Scatter,ScatterChart,Tooltip,XAxis,YAxis} from 'recharts';
import type {PlotVisualSpec} from '../../types';
import {CitationButtons,SupportBadge} from './common';
import {plotGeometry} from '../../lib/visual-plot';
import {ScientificPlot} from './ScientificPlot';
export {plotGeometry} from '../../lib/visual-plot';

export function PlotVisual({spec,onCitation}:{spec:PlotVisualSpec;onCitation:(id:string)=>void}){
  if(spec.version===2)return <ScientificPlot spec={spec} onCitation={onCitation}/>;
  let geometry:ReturnType<typeof plotGeometry>;
  try{geometry=plotGeometry(spec);}catch{return <p role="status">Plot unavailable: source data or units cannot be displayed safely. Read the text answer.</p>;}
  const p=spec.payload;
  return <section aria-label="Source-stated data plot">
    {geometry.series.map(series=><figure key={series.id}><figcaption>{series.label} · {series.unit}</figcaption>
      <div className="visual-chart"><ResponsiveContainer width="100%" height={280} minWidth={0} initialDimension={{width:640,height:280}}>
        {p.chart_type==='bar'?<BarChart data={series.points} accessibilityLayer margin={{top:12,right:24,bottom:32,left:12}}>
          <CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="group"/><YAxis domain={geometry.yDomain} label={{value:p.unit,angle:-90,position:'insideLeft'}}/><Tooltip/>
          <Bar dataKey="y" name={series.unit} fill="#176b5b" isAnimationActive={false}/>
        </BarChart>:p.chart_type==='line'?<LineChart data={series.points} accessibilityLayer margin={{top:12,right:24,bottom:32,left:12}}>
          <CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="x" type="number" domain={['dataMin','dataMax']} label={{value:`${p.x_label}${p.x_unit?' ('+p.x_unit+')':''}`,position:'insideBottom',offset:-12}}/><YAxis label={{value:p.unit,angle:-90,position:'insideLeft'}}/><Tooltip/>
          <Line dataKey="y" name={series.unit} type="linear" connectNulls={false} stroke="#176b5b" isAnimationActive={false}/>
        </LineChart>:<ScatterChart accessibilityLayer margin={{top:12,right:24,bottom:32,left:12}}>
          <CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="x" type="number" name={p.x_label} unit={p.x_unit}/><YAxis dataKey="y" type="number" name={p.y_label} unit={p.unit}/><Tooltip/>
          <Scatter data={series.points.filter(point=>point.y!==null)} name={series.label} fill="#176b5b" line={false} isAnimationActive={false}/>
        </ScatterChart>}
      </ResponsiveContainer></div>
    </figure>)}
    <div className="visual-scroll"><table className="visual-data"><caption>Original source data · no interpolation or unit conversion</caption><thead><tr><th scope="col">Group</th>{p.chart_type!=='bar'&&<th scope="col">{p.x_label}{p.x_unit?` (${p.x_unit})`:''}</th>}<th scope="col">Value</th><th scope="col">Unit</th><th scope="col">Source</th></tr></thead><tbody>
      {p.series.flatMap(series=>series.points.map((point,n)=><tr key={`${series.id}-${n}`}><th scope="row">{point.group}</th>{p.chart_type!=='bar'&&<td>{point.x}</td>}<td>{point.value??'Not reported'}</td><td>{series.unit}</td><td><SupportBadge support={point.support}/><CitationButtons support={point.support} onCitation={onCitation}/></td></tr>))}
    </tbody></table></div>
  </section>;
}
