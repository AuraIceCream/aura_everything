import {expect,it} from 'vitest';
import {plotGeometry} from './visual-plot';
import {scientificPlot} from '../components/answer-visuals/fixtures';

it('retains the source SD and uses derived endpoints only as drawing geometry',()=>{
  const spec=scientificPlot();spec.payload.series[0].points[1].uncertainty={kind:'SD',magnitude:'2',bindings:{}};
  const geometry=plotGeometry(spec);
  expect(geometry.yDomain).toEqual([0,40]);
  expect(geometry.series[0].points[1].error).toEqual({kind:'SD',lower:36,upper:40,derived:true});
  expect(spec.payload.series[0].points[1].uncertainty.magnitude).toBe('2');
});

it('retains missing masks, source bins and explicit distribution mode without smoothing',()=>{
  const spec=scientificPlot();spec.payload.chart_type='heatmap';
  spec.payload.series[0].points[0].column='Sample A';spec.payload.series[0].points[0].value='0';
  spec.payload.series[0].points[1].column='Sample B';spec.payload.series[0].points[1].value=null;
  const geometry=plotGeometry(spec);
  expect(geometry.series[0].points[0].y).toBe(0);expect(geometry.series[0].points[1].y).toBeNull();
  expect(geometry.connectNulls).toBe(false);
});

it('never joins different entities, accepts nonpositive log values or mismatched units',()=>{
  const spec=scientificPlot();spec.payload.chart_type='line';spec.payload.series[0].points.forEach((p,i)=>{p.x=String(i);});
  expect(()=>plotGeometry(spec)).toThrow(/trajectory/i);
  spec.payload.chart_type='bar';spec.payload.y_scale='log';expect(()=>plotGeometry(spec)).toThrow();
  spec.payload.y_scale='linear';spec.payload.series[0].unit='mg';expect(()=>plotGeometry(spec)).toThrow();
});

it('keeps repeated-group individual samples at distinct observation positions',()=>{
  const spec=scientificPlot();spec.payload.chart_type='distribution';spec.payload.distribution_mode='samples';
  spec.payload.series[0].points.forEach(p=>{p.group='Culture A';});
  const geometry=plotGeometry(spec);
  expect(geometry.groups).toHaveLength(2);
});

it('puts retained conditions in categorical drawing labels',()=>{
  const spec=scientificPlot();spec.payload.series[0].points[0].condition='Without oxygen';
  expect(plotGeometry(spec).groups[0]).toContain('Without oxygen');
});
