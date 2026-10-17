import {render,screen} from '@testing-library/react';
import {expect,it} from 'vitest';
import {ProcedureVisual} from './ProcedureVisual';
import {support} from './fixtures';
import type {ProcedureVisualSpec} from '../../types';
it('numbers only source-established total order and marks parallel/unordered steps',()=>{
  const spec:ProcedureVisualSpec={version:1,id:'procedure',kind:'procedure',title:'Procedure',description:'Source order',payload:{steps:[{id:'a',text:'ORION',claim_ids:['c1'],support},{id:'b',text:'VEGA',claim_ids:['c1'],support}],precedes:[],ordering:'partial'}};
  const {container,rerender}=render(<ProcedureVisual spec={spec} onCitation={()=>{}}/>);
  expect(container.querySelector('ol')).toBeNull();expect(screen.getByText(/parallel or unspecified/)).toBeInTheDocument();
  rerender(<ProcedureVisual spec={{...spec,payload:{...spec.payload,ordering:'total'}}} onCitation={()=>{}}/>);
  expect(container.querySelectorAll('ol li')).toHaveLength(2);
});
