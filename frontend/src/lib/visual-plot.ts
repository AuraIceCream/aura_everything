import type {PlotVisualSpec,VisualPointV2} from '../types';

export const plotColors=['#176b5b','#496eb4','#a56236'];
export function observationLabel(point:{group:string;condition?:string;population?:string}){
  return [point.group,point.condition,point.population].filter(Boolean).join(' · ');
}
export function plotGeometry(spec:PlotVisualSpec){
  const payload=spec.payload;const values:number[]=[];const xs:number[]=[];
  const v2=spec.version===2?spec.payload:undefined;
  if(payload.series.length>3||payload.series.reduce((n,s)=>n+s.points.length,0)>100)throw new Error('Plot exceeds bounds');
  const series=payload.series.map((series,i)=>{
    if(series.unit!==payload.unit)throw new Error('Incompatible units');
    let previous=-Infinity;let trajectory='';
    const points=series.points.map((point,n)=>{
      const y=point.value===null?null:Number(point.value);const x=point.x===undefined?undefined:Number(point.x);
      if(y!==null&&!Number.isFinite(y)||x!==undefined&&!Number.isFinite(x))throw new Error('Nonfinite plot conversion');
      if(['line','scatter'].includes(payload.chart_type)&&x===undefined)throw new Error('Missing numeric x');
      if(payload.chart_type==='line'&&x!==undefined&&x<=previous)throw new Error('Unordered line observations');
      const detail=spec.version===2?point as VisualPointV2:undefined;
      if(detail){
        if(detail.origin!=='source_observation'||detail.support.status!=='native_verified'||detail.support.provenance.some(p=>p!=='native_text'))throw new Error('Unverified observation');
        if(payload.chart_type==='line'){
          const identity=spec.version===2?spec.payload.series[i].identity.text:'';
          const key=JSON.stringify([detail.group,detail.population,detail.condition,detail.quantity]);
          if(detail.group!==identity||trajectory&&trajectory!==key)throw new Error('Cross-entity trajectory');trajectory=key;
        }
      }
      let error:{kind:string;lower:number;upper:number;derived:boolean}|undefined;
      if(detail?.uncertainty){
        if(y===null)throw new Error('Missing source center');const u=detail.uncertainty;
        if('magnitude' in u){const delta=Number(u.magnitude);if(!Number.isFinite(delta)||delta<0)throw new Error('Invalid source uncertainty');error={kind:u.kind,lower:y-delta,upper:y+delta,derived:true};}
        else error={kind:u.kind,lower:Number(u.lower),upper:Number(u.upper),derived:false};
        if(!Number.isFinite(error.lower)||!Number.isFinite(error.upper)||error.lower>y||error.upper<y)throw new Error('Invalid source interval');
        values.push(error.lower,error.upper);
      }
      if(v2?.x_scale==='log'&&x!==undefined&&x<=0||v2?.y_scale==='log'&&y!==null&&(y<=0||error&&error.lower<=0))throw new Error('Nonpositive log value');
      previous=x??previous;if(y!==null)values.push(y);if(x!==undefined)xs.push(x);
      const category=observationLabel(detail??point)+(v2?.chart_type==='distribution'&&v2.distribution_mode==='samples'?` · observation ${n+1}`:'');
      return {...point,...(detail??{}),x,y,error,category};
    });
    return {...series,color:plotColors[i],points};
  });
  const groups=[...new Set(series.flatMap(s=>s.points.map(p=>p.category)))];
  const columns=[...new Set(spec.version===2?spec.payload.series.flatMap(s=>s.points.map(p=>p.column).filter((c):c is string=>!!c)):[])];
  if(v2?.chart_type==='heatmap'&&(groups.length*columns.length>100||!columns.length))throw new Error('Heatmap exceeds bounded grid');
  if(v2?.chart_type==='distribution'&&!v2.distribution_mode)throw new Error('Missing source distribution mode');
  if(v2&&['bar','distribution','heatmap'].includes(v2.chart_type)&&v2.y_scale==='log')throw new Error('Categorical/bar views need a linear scale');
  const low=values.length?Math.min(...values):0;const high=values.length?Math.max(...values):1;
  return {series,groups,columns,yDomain:(v2?.y_scale==='log'?[low,high]:[Math.min(0,low),Math.max(0,high)||1]) as [number,number],
    xDomain:[xs.length?Math.min(...xs):0,xs.length?Math.max(...xs):1] as [number,number],
    connectNulls:false,joinScatter:false,xScale:v2?.x_scale??'linear',yScale:v2?.y_scale??'linear'};
}
export type PlotGeometry=ReturnType<typeof plotGeometry>;

export function uncertaintyLabel(point:VisualPointV2){
  const u=point.uncertainty;if(!u)return 'None supplied';
  return 'magnitude' in u?`${u.kind} ${u.magnitude}`:`${u.level?u.level+' ':''}${u.kind} ${u.lower} to ${u.upper}`;
}
