import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {createRef} from 'react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {beforeEach,expect,it,vi} from 'vitest';
import {AskImage,type AskImageHandle} from './ask-image';
import {api} from '../lib/api';
import type {ImageAttachment} from '../types';
vi.mock('../lib/api',()=>({ApiError:class extends Error{},api:{attachments:{upload:vi.fn(),status:vi.fn(),remove:vi.fn(),save:vi.fn()},studyPacks:{list:vi.fn(),originalUrl:()=>'/image',assetUrl:()=>'/pixels',figures:vi.fn(),visualList:vi.fn(),visualStart:vi.fn(),visualStatus:vi.fn(),visualAction:vi.fn()}}}));
const item={attachment_id:'image',pack:{pack_id:'image',name:'Temporary',retention:'temporary',expires_at:Date.now()/1000+3600,state:'empty'},document:{document_id:'doc',filename:'diagram.png'},usable:false,visual_jobs:[]} as unknown as ImageAttachment;
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api.attachments.status).mockResolvedValue(item);vi.mocked(api.studyPacks.figures).mockResolvedValue({figures:[],external_allowed:false});vi.mocked(api.studyPacks.visualList).mockResolvedValue({jobs:[]});});
function view(attachment:ImageAttachment|null,onChange=vi.fn()){
 return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><AskImage attachment={attachment} onChange={onChange} onUnavailable={vi.fn()} question="Arrow?" /></QueryClientProvider>);
}
it('upload alone never starts visual inference and late upload is cleaned instead of mounted',async()=>{
 let finish!:(v:ImageAttachment)=>void;
 vi.mocked(api.attachments.upload).mockReturnValue(new Promise(resolve=>{finish=resolve;}));
 const changed=vi.fn(); const v=view(null,changed);
 fireEvent.change(screen.getByLabelText('Attach PNG or JPEG'),{target:{files:[new File(['pixels'],'diagram.png',{type:'image/png'})]}});
 v.unmount();finish(item);
 await waitFor(()=>expect(api.attachments.remove).toHaveBeenCalledWith('image','image'));
 expect(changed).not.toHaveBeenCalled();
});
it('pasting an image uploads it without starting inference',async()=>{
 vi.mocked(api.attachments.upload).mockResolvedValue(item);
 const changed=vi.fn();view(null,changed);
 const file=new File(['pixels'],'pasted.png',{type:'image/png'});
 fireEvent.paste(screen.getByRole('region',{name:'Question image'}),{clipboardData:{items:[{type:'image/png',getAsFile:()=>file}]}});
 await waitFor(()=>expect(changed).toHaveBeenCalledWith(item));
 expect(api.studyPacks.visualStart).not.toHaveBeenCalled();
});
it('detaching a saved image never deletes the retained pack',async()=>{
 const saved={...item,pack:{...item.pack,retention:'saved' as const,expires_at:null}};
 vi.mocked(api.attachments.status).mockResolvedValue(saved);
 const changed=vi.fn();view(saved,changed);
 fireEvent.click(screen.getByRole('button',{name:'Detach image'}));
 await waitFor(()=>expect(changed).toHaveBeenCalledWith(null));
 expect(api.attachments.remove).not.toHaveBeenCalled();
});
it('waits for indexing and recognizes real sparse-ready job completion',async()=>{
 vi.mocked(api.studyPacks.figures).mockResolvedValue({figures:[{figure_id:'figure',locator:{kind:'image'},reason:'source_image'}] as never,external_allowed:false});
 vi.mocked(api.studyPacks.visualStart).mockResolvedValue({job_id:'visual',pack_id:'image',state:'queued'});
 vi.mocked(api.studyPacks.visualStatus).mockResolvedValue({job_id:'visual',pack_id:'image',state:'completed',config:{provider:'ollama',model:'qwen3.5:4b'},tokens_used:0,checkpoints:[]});
 vi.mocked(api.attachments.status).mockResolvedValueOnce({...item,job:{job_id:'extract',pack_id:'image',state:'empty'}})
   .mockResolvedValueOnce({...item,usable:true,job:{job_id:'index',pack_id:'image',state:'queued'}})
   .mockResolvedValue({...item,usable:true,job:{job_id:'index',pack_id:'image',state:'sparse-ready'}});
 const ref=createRef<AskImageHandle>();const changed=vi.fn();
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><AskImage ref={ref} attachment={item} onChange={changed} onUnavailable={vi.fn()} question="Arrow?" /></QueryClientProvider>);
 await screen.findByLabelText('Select figure 1');
 vi.useFakeTimers();const active=new AbortController();let finished:ImageAttachment|undefined;
 const work=ref.current!.prepare(active.signal,()=>{}).then(value=>{finished=value;}).catch(()=>{});
 try{
   await act(async()=>{await vi.advanceTimersByTimeAsync(3100);});
   expect(finished?.attachment_id).toBe('image');
   expect(changed).toHaveBeenCalledTimes(1);
 }finally{active.abort();await work;vi.useRealTimers();}
});
