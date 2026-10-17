import {expect,it,vi} from 'vitest';
import {buildExportSvg,visualManifest,downloadVisual} from './export';
import {diagram,support} from './fixtures';
import type {ComparisonVisualSpec,ProcedureVisualSpec,VisualSupport} from '../../types';
import {scientificPlot} from './fixtures';

it('exports the supplied SD rather than presenting drawing endpoints as observed CI',()=>{
  const spec=scientificPlot();spec.payload.series[0].points[0].uncertainty={kind:'SD',magnitude:'2',bindings:{}};
  const svg=buildExportSvg(spec);
  expect(svg).toContain('SD 2');expect(svg).not.toContain('CI 31');
  expect(visualManifest(spec).visual.payload).toEqual(spec.payload);
});
const interpreted:VisualSupport={...support,status:'interpreted',provenance:['vlm']};
const procedure:ProcedureVisualSpec={version:1,id:'steps',kind:'procedure',title:'Procedure',description:'',payload:{ordering:'partial',precedes:[],steps:[{id:'a',text:'ORION',claim_ids:['c1'],support},{id:'b',text:'VEGA',claim_ids:['c1'],support}]}};
const bound={claim_ids:['c1'],bindings:[],support};
const comparison:ComparisonVisualSpec={version:1,id:'table',kind:'comparison',title:'Table',description:'',payload:{columns:[{id:'a',text:'Group A',...bound},{id:'b',text:'Group B',...bound}],rows:[{id:'count',criterion:{text:'cells',...bound},cells:[{column_id:'a',text:'33 cells',status:'stated',...bound},{column_id:'b',text:'38 cells',status:'stated',...bound}]}]}};

function svg(text='<text>ORION</text>'){
  return new DOMParser().parseFromString(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">${text}</svg>`,'image/svg+xml').documentElement as unknown as SVGElement;
}
it('embeds visible title, original source references and provenance in exported artwork',()=>{
  const output=buildExportSvg(diagram,[svg()]);
  expect(new DOMParser().parseFromString(output,'image/svg+xml').querySelector('parsererror')).toBeNull();
  expect(output).toContain('Source-grounded diagram');expect(output).toContain('cit-1');
  expect(output).toContain('Solid: source-checked');expect(output).toContain('Interpreted: dashed');
  const manifest=visualManifest(diagram,{model:'fixture',prompt_version:'v1'});
  expect(manifest.claim_ids).toEqual(['c1']);expect(manifest.citation_ids).toEqual(['cit-1']);
  expect(manifest.generator).toEqual({model:'fixture',prompt_version:'v1'});
});
it('rejects unsafe SVG even when export is requested explicitly',()=>{
  expect(()=>buildExportSvg(diagram,[svg('<script>alert(1)</script>')])).toThrow();
});
it('keeps per-step and per-cell support and citation labels in SVG artwork',()=>{
  const steps=structuredClone(procedure);steps.payload.steps[1].support={...interpreted,cite_ids:['cit-2']};
  const artwork=buildExportSvg(steps);
  expect(artwork).toContain('VEGA [Interpreted; cit-2]');
  expect(artwork).toContain('ORION [Source-checked; cit-1]');
  const table=structuredClone(comparison);table.payload.rows[0].cells[1].support={...interpreted,cite_ids:['cit-2']};
  expect(buildExportSvg(table)).toContain('38 cells [Interpreted; cit-2]');
});
it('exports and revokes local blobs without publishing a link',async()=>{
  const create=vi.fn(()=> 'blob:local-only');const revoke=vi.fn();
  vi.stubGlobal('URL',class extends URL {static createObjectURL=create;static revokeObjectURL=revoke;});
  vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
  vi.useFakeTimers();
  try{await downloadVisual(diagram,[svg()],'svg');await vi.runAllTimersAsync();
    expect(create).toHaveBeenCalledTimes(1);expect(revoke).toHaveBeenCalledWith('blob:local-only');
  }finally{vi.useRealTimers();vi.unstubAllGlobals();vi.restoreAllMocks();}
});
