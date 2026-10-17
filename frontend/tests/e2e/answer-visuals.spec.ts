import {expect,test,type Page} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import type {VisualSpec} from '../../src/types';

test.use({launchOptions:{args:['--disable-gpu']}});
const fixtureRoot=resolve('../.local/visual-outputs-20261014/frozen-fixtures-v3');
const rows=readFileSync(resolve(fixtureRoot,'records.jsonl'),'utf8').trim().split('\n').map(line=>JSON.parse(line)) as {id:string;status:string;result:{spec:VisualSpec}}[];
const bank=readFileSync(resolve('../aura_bio_system/benchmarks/data/visual_output_bank_v1.jsonl'),'utf8').trim().split('\n').map(line=>JSON.parse(line));

async function setup(page:Page,row:typeof rows[number],options:{expired?:boolean;malicious?:boolean;sourceText?:string}={}){
  const spec=JSON.parse(JSON.stringify(row.result.spec)) as VisualSpec;
  if(options.malicious&&spec.kind==='diagram')spec.payload.nodes[0].label='" %%{init: {securityLevel:loose}}%% <img src="https://evil.example/x">';
  const pack=spec.sources?.[0].pack_id??'a'.repeat(32);
  const source=bank.find(item=>item.id===row.id);
  const external:string[]=[];let starts=0;
  const answer={markdown:'The selected material supports this response.',citations:(spec.sources??[]).map((reference,n)=>({citation_id:reference.citation_id,source_id:'fixture',source_title:reference.title,source_type:'study material',section:'Fixture',chunk_id:n?'chunk2':'chunk1',excerpt:options.sourceText??source.evidence_text,rank:n+1,license_id:'authored fixture',pack_id:reference.pack_id,document_id:reference.document_id,unit_ids:reference.unit_ids,locators:reference.locators})),confidence:'high',confidence_rationale:'Authored fixture; not a model-accuracy result.',verification_status:'verified',revised:false,limitations:[],latency_ms:10,visuals:[{status:'ready',spec,limitations:[],metadata:{model:'fixture',prompt_version:spec.version===2?'v2-renderer-fixture':'v1'}}]};
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(['blob:','data:'].includes(url.protocol)){await route.continue();return;}
    if(!['127.0.0.1','localhost'].includes(url.hostname)){external.push(url.href);await route.abort();return;}
    if(url.port==='5173'){await route.continue();return;}
    const path=url.pathname;let data:unknown={};
    if(path.endsWith('/health'))data={status:'ready',backend:true,model:true,retrieval:true,index_ready:true};
    else if(path.endsWith('/capabilities'))data={local_models:['fixture'],teaching_modes:[],retrieval_modes:[],external_critic_available:false};
    else if(path==='/api/v1/study-packs')data={packs:[{pack_id:pack,name:'Visual fixture',domain:'general',state:'hybrid-ready',generation:1,retention:'saved'}]};
    else if(path.includes('/assets/')&&spec.kind==='source'){
      if(options.expired){await route.fulfill({status:404,json:{detail:'Source unavailable'}});return;}
      await route.fulfill({contentType:'image/png',body:readFileSync(resolve(fixtureRoot,'packs',spec.payload.pack_id,'assets',spec.payload.document_id,spec.payload.asset_id!))});return;
    }else if(path.includes('/units/')&&spec.kind==='source'){
      if(options.expired){await route.fulfill({status:404,json:{detail:'Source unavailable'}});return;}
      data={unit_id:spec.payload.revision_id,document_id:spec.payload.document_id,ordinal:0,role:'body',title:'Fixture',breadcrumb:'',text:source.evidence_text,locators:spec.payload.locators,asset_ids:[spec.payload.asset_id],provenance:source.provenance,
        provenance_details:{},metadata:source.provenance==='ocr'?{ocr:{words:[{text:'ORION',confidence:95,bbox:[.03,.1,.1,.16]}]}}:{}};
    }else if(path==='/api/v1/runs'&&route.request().method()==='POST'){
      starts++;expect(route.request().postDataJSON().visual_output).toBe(spec.kind);data={run_id:`fixture-${starts}`,status:'queued'};
    }else if(path.endsWith('/events')){
      const delivered=starts>1?{...answer,markdown:'A replacement answer.',visuals:[]}:answer;
      await route.fulfill({contentType:'text/event-stream',body:`data: ${JSON.stringify({type:'answer.completed',answer:delivered})}\n\n`});return;
    }else if(path==='/api/v1/runs')data={runs:[],total:0};
    await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('/ask');await page.getByLabel('Answer from').selectOption(pack!);
  await page.getByLabel('Answer visual').selectOption(spec.kind);
  await page.getByLabel('Ask a biology question').fill('Explain the selected source material.');
  await page.getByRole('button',{name:'Ask AURA',exact:true}).click();
  await expect(page.getByText(answer.markdown,{exact:true})).toBeVisible();
  return {spec,pack,external};
}

for(const row of rows.filter(row=>row.status==='ready')){
  test(`${row.id}: local, source-linked and mobile-readable`,async({page},info)=>{
    const {spec,external}=await setup(page,row);
    const visual=page.getByRole('region',{name:spec.title,exact:true});await expect(visual).toBeVisible();
    if(spec.kind==='diagram'){
      await expect(visual.locator('.visual-diagram > svg')).toBeVisible();
      await expect(visual.locator('.visual-diagram > svg')).not.toContainText('&#');
      const first=visual.locator('[data-visual-node]').first();await expect(first).toHaveAttribute('role','button');
      await first.focus();await page.keyboard.press('Enter');await expect(page.getByRole('dialog')).toBeVisible();
      await page.getByRole('button',{name:'Close evidence'}).click();
      await page.getByLabel('Diagram zoom').fill('2');await expect(visual.locator('.visual-diagram')).toHaveAttribute('style',/200%/);
    }else if(spec.kind==='source')await expect(visual.getByRole('img')).toBeVisible();
    else if(spec.kind==='comparison'||spec.kind==='plot')await expect(visual.getByRole('table')).toBeVisible();
    else if(spec.kind==='procedure')await expect(visual.locator('ol li')).toHaveCount(2);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
    expect(external).toEqual([]);
    await page.screenshot({path:info.outputPath(`${row.id}.png`),fullPage:true});
    await visual.screenshot({path:info.outputPath(`${row.id}-visual.png`),style:'.topbar { visibility: hidden; }'});
  });
}

test('malicious labels remain text; downloads and replacement never publish or retain an old visual',async({page})=>{
  const row=rows.find(row=>row.id==='diagram-interpreted')!;
  const {spec,external}=await setup(page,row,{malicious:true});
  const visual=page.getByRole('region',{name:spec.title,exact:true});await expect(visual.locator('.visual-diagram > svg')).toBeVisible();
  await expect(visual.locator('img,script,foreignObject,a[href^="http"]')).toHaveCount(0);
  for(const kind of ['SVG','PNG','JSON']){
    const download=page.waitForEvent('download');await visual.getByRole('button',{name:`Download ${kind}`}).click();
    const file=await download;expect(await file.failure()).toBeNull();expect(file.suggestedFilename()).toMatch(new RegExp(`\\.${kind.toLowerCase()}$`));
  }
  await page.getByLabel('Ask a biology question').fill('Explain another source-stated detail.');await page.getByRole('button',{name:'Ask AURA',exact:true}).click();
  await expect(page.getByText('A replacement answer.',{exact:true})).toBeVisible();
  await expect(page.getByRole('region',{name:spec.title})).toHaveCount(0);expect(external).toEqual([]);
});

test('expired preview fails visibly; source purge clears visual and practice without a model job',async({page})=>{
  const row=rows.find(row=>row.id==='source-ocr')!;
  const {spec,pack,external}=await setup(page,row,{expired:true});
  await expect(page.getByRole('region',{name:spec.title}).getByRole('alert')).toContainText('Source unavailable');
  await expect(page.getByText('The selected material supports this response.',{exact:true})).toBeVisible();
  await page.evaluate(id=>window.dispatchEvent(new CustomEvent('study-pack-purged',{detail:id})),pack);
  await expect(page.getByRole('region',{name:spec.title})).toHaveCount(0);expect(external).toEqual([]);
});

test('label practice confirms OCR keys, hides them accessibly and clears with its source',async({page})=>{
  const row=rows.find(row=>row.id==='source-ocr')!;
  const {spec,pack,external}=await setup(page,row);
  const visual=page.getByRole('region',{name:spec.title,exact:true});
  await visual.getByRole('button',{name:'Practice labels'}).click();
  await visual.getByLabel('Use label 1').check();
  await visual.getByRole('button',{name:'Start practice'}).click();
  const practice=visual.getByRole('region',{name:'Source label practice'});
  await expect(practice.getByAltText(/numbered covered regions/)).toBeVisible();
  expect(await practice.locator('[alt],[title],[aria-label]').evaluateAll(elements=>elements.some(element=>Array.from(element.attributes).some(attribute=>attribute.value.includes('ORION'))))).toBe(false);
  await practice.getByLabel('Your answer for label 1').fill('orion');
  await practice.getByRole('button',{name:'Check answers'}).click();
  await expect(practice.getByRole('status')).toHaveText('1 of 1 confirmed transcriptions matched.');
  await expect(practice.getByText('ORION',{exact:true})).toHaveCount(0);
  await practice.getByRole('button',{name:'Reveal labels'}).click();await expect(practice.getByText('ORION',{exact:true})).toBeVisible();
  await page.evaluate(id=>window.dispatchEvent(new CustomEvent('study-pack-purged',{detail:id})),pack);
  await expect(practice).toHaveCount(0);expect(external).toEqual([]);
});

test('v2 scientific graph retains inhibition, modality, groups and citation access',async({page},info)=>{
  const row=JSON.parse(JSON.stringify(rows.find(r=>r.id==='diagram-chain')));
  const spec=row.result.spec;
  spec.version=2;spec.payload.orientation='LR';spec.payload.layout='pathway';
  spec.payload.nodes.forEach((n:Record<string,unknown>,i:number)=>{n.role=i===1?'process':'entity';});
  spec.payload.edges.forEach((e:Record<string,unknown>)=>{e.qualifiers=e.relation==='inhibits'?['may']:[];e.conditions=[];e.bindings=[];});
  spec.payload.groups=[{id:'g',label:'Presentation group 1',node_ids:[spec.payload.nodes[0].id],mode:'presentation',claim_ids:[],bindings:[]}];
  const {external}=await setup(page,row);
  const visual=page.getByRole('region',{name:spec.title,exact:true});
  await expect(visual.locator('.visual-diagram > svg')).toBeVisible();
  await expect(visual.locator('path[data-relation="inhibits"]')).toHaveAttribute('marker-end',/inhibition/);
  await expect(visual.locator('path[data-relation="activates"]')).toHaveAttribute('marker-end',/activation/);
  await expect(visual.locator('.visual-diagram')).toContainText('may inhibit');
  await expect(visual.locator('.visual-diagram')).toContainText('layout only');
  await expect(visual.locator('script,foreignObject,a[href]')).toHaveCount(0);
  await visual.locator('[data-visual-node]').first().focus();await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog')).toBeVisible();await page.getByRole('button',{name:'Close evidence'}).click();
  expect(external).toEqual([]);
  await visual.screenshot({path:info.outputPath('v2-scientific-graph.png')});
});

for(const kind of ['bar','line','heatmap','distribution'] as const){
  test(`v2 ${kind} scientific plot retains source data and readable exports`,async({page},info)=>{
    const row=JSON.parse(JSON.stringify(rows.find(r=>r.id==='plot-counts')));
    const spec=row.result.spec;const support=spec.payload.series[0].points[0].support;
    const point=(id:string,group:string,value:string|null,extra:object={})=>({id,group,value,quantity:'count',origin:'source_observation',uncertainty:null,claim_ids:['c1'],bindings:{},support,...extra});
    const identity=(text:string)=>({text,claim_ids:['c1'],bindings:[],support});
    spec.version=2;spec.payload={chart_type:kind,x_label:'Time',y_label:'Count',unit:kind==='heatmap'?'units':'cells',x_unit:'h',x_scale:'linear',y_scale:'linear',series:[]};
    let sourceText='';
    if(kind==='bar'){
      sourceText='Sample A mean: 10 cells. Sample A SD: 2 cells. Sample B mean: 15 cells. Sample B SD: 3 cells.';
      spec.payload.series=[{id:'mean',label:'Source mean',identity:identity('mean'),unit:'cells',points:[point('a','Sample A','10',{quantity:'mean',uncertainty:{kind:'SD',magnitude:'2',bindings:{}}}),point('b','Sample B','15',{quantity:'mean',uncertainty:{kind:'SD',magnitude:'3',bindings:{}}})]}];
    }else if(kind==='line'){
      sourceText='At time 0 h, Culture A: 33 cells. At time 1 h, Culture A: 38 cells. At time 0 h, Culture B: 20 cells. At time 1 h, Culture B: not reported cells.';
      spec.payload.series=[{id:'a',label:'Culture A',identity:identity('Culture A'),unit:'cells',points:[point('a0','Culture A','33',{x:'0'}),point('a1','Culture A','38',{x:'1'})]},
        {id:'b',label:'Culture B',identity:identity('Culture B'),unit:'cells',points:[point('b0','Culture B','20',{x:'0'}),point('b1','Culture B',null,{x:'1'})]}];
    }else if(kind==='heatmap'){
      sourceText='Matrix row Gene A, column Sample A: 2 units. Matrix row Gene A, column Sample B: not reported units. Matrix row Gene B, column Sample A: 5 units. Matrix row Gene B, column Sample B: 8 units.';
      spec.payload.series=[{id:'matrix',label:'Source matrix',identity:identity('Matrix'),unit:'units',points:[point('aa','Gene A','2',{column:'Sample A'}),point('ab','Gene A',null,{column:'Sample B'}),point('ba','Gene B','5',{column:'Sample A'}),point('bb','Gene B','8',{column:'Sample B'})]}];
    }else{
      sourceText='Bin 0-5 micrometres: 2 cells. Bin 5-10 micrometres: 4 cells. Bin 10-15 micrometres: 1 cells.';
      spec.payload.distribution_mode='source_bins';spec.payload.series=[{id:'bins',label:'Source bins',identity:identity('Bin'),unit:'cells',points:[point('d1','0-5 micrometres','2',{bin_lower:'0',bin_upper:'5'}),point('d2','5-10 micrometres','4',{bin_lower:'5',bin_upper:'10'}),point('d3','10-15 micrometres','1',{bin_lower:'10',bin_upper:'15'})]}];
    }
    spec.description=sourceText;
    const {external}=await setup(page,row,{sourceText});const visual=page.getByRole('region',{name:spec.title,exact:true});
    await expect(visual.getByRole('table')).toBeVisible();await expect(visual.locator('svg').first()).toBeVisible();
    if(kind==='bar'){await expect(visual.locator('[data-uncertainty="SD"]')).toHaveCount(2);await expect(visual.getByRole('table')).toContainText('SD 2');}
    if(kind==='heatmap'){await expect(visual.locator('[data-missing="true"]')).toHaveCount(1);await expect(visual.getByRole('table')).toContainText('Not reported');}
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);expect(external).toEqual([]);
    const download=page.waitForEvent('download');await visual.getByRole('button',{name:'Download SVG'}).click();const file=await download;expect(await file.failure()).toBeNull();
    const artwork=readFileSync((await file.path())!,'utf8');expect(artwork).toContain('data-aura-plot="true"');
    expect((artwork.match(/<svg\b/g)??[]).length).toBeGreaterThan(1);
    await visual.screenshot({path:info.outputPath(`v2-${kind}.png`),style:'.topbar { visibility: hidden; }'});
  });
}
