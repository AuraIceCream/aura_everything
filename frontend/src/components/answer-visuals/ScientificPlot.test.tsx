import {render,screen} from '@testing-library/react';
import {it,expect} from 'vitest';
import {PlotVisual} from './PlotVisual';
import {scientificPlot} from './fixtures';

it('shows source-defined uncertainty and its exact data, not an invented CI',()=>{
  const spec=scientificPlot();spec.payload.series[0].points[0].uncertainty={kind:'SD',magnitude:'2',bindings:{}};
  const {container}=render(<PlotVisual spec={spec} onCitation={()=>{}}/>);
  expect(container.querySelector('[data-uncertainty="SD"]')).not.toBeNull();
  expect(screen.getByRole('table')).toHaveTextContent('SD 2');
  expect(screen.getByRole('table')).not.toHaveTextContent('CI');
});

it('heatmap differentiates a source missing cell from zero and keeps its row/column',()=>{
  const spec=scientificPlot();spec.payload.chart_type='heatmap';
  const points=spec.payload.series[0].points;
  points[0].column='Sample A';points[0].value='0';points[1].column='Sample B';points[1].value=null;
  const {container}=render(<PlotVisual spec={spec} onCitation={()=>{}}/>);
  expect(container.querySelector('[data-missing="true"]')).not.toBeNull();
  expect(container.querySelector('[data-source-value="0"]')).not.toBeNull();
  expect(screen.getByRole('table')).toHaveTextContent('Sample B');
});
