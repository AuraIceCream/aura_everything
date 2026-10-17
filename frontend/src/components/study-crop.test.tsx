import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { StudyCrop } from './study-crop';

it('offers numeric keyboard controls and rejects an inverted crop', () => {
  const save=vi.fn(); render(<StudyCrop sourceUrl="/owned.png" initial={{x0:0,y0:0,x1:1,y1:1}} onSave={save} />);
  fireEvent.change(screen.getByLabelText('Left'),{target:{value:'0.8'}});
  fireEvent.change(screen.getByLabelText('Right'),{target:{value:'0.2'}});
  expect(screen.getByRole('button',{name:'Save crop'})).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Right'),{target:{value:'0.9'}});
  fireEvent.click(screen.getByRole('button',{name:'Save crop'}));
  expect(save).toHaveBeenCalledWith({x0:.8,y0:0,x1:.9,y1:1});
});
