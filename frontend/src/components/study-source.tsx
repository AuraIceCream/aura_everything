import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { StudyLocator, StudyUnit } from '../types';
import { RegionImage } from './study-crop';

const labels:Record<string,string>={native_text:'Native extracted text',vlm:'Model-described figure · interpreted, not verified',ocr:'OCR transcription · numbers unverified',user_annotation:'User annotation · not independently verified'};

export function locatorLabel(loc: StudyLocator): string {
  if (loc.kind==='image') return 'Source image';
  if (loc.page != null) return `Page ${loc.page}${loc.page_label && loc.page_label !== String(loc.page) ? ` (${loc.page_label})` : ''}`;
  if (loc.slide != null) return `Slide ${loc.slide}${loc.role === 'notes' ? ' · notes' : ''}${loc.shape_id ? ` · shape ${loc.shape_id}` : ''}`;
  if (loc.sheet) return `${loc.sheet}!${loc.cell_range ?? ''}`;
  return `Lines ${loc.start_line ?? '?'}–${loc.end_line ?? '?'}${loc.role === 'notes' ? ' · notes' : ''}`;
}

export function StudyUnitContent({ pack, doc, unit }: { pack: string; doc: string; unit: StudyUnit }) {
  return <section className="study-preview" aria-label="Original source unit">
    <h3>{unit.title}</h3>
    <p>{unit.locators.map(locatorLabel).join(' · ')} · {unit.role}</p>
    <small>{labels[unit.provenance??'native_text']} · immutable unit {unit.unit_id.slice(0,8)}</small>
    {unit.provenance_details?.model!=null && <p>{String(unit.provenance_details.provider)} · {String(unit.provenance_details.model)}</p>}
    <pre>{unit.text || '(No extracted text in this unit.)'}</pre>
    {unit.asset_ids.map((asset) => <figure key={asset}><RegionImage sourceUrl={api.studyPacks.assetUrl(pack,doc,asset)} bbox={unit.provenance_details?.bbox as import('../types').NormalizedBox|undefined} alt="Upright source image for this immutable revision" /><figcaption>Source pixels · not an independently verified fact</figcaption></figure>)}
    {unit.provenance==='ocr' && <details><summary>OCR words, confidence and boxes (confidence is not truth)</summary><pre>{JSON.stringify(unit.metadata.ocr,null,2)}</pre></details>}
    <a href={api.studyPacks.originalUrl(pack, doc)} download>Download original</a>
  </section>;
}

export function StudySourcePreview({ pack, doc, unitId }: { pack: string; doc: string; unitId: string }) {
  const unit = useQuery({ queryKey: ['study-unit', pack, doc, unitId], queryFn: () => api.studyPacks.unit(pack, doc, unitId) });
  if (unit.isPending) return <p role="status">Loading original unit…</p>;
  if (unit.error) return <p role="alert">{unit.error.message}</p>;
  return unit.data ? <StudyUnitContent pack={pack} doc={doc} unit={unit.data} /> : null;
}
