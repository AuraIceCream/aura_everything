import type {PlotVisualV2} from '../../types';

export function DistributionVisual({spec}:{spec:PlotVisualV2}){
  return <p>{spec.payload.distribution_mode==='source_bins'?
    'Source-stated bins and counts. No smoothing, fitting, synthetic samples or reconstructed distribution.':
    'Individual source observations shown separately. No computed histogram, summary statistic or synthetic samples.'}</p>;
}
