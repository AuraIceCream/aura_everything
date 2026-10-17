import {expect,it,vi,afterEach} from 'vitest';
import {needsVisualQuestion,prepareDocumentQuestion} from './prepare-document-question';
import {api} from './api';

afterEach(()=>vi.restoreAllMocks());

it('prepares plural and panel-qualified figure references as well as images',()=>{
  for(const question of ['Compare Figs. 5 and 6','Explain Figure 5a','Explain figure S5(b)','Read Table 12','What is this image?']){
    expect(needsVisualQuestion(question),question).toBe(true);
  }
  expect(needsVisualQuestion('Define mitosis')).toBe(false);
});

it('Ask explicitly starts one local v2 focused job and waits for its index',async()=>{
  const controller=new AbortController();
  vi.spyOn(api.studyPacks,'resolveVisualQuestion').mockResolvedValue({figures:[{figure_id:'f'}] as never,warnings:[]});
  const start=vi.spyOn(api.studyPacks,'visualStart').mockResolvedValue({job_id:'j'} as never);
  vi.spyOn(api.studyPacks,'visualStatus').mockResolvedValue({state:'completed',indexed:true,checkpoints:[]} as never);
  const ids=await prepareDocumentQuestion('p','Explain Fig. 5',false,controller.signal,()=>{});
  expect(ids).toEqual(['f']);expect(start).toHaveBeenCalledTimes(1);
  expect(start.mock.calls[0][2]).toMatchObject({provider:'ollama',description_version:2,focus:true,question:'Explain Fig. 5'});
  expect(start.mock.calls[0][2]).not.toHaveProperty('consent');
});

it('abort during resolution never starts processing or returns late image IDs',async()=>{
  const controller=new AbortController();
  vi.spyOn(api.studyPacks,'resolveVisualQuestion').mockImplementation(async()=>{
    controller.abort();return {figures:[{figure_id:'late'}] as never,warnings:[]};
  });
  const start=vi.spyOn(api.studyPacks,'visualStart');
  await expect(prepareDocumentQuestion('p','Explain image',false,controller.signal,()=>{})).rejects.toHaveProperty('name','AbortError');
  expect(start).not.toHaveBeenCalled();
});
