import {expect,test} from '@playwright/test';

test.use({launchOptions:{args:['--disable-gpu']}});
test('one explicit Ask processes an authored image and answers privately without layout overflow',async({page},info)=>{
  const pack='a'.repeat(32),doc='b'.repeat(32),figure='c'.repeat(32),asset='d'.repeat(32);
  const pixels=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8ZkAAAAASUVORK5CYII=','base64');
  let visualStarts=0,answerStarts=0;
  const image={attachment_id:pack,pack:{pack_id:pack,name:'Synthetic image',domain:'general',state:'sparse-ready',generation:1,retention:'temporary',expires_at:Date.now()/1000+3600},document:{document_id:doc,pack_id:pack,filename:'synthetic.png',kind:'png',state:'extracted'},job:{job_id:'extract',state:'sparse-ready'},visual_jobs:[],processing:false,usable:true,preview_asset_id:asset};
  const answer={markdown:'The image is interpreted, not verified.',confidence:'low',confidence_rationale:'Authored fake-provider fixture, not an accuracy result.',verification_status:'interpreted',revised:false,limitations:['Pixel-derived numbers are not verified.'],latency_ms:1000,citations:[]};
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.hostname!=='127.0.0.1'&&url.hostname!=='localhost'){await route.abort();return;}
    if(url.port==='5173'){await route.continue();return;}
    const path=url.pathname;let data:unknown={};
    if(path.endsWith('/health'))data={status:'ready',backend:true,model:true,retrieval:true,index_ready:true};
    else if(path.endsWith('/capabilities'))data={local_models:['fake-test'],teaching_modes:[],retrieval_modes:[],external_critic_available:false};
    else if(path==='/api/v1/study-packs')data={packs:[]};
    else if(path.includes('/assets/')||path.endsWith('/original')||path.endsWith('/preview')){await route.fulfill({contentType:'image/png',body:pixels});return;}
    else if(path.includes('study-attachments'))data=image;
    else if(path.endsWith('/figures'))data={figures:[{figure_id:figure,document_id:doc,unit_id:'unit',asset_id:asset,locator:{kind:'image'},bbox:{x0:0,y0:0,x1:1,y1:1},frame:'asset_normalized',reason:'source_image'}],external_allowed:false};
    else if(path.endsWith('/visual-jobs')&&route.request().method()==='POST'){
      visualStarts++;expect(route.request().postDataJSON().config.question).toBe('What does this arrow mean?');data={job_id:'visual',pack_id:pack,state:'queued'};
    }else if(path.endsWith('/visual-jobs/visual'))data={job_id:'visual',pack_id:pack,state:'completed',config:{provider:'ollama',model:'qwen3.5:4b'},checkpoints:[],tokens_used:0};
    else if(path.endsWith('/visual-jobs'))data={jobs:[]};
    else if(path==='/api/v1/runs'&&route.request().method()==='POST'){
      answerStarts++;const request=route.request().postDataJSON();expect(request.attachment_id).toBe(pack);expect(request.evidence_scope).toBe('pack_only');expect(request.allow_external_critic).toBe(false);data={run_id:'fake-image-run',status:'queued'};
    }else if(path.endsWith('/events')){await route.fulfill({contentType:'text/event-stream',body:`data: ${JSON.stringify({type:'answer.completed',answer})}\n\n`});return;}
    else if(path==='/api/v1/runs')data={runs:[],total:0};
    await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('/ask');
  await page.getByLabel('Attach PNG or JPEG').setInputFiles({name:'synthetic.png',mimeType:'image/png',buffer:pixels});
  await expect(page.getByAltText(/Original question image/)).toBeVisible();
  expect(visualStarts).toBe(0);expect(answerStarts).toBe(0);
  await page.getByLabel('Ask a biology question').fill('What does this arrow mean?');
  await page.getByRole('button',{name:'Ask AURA',exact:true}).click();
  await expect(page.getByText('The image is interpreted, not verified.',{exact:true})).toBeVisible();
  expect(visualStarts).toBe(1);expect(answerStarts).toBe(1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  expect(await page.evaluate(()=>Object.values(localStorage).join(' ').includes('What does this arrow mean?'))).toBe(false);
  await page.screenshot({path:info.outputPath('ask-image.png'),fullPage:true});
});
