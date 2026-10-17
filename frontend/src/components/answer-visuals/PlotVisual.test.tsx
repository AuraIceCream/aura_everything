import {render,screen} from '@testing-library/react';
import {expect,it} from 'vitest';
import {PlotVisual,plotGeometry} from './PlotVisual';
import {plot} from './fixtures';
it('uses a zero bar baseline and exposes exact original values, units and sources',()=>{
  expect(plotGeometry(plot).yDomain).toEqual([0,38]);
  render(<PlotVisual spec={plot} onCitation={()=>{}}/>);
  expect(screen.getByRole('table')).toHaveTextContent('Group A33cells');
  expect(screen.getByRole('table')).toHaveTextContent('Group B38cells');
  expect(screen.getAllByRole('button',{name:'Open cit-1'})).toHaveLength(2);
});
it('does not bridge missing observations or join scatter points',()=>{
  const line={...plot,payload:{...plot.payload,chart_type:'line' as const,series:[{...plot.payload.series[0],points:[{...plot.payload.series[0].points[0],x:'0'},{...plot.payload.series[0].points[1],x:'1',value:null}]}]}};
  expect(plotGeometry(line).connectNulls).toBe(false);
  expect(plotGeometry({...line,payload:{...line.payload,chart_type:'scatter'}}).joinScatter).toBe(false);
});
it('rejects nonfinite conversions, incompatible units and unordered line x',()=>{
  const bad={...plot,payload:{...plot.payload,series:[{...plot.payload.series[0],unit:'mg'}]}};
  expect(()=>plotGeometry(bad)).toThrow();
  expect(()=>plotGeometry({...plot,payload:{...plot.payload,series:[{...plot.payload.series[0],points:[{...plot.payload.series[0].points[0],value:'1e999'}]}]}})).toThrow();
  const points=plot.payload.series[0].points.map((p,i)=>({...p,x:String(1-i)}));
  expect(()=>plotGeometry({...plot,payload:{...plot.payload,chart_type:'line',series:[{...plot.payload.series[0],points}]}})).toThrow();
});
