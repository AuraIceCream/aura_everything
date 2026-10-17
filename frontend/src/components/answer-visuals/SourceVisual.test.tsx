import {fireEvent,render,screen} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {it,expect,vi} from 'vitest';
import {SourceVisual} from './SourceVisual';
import {source} from './fixtures';
import type {StudyUnit} from '../../types';
const unit:StudyUnit={unit_id:source.payload.unit_id,document_id:source.payload.document_id,ordinal:0,role:'figure_description',title:'Lesson',breadcrumb:'',text:'ORION activates VEGA.',locators:[{kind:'pdf',page:2}],metadata:{},asset_ids:[source.payload.asset_id!],provenance:'vlm',provenance_details:{bbox:source.payload.bbox}};
vi.mock('../../lib/api',()=>({api:{studyPacks:{unit:async()=>unit,assetUrl:()=>'/owned.png',originalUrl:()=>'/owned-original'}}}));
function mount(spec=source){return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><SourceVisual spec={spec} onCitation={()=>{}} /></QueryClientProvider>);}
it('uses the cited immutable source and separate upright overlays',async()=>{
  const {container}=mount();await screen.findByRole('img');
  expect(screen.getByRole('img')).toHaveAttribute('src','/owned.png');
  expect(screen.getByLabelText('Selected upright source region')).toHaveStyle({left:'10%',top:'20%',width:'70%',height:'70%'});
  expect(container.querySelector('canvas')).toBeNull();
  expect(screen.getByText(/Page 2/)).toBeInTheDocument();
});
it('shows unavailability after purge or a failed asset, not a substitute',async()=>{
  mount();const image=await screen.findByRole('img');fireEvent.error(image);
  expect(screen.getByRole('alert')).toHaveTextContent('Source unavailable');
  expect(screen.queryByRole('img')).toBeNull();
});
it('does not invent a precise region when only the whole source is known',async()=>{
  mount({...source,payload:{...source.payload,bbox:null,highlight_precision:'whole_asset'}});await screen.findByRole('img');
  expect(screen.queryByLabelText('Selected upright source region')).toBeNull();
  expect(screen.getByText(/Whole source/)).toBeInTheDocument();
});
