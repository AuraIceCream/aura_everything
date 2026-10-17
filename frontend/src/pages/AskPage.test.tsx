import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { AskPage } from './AskPage';
import { api } from '../lib/api';
const {prepare}=vi.hoisted(()=>({prepare:vi.fn()}));
vi.mock('../components/ask-image',async()=>{
  const {forwardRef,useImperativeHandle}=await import('react');
  return {AskImage:forwardRef(({onChange}:any,ref)=>{useImperativeHandle(ref,()=>({prepare}));return <button type="button" onClick={()=>onChange({attachment_id:'image',pack:{pack_id:'image',retention:'temporary'},document:{filename:'diagram.png'}})}>Test attach</button>;})};
});
const start = vi.fn();
vi.mock('../hooks/use-run', () => ({ useRun: () => ({ state: { status: 'idle', trace: [] }, start, reset: vi.fn(), cancel: vi.fn() }) }));
vi.mock('../context/settings', () => ({ useSettings: () => ({ settings: { learnerLevel: 'high_school', teachingMode: 'guided', responseLength: 'balanced', contextDepth: 'none', externalCritic: true }, update: vi.fn() }) }));
vi.mock('../lib/api', () => ({ api: { studyPacks: { list: vi.fn(), resolveVisualQuestion:vi.fn(),visualStart:vi.fn(),visualStatus:vi.fn(),visualAction:vi.fn(),detail:vi.fn() } } }));
beforeEach(() => { vi.clearAllMocks(); prepare.mockResolvedValue({});vi.mocked(api.studyPacks.list).mockResolvedValue({ packs: [
  { pack_id: 'ready', name: 'Ready pack', state: 'sparse-ready' }, { pack_id: 'waiting', name: 'Waiting pack', state: 'empty' },
] } as never); });
it('sends automatic selection when enabled and none when switched off',async()=>{
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><AskPage /></MemoryRouter></QueryClientProvider>);
 await screen.findByRole('option',{name:/Ready pack/});
 fireEvent.change(screen.getByLabelText('Answer from'),{target:{value:'ready'}});
 const visual=screen.getByLabelText('Answer visual');
 expect(screen.getByRole('option',{name:'On — automatic'})).toBeInTheDocument();
 fireEvent.change(visual,{target:{value:'auto'}});
 fireEvent.change(screen.getByLabelText('Ask a biology question'),{target:{value:'How do they interact?'}});
 fireEvent.click(screen.getByRole('button',{name:'Ask AURA'}));
 expect(start).toHaveBeenLastCalledWith(expect.objectContaining({visual_output:'auto'}));
 fireEvent.change(visual,{target:{value:'none'}});
 fireEvent.change(screen.getByLabelText('Ask a biology question'),{target:{value:'Define ORION'}});
 fireEvent.click(screen.getByRole('button',{name:'Ask AURA'}));
 expect(start).toHaveBeenLastCalledWith(expect.objectContaining({visual_output:'none'}));
});
it('uses pack-only, requires readiness and explicit private critic consent, then restores core', async () => {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><AskPage /></MemoryRouter></QueryClientProvider>);
  await screen.findByRole('option', { name: /Ready pack/ });
  fireEvent.change(screen.getByLabelText('Answer from'), { target: { value: 'waiting' } });
  fireEvent.change(screen.getByLabelText('Ask a biology question'), { target: { value: 'ORION?' } });
  expect(screen.getByRole('button', { name: 'Ask AURA' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Answer from'), { target: { value: 'ready' } });
  fireEvent.click(screen.getByRole('button', { name: 'Ask AURA' }));
  await waitFor(() => expect(start).toHaveBeenCalledWith(expect.objectContaining({ pack_id: 'ready', evidence_scope: 'pack_only', allow_external_critic: false })));
  fireEvent.click(screen.getByRole('checkbox', { name: /private source excerpts/ }));
  fireEvent.change(screen.getByLabelText('Ask a biology question'), { target: { value: 'VEGA?' } });
  fireEvent.click(screen.getByRole('button', { name: 'Ask AURA' }));
  expect(start).toHaveBeenLastCalledWith(expect.objectContaining({ allow_external_critic: true }));
  fireEvent.change(screen.getByLabelText('Answer from'), { target: { value: '' } });
  fireEvent.change(screen.getByLabelText('Ask a biology question'), { target: { value: 'Biology?' } });
  fireEvent.click(screen.getByRole('button', { name: 'Ask AURA' }));
  expect(start).toHaveBeenLastCalledWith(expect.objectContaining({ evidence_scope: 'core', pack_id: null }));
});
it('uses tutor delivery by default and sends strict only when selected for a study pack',async()=>{
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><AskPage /></MemoryRouter></QueryClientProvider>);
 await screen.findByRole('option',{name:/Ready pack/});
 fireEvent.change(screen.getByLabelText('Answer from'),{target:{value:'ready'}});
 fireEvent.change(screen.getByLabelText('Ask a biology question'),{target:{value:'ORION?'}});
 fireEvent.click(screen.getByRole('button',{name:'Ask AURA'}));
 expect(start).toHaveBeenLastCalledWith(expect.objectContaining({answer_mode:'tutor'}));
 fireEvent.change(screen.getByLabelText('Study answer mode'),{target:{value:'strict'}});
 fireEvent.change(screen.getByLabelText('Ask a biology question'),{target:{value:'VEGA?'}});
 fireEvent.click(screen.getByRole('button',{name:'Ask AURA'}));
 expect(start).toHaveBeenLastCalledWith(expect.objectContaining({answer_mode:'strict'}));
});
it('one Ask binds image, saved context and private critic consent independently',async()=>{
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><AskPage /></MemoryRouter></QueryClientProvider>);
  await screen.findByRole('option',{name:/Ready pack/});
  fireEvent.change(screen.getByLabelText('Answer from'),{target:{value:'ready'}});
  fireEvent.click(screen.getByRole('button',{name:'Test attach'}));
  fireEvent.change(screen.getByLabelText('Ask a biology question'),{target:{value:'Arrow?'}});
  prepare.mockRejectedValueOnce(new Error('Image unavailable'));
  fireEvent.click(screen.getByRole('button',{name:'Ask AURA'}));
  await screen.findByRole('alert');
  expect(start).not.toHaveBeenCalled();
});
it('one Ask prepares then starts a correctly scoped composite run',async()=>{
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><AskPage /></MemoryRouter></QueryClientProvider>);
 await screen.findByRole('option',{name:/Ready pack/});
 fireEvent.change(screen.getByLabelText('Answer from'),{target:{value:'ready'}});
 fireEvent.click(screen.getByRole('button',{name:'Test attach'}));
 fireEvent.change(screen.getByLabelText('Ask a biology question'),{target:{value:'Arrow?'}});
 fireEvent.click(screen.getByRole('button',{name:'Ask AURA'}));
 await waitFor(()=>expect(start).toHaveBeenCalledWith(expect.objectContaining({query:'Arrow?',pack_id:'image',attachment_id:'image',context_pack_id:'ready',allow_external_critic:false})));
 expect(prepare).toHaveBeenCalledTimes(1);
});
it('context disappearing in another tab cancels bound image preparation',async()=>{
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
 render(<QueryClientProvider client={client}><MemoryRouter><AskPage /></MemoryRouter></QueryClientProvider>);
 await screen.findByRole('option',{name:/Ready pack/});
 fireEvent.change(screen.getByLabelText('Answer from'),{target:{value:'ready'}});
 fireEvent.click(screen.getByRole('button',{name:'Test attach'}));
 let finish!:()=>void;prepare.mockReturnValue(new Promise<void>(resolve=>{finish=resolve;}));
 fireEvent.change(screen.getByLabelText('Ask a biology question'),{target:{value:'Arrow?'}});
 fireEvent.click(screen.getByRole('button',{name:'Ask AURA'}));
 await waitFor(()=>expect(prepare).toHaveBeenCalled());
 const signal=prepare.mock.calls[0][0] as AbortSignal;
 client.setQueryData(['study-packs'],{packs:[]});
 await waitFor(()=>expect(signal.aborted).toBe(true));
 finish();expect(start).not.toHaveBeenCalled();
});

it('one Ask resolves a PDF figure, waits for indexing, and binds it to the answer',async()=>{
 vi.mocked(api.studyPacks.resolveVisualQuestion).mockResolvedValue({figures:[{figure_id:'f5',document_id:'d',locator:{kind:'pdf',page:3},figure_label:'5'}] as never,warnings:[]});
 vi.mocked(api.studyPacks.visualStart).mockResolvedValue({job_id:'visual',pack_id:'ready',state:'queued'});
 vi.mocked(api.studyPacks.visualStatus).mockResolvedValue({job_id:'visual',pack_id:'ready',state:'completed',indexed:true,tokens_used:0,checkpoints:[],config:{provider:'ollama',model:'qwen3.5:4b'}});
 vi.mocked(api.studyPacks.detail).mockResolvedValue({pack_id:'ready',name:'Ready pack',state:'sparse-ready',documents:[]} as never);
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><AskPage /></MemoryRouter></QueryClientProvider>);
 await screen.findByRole('option',{name:/Ready pack/});
 fireEvent.change(screen.getByLabelText('Answer from'),{target:{value:'ready'}});
 fireEvent.click(screen.getByLabelText('Enable local model thinking'));
 fireEvent.change(screen.getByLabelText('Ask a biology question'),{target:{value:'Explain Fig. 5'}});
 fireEvent.click(screen.getByRole('button',{name:'Ask AURA'}));
 await waitFor(()=>expect(start).toHaveBeenCalledWith(expect.objectContaining({query:'Explain Fig. 5',pack_id:'ready',figure_ids:['f5'],think:true})),{timeout:4000});
 expect(api.studyPacks.visualStart).toHaveBeenCalledWith('ready',['f5'],expect.objectContaining({question:'Explain Fig. 5',think:true}));
});

it('missing requested figure stops before answering instead of using unrelated text',async()=>{
 vi.mocked(api.studyPacks.resolveVisualQuestion).mockRejectedValue(new Error('Figure 99 was not found'));
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><AskPage /></MemoryRouter></QueryClientProvider>);
 await screen.findByRole('option',{name:/Ready pack/});
 fireEvent.change(screen.getByLabelText('Answer from'),{target:{value:'ready'}});
 fireEvent.change(screen.getByLabelText('Ask a biology question'),{target:{value:'Explain Fig. 99'}});
 fireEvent.click(screen.getByRole('button',{name:'Ask AURA'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('Figure 99 was not found');
 expect(start).not.toHaveBeenCalled();
});
