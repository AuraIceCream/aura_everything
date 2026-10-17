import type {DiagramVisualV1,SourceVisualV1,VisualSupport,PlotVisualV1,PlotVisualV2} from '../../types';
export const support:VisualSupport={claim_ids:['c1'],cite_ids:['cit-1'],status:'native_verified',provenance:['native_text']};
export const diagram:DiagramVisualV1={version:1,id:'fixture',kind:'diagram',title:'Source-grounded diagram',description:'ORION activates VEGA.',payload:{nodes:[{id:'orion',label:'ORION',claim_ids:['c1'],support},{id:'vega',label:'VEGA',claim_ids:['c1'],support}],edges:[{from_id:'orion',to_id:'vega',relation:'activates',label:'activates',claim_ids:['c1'],support}]}};
export const source:SourceVisualV1={version:1,id:'source',kind:'source',title:'Source view',description:'ORION activates VEGA.',payload:{claim_ids:['c1'],pack_id:'a'.repeat(32),document_id:'b'.repeat(32),unit_id:'d'.repeat(32),asset_id:'e'.repeat(32),bbox:{x0:.1,y0:.2,x1:.8,y1:.9},support,revision_id:'d'.repeat(32),source_checksum:'hash',asset_checksum:'asset-hash',generation:1,locators:[{kind:'pdf',page:2}],coordinates:'upright_normalized',highlight_precision:'region',resolved:true}};
export const plot:PlotVisualV1={version:1,id:'plot',kind:'plot',title:'Source-stated data',description:'Group A: 33 cells; Group B: 38 cells.',payload:{chart_type:'bar',x_label:'Group',y_label:'Count',unit:'cells',series:[{id:'counts',label:'Cell counts',unit:'cells',points:[{group:'Group A',value:'33',claim_ids:['c1'],bindings:{},support},{group:'Group B',value:'38',claim_ids:['c2'],bindings:{},support}]}]}};
export function scientificPlot():PlotVisualV2{
  return {...plot,version:2,payload:{...plot.payload,x_scale:'linear',y_scale:'linear',series:plot.payload.series.map(s=>({...s,
    identity:{text:'Cell counts',claim_ids:['c1'],bindings:[],support:s.points[0].support},
    points:s.points.map((p,i)=>({...p,id:`o${i}`,quantity:'count',origin:'source_observation' as const,uncertainty:null}))}))}};
}
