import { render,screen } from '@testing-library/react';
import { expect,it,vi } from 'vitest';
import { StudyUnitContent } from './study-source';
import type { StudyUnit } from '../types';

vi.mock('../lib/api',()=>({api:{studyPacks:{assetUrl:()=>'/owned-source.png',originalUrl:()=>'/owned-original'}}}));

it('shows interpretation as escaped text with a source-region highlight, not verification',()=>{
  const unit:StudyUnit={unit_id:'old-revision',document_id:'d',ordinal:0,role:'figure_description',title:'Slide diagram',breadcrumb:'',
    text:'<script>alert("not executable")</script>',locators:[{kind:'pdf',page:2}],metadata:{},asset_ids:['a'],provenance:'vlm',
    provenance_details:{bbox:{x0:.1,y0:.2,x1:.8,y1:.9},model:'fake-vision',provider:'test'}};
  const {container}=render(<StudyUnitContent pack="p" doc="d" unit={unit} />);
  expect(screen.getByText(/interpreted, not verified/)).toBeInTheDocument();
  expect(screen.getByText('<script>alert("not executable")</script>')).toBeInTheDocument();
  expect(container.querySelector('script')).toBeNull();
  expect(screen.getByLabelText('Selected upright source region')).toHaveStyle({left:'10%',top:'20%',width:'70%',height:'70%'});
  expect(screen.getByRole('img')).toHaveAttribute('src','/owned-source.png');
  expect(screen.getByText(/immutable unit old-revi/)).toBeInTheDocument();
});
