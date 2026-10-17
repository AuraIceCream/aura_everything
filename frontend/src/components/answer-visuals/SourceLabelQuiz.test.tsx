import {fireEvent,render,screen} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
import {SourceLabelQuiz,ocrWordsInSourceFrame} from './SourceLabelQuiz';
import {source} from './fixtures';
const words=[{text:'ORION',confidence:95,bbox:[.1,.2,.3,.3]},{text:'LOW',confidence:40,bbox:[.4,.2,.5,.3]}];
it('maps crop-relative OCR boxes into the upright source rather than masking the wrong panel',()=>{
  const converted=ocrWordsInSourceFrame([{text:'ORION',confidence:95,bbox:[.25,.25,.5,.5]}],{x0:.2,y0:.3,x1:.8,y1:.9});
  converted[0].bbox.forEach((value,n)=>expect(value).toBeCloseTo([.35,.45,.5,.6][n]));
});
it('requires confirmation and hides confirmed keys from the DOM before reveal',()=>{
  const result=vi.fn();const {container}=render(<SourceLabelQuiz source={source} ocrWords={words} onPracticeResult={result}/>);
  fireEvent.click(screen.getByRole('button',{name:'Practice labels'}));
  expect(screen.getByLabelText('Confirm label 1')).toHaveValue('ORION');expect(container.textContent).not.toContain('LOW');
  expect(screen.getByRole('button',{name:'Start practice'})).toBeDisabled();
  fireEvent.click(screen.getByLabelText('Use label 1'));
  fireEvent.click(screen.getByRole('button',{name:'Start practice'}));
  expect(container.innerHTML).not.toContain('ORION');
  fireEvent.change(screen.getByLabelText('Your answer for label 1'),{target:{value:' orion '}});
  fireEvent.click(screen.getByRole('button',{name:'Check answers'}));
  expect(result).toHaveBeenCalledWith(expect.objectContaining({pack_id:source.payload.pack_id,revision_id:source.payload.revision_id,correct:1,attempted:1,provenance:'user_annotation'}));
  expect(container.innerHTML).not.toContain('ORION');
  fireEvent.click(screen.getByRole('button',{name:'Reveal labels'}));expect(screen.getByText('ORION')).toBeInTheDocument();
});
it('has an explicit unavailable state without OCR and clears old revision state',()=>{
  const {rerender}=render(<SourceLabelQuiz source={source} ocrWords={[]} onPracticeResult={()=>{}}/>);
  expect(screen.getByText(/No OCR labels/)).toBeInTheDocument();
  rerender(<SourceLabelQuiz source={{...source,payload:{...source.payload,revision_id:'f'.repeat(32)}}} ocrWords={words} onPracticeResult={()=>{}}/>);
  expect(screen.getByRole('button',{name:'Practice labels'})).toBeInTheDocument();
});
