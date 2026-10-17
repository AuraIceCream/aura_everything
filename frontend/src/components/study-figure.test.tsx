import { act,fireEvent, render, screen } from '@testing-library/react';
import {createRef} from 'react';
import { QueryClient,QueryClientProvider } from '@tanstack/react-query';
import { beforeEach,expect,it,vi } from 'vitest';
import { StudyVisualManager,type VisualPrepareHandle } from './study-figure';
import { api } from '../lib/api';

vi.mock('../lib/api',()=>({api:{studyPacks:{figures:vi.fn(),visualList:vi.fn(async()=>({jobs:[]})),visualStart:vi.fn(),visualStatus:vi.fn(),visualPreview:vi.fn(),visualPermission:vi.fn(),assetUrl:()=>'/owned.png',figureUrl:()=>'/crop.png'}}}));
beforeEach(()=>vi.clearAllMocks());
it('immediate Ask discovers the one source image after extraction without a second click',async()=>{
  vi.mocked(api.studyPacks.figures).mockReturnValueOnce(new Promise(()=>{})).mockResolvedValue({figures:[{figure_id:'f',unit_id:'u',asset_id:'a',document_id:'d',bbox:{x0:0,y0:0,x1:1,y1:1},frame:'asset_normalized',reason:'source_image',locator:{kind:'image'},context_hash:'hash',checksum:'hash',exclusion_reason:null}],external_allowed:false});
  vi.mocked(api.studyPacks.visualStart).mockClear().mockResolvedValue({job_id:'new',pack_id:'p',state:'queued'});
  vi.mocked(api.studyPacks.visualStatus).mockResolvedValue({job_id:'new',pack_id:'p',state:'completed',tokens_used:0,checkpoints:[],config:{provider:'ollama',model:'qwen3.5:4b'}});
  const ref=createRef<VisualPrepareHandle>();
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><StudyVisualManager pack="p" doc="d" question="Arrow?" autoSelectSingle preparationRef={ref} /></QueryClientProvider>);
  let failure:unknown;
  await act(async()=>{await ref.current!.prepare(new AbortController().signal,()=>{}).catch(e=>{failure=e;});});
  expect(failure).toBeUndefined();
  expect(api.studyPacks.visualStart).toHaveBeenCalledWith('p',['f'],expect.objectContaining({question:'Arrow?'}),undefined);
});
it('never starts automatically and makes a missing model visible',async()=>{
  vi.mocked(api.studyPacks.figures).mockResolvedValue({figures:[{figure_id:'f',unit_id:'u',asset_id:'a',document_id:'d',bbox:{x0:0,y0:0,x1:1,y1:1},frame:'asset_normalized',reason:'embedded_image',locator:{kind:'image'},context_hash:'hash',checksum:'hash',exclusion_reason:null}],external_allowed:false});
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><StudyVisualManager pack="p" doc="d" /></QueryClientProvider>);
  expect(await screen.findByText(/embedded_image/)).toBeInTheDocument();
  expect(api.studyPacks.visualStart).not.toHaveBeenCalled();
  expect(screen.getByRole('button',{name:'Start visual pass'})).toBeDisabled();
  fireEvent.click(screen.getByLabelText('Select figure 1'));
  vi.mocked(api.studyPacks.visualStart).mockRejectedValue(new Error('Selected model is not installed'));
  fireEvent.click(screen.getByRole('button',{name:'Start visual pass'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Selected model is not installed');
});

it('opens a durable paused job after remount without automatically resuming',async()=>{
  vi.mocked(api.studyPacks.visualList).mockResolvedValue({jobs:[{job_id:'old-job',pack_id:'p',state:'paused'}]});
  vi.mocked(api.studyPacks.visualStatus).mockResolvedValue({job_id:'old-job',pack_id:'p',state:'paused',config:{provider:'ollama',model:'test'},tokens_used:0,checkpoints:[]});
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><StudyVisualManager pack="p" doc="d" /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole('button',{name:/Inspect job old-job/}));
  expect(await screen.findByRole('button',{name:'Resume unfinished figures'})).toBeInTheDocument();
});

it('requires hosted payload preview and explicit crop/hint approval, cleared on model change',async()=>{
  vi.mocked(api.studyPacks.figures).mockResolvedValue({figures:[{figure_id:'f',unit_id:'u',asset_id:'a',document_id:'d',bbox:{x0:0,y0:0,x1:1,y1:1},frame:'asset_normalized',reason:'embedded_image',locator:{kind:'image'},context_hash:'hash',checksum:'hash',exclusion_reason:null}],external_allowed:true});
  vi.mocked(api.studyPacks.visualPreview).mockResolvedValue({preview_hash:'approved-hash',provider:'groq',model:'vision',disclosure:'Images and hints leave the device',figures:[{figure_id:'f',image_bytes:100,ocr_hint:'Untrusted label',caption_hint:'Course notes',crop_sha256:'sha'}]});
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><StudyVisualManager pack="p" doc="d" /></QueryClientProvider>);
  await screen.findByText(/embedded_image/);
  fireEvent.change(screen.getByLabelText('Visual provider'),{target:{value:'groq'}});
  fireEvent.click(screen.getByLabelText('Select figure 1'));
  expect(screen.getByRole('button',{name:'Start visual pass'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'Preview exact hosted payload'}));
  const approval=await screen.findByLabelText('Approve exactly these crops and hints for this job');
  expect(screen.getByRole('button',{name:'Start visual pass'})).toBeDisabled();
  fireEvent.click(approval);
  expect(screen.getByRole('button',{name:'Start visual pass'})).toBeEnabled();
  fireEvent.change(screen.getByLabelText('Exact model ID'),{target:{value:'another-model'}});
  expect(screen.getByRole('button',{name:'Start visual pass'})).toBeDisabled();
  expect(screen.queryByLabelText('Approve exactly these crops and hints for this job')).not.toBeInTheDocument();
});
