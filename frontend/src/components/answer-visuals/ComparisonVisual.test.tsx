import {render,screen,fireEvent} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
import {ComparisonVisual} from './ComparisonVisual';
import {support} from './fixtures';
import type {ComparisonVisualSpec} from '../../types';
it('renders source-bound cells as an accessible table and explicitly marks absence',()=>{
  const bound={claim_ids:['c1'],bindings:[],support};
  const spec:ComparisonVisualSpec={version:1,id:'compare',kind:'comparison',title:'Compare',description:'Source comparison',payload:{columns:[{id:'a',text:'Group A',...bound},{id:'b',text:'Group B',...bound}],rows:[{id:'count',criterion:{text:'Count',...bound},cells:[{column_id:'a',text:'33 cells',status:'stated',...bound},{column_id:'b',text:'',status:'not_stated',claim_ids:[],bindings:[]}]}]}};
  const cite=vi.fn();render(<ComparisonVisual spec={spec} onCitation={cite}/>);
  expect(screen.getByRole('table')).toHaveTextContent('33 cells');
  expect(screen.getByText('Not stated in the selected material')).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole('button',{name:'Open cit-1'})[0]);expect(cite).toHaveBeenCalledWith('cit-1');
});
