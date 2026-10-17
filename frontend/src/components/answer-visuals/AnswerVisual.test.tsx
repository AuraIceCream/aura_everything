import {render,screen,fireEvent} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
import {AnswerVisual} from './AnswerVisual';
import {scientificPlot} from './fixtures';
import * as exports from './export';

it('exports the actual trusted scientific SVG, not only its fact table',()=>{
  const download=vi.spyOn(exports,'downloadVisual').mockResolvedValue(undefined);
  render(<AnswerVisual visual={{status:'ready',spec:scientificPlot(),limitations:[]}} onCitation={()=>{}}/>);
  fireEvent.click(screen.getByRole('button',{name:'Download SVG'}));
  expect(download).toHaveBeenCalledTimes(1);
  expect(download.mock.calls[0][1]).toHaveLength(1);
  download.mockRestore();
});
