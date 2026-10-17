import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { PageHeader, ProgressBar, StatusPill } from '../components/ui';
import { StudyUnitContent, locatorLabel } from '../components/study-source';
import { StudyVisualManager } from '../components/study-figure';
import { api } from '../lib/api';
import { clearPackArchive } from '../lib/trace-store';
import type { StudyJob, StudyUnit } from '../types';

export function StudyPacksPage() {
  const client = useQueryClient();
  const [packId, setPackId] = useState('');
  const [docId, setDocId] = useState('');
  const [name, setName] = useState('');
  const [domain, setDomain] = useState('general');
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [job, setJob] = useState<StudyJob | null>(null);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<StudyUnit | null>(null);
  const [target, setTarget] = useState<{ id: string; doc?: string } | null>(null);
  const [confirmation, setConfirmation] = useState('');
  const packs = useQuery({ queryKey: ['study-packs'], queryFn: api.studyPacks.list, refetchInterval: 3000 });
  const detail = useQuery({ queryKey: ['study-pack', packId], queryFn: () => api.studyPacks.detail(packId), enabled: !!packId, refetchInterval: 3000 });
  const units = useQuery({ queryKey: ['study-units', packId, docId, offset], queryFn: () => api.studyPacks.units(packId, docId, offset), enabled: !!docId });
  const jobState = useQuery({ queryKey: ['study-job', job?.job_id], queryFn: () => api.studyPacks.status(job!.job_id), enabled: !!job, refetchInterval: (query) => ['queued', 'extracting', 'extracted', 'indexing'].includes(query.state.data?.state ?? 'queued') ? 1000 : false });
  const activeDoc = detail.data?.documents.find((doc) => doc.document_id === docId);
  async function action(work: () => Promise<unknown>) {
    setBusy(true); setError('');
    try { await work(); await client.invalidateQueries({ queryKey: ['study-packs'] }); await client.invalidateQueries({ queryKey: ['study-pack', packId] }); }
    catch (exc) { setError(exc instanceof Error ? exc.message : 'Action failed.'); }
    finally { setBusy(false); }
  }
  function resetDocument() { setDocId(''); setSelected(null); setOffset(0); }
  async function upload(file: File) {
    setProgress(0);
    await action(async () => { const result = await api.studyPacks.upload(packId, file, setProgress); setProgress(null); setJob(result.job); resetDocument(); });
    setProgress(null);
  }
  async function purge() {
    if (!target || confirmation !== target.id) return;
    await action(async () => {
      const result = await api.studyPacks.purge(packId, confirmation, target.doc);
      if (!result.deleted) throw new Error('Cleanup did not complete.');
      clearPackArchive(packId);
      window.dispatchEvent(new CustomEvent('study-pack-purged', { detail: packId }));
      // Private run/source caches may contain evidence from the removed document.
      await client.cancelQueries({ predicate: (query) => query.queryKey.includes(packId) || ['recent-runs', 'run'].includes(String(query.queryKey[0])) });
      client.removeQueries({ predicate: (query) => query.queryKey.includes(packId) || ['recent-runs', 'run'].includes(String(query.queryKey[0])) });
      setTarget(null); setConfirmation(''); setJob(null); resetDocument();
      if (!target.doc) setPackId('');
    });
  }
  return <div className="page-stack">
    <PageHeader eyebrow="Local study material" title="Your sources. Their exact context." description="Upload PDF, PPTX, XLSX, PNG/JPEG, UTF-8 text or Markdown. Study packs remain separate from the original biology corpus." />
    <section className="study-create query-panel">
      <label>Pack name<input value={name} onChange={(event) => setName(event.target.value)} maxLength={160} /></label>
      <label>Domain adapter<select value={domain} onChange={(event) => setDomain(event.target.value)}><option value="general">General · arithmetic and units</option><option value="biology">Biology · additional bio checks</option></select></label>
      <button disabled={busy || !name.trim()} onClick={() => void action(async () => { const pack = await api.studyPacks.create(name.trim(), domain); setPackId(pack.pack_id); resetDocument(); setName(''); })}>Create pack</button>
    </section>
    {(error || packs.error || detail.error) && <div role="alert" className="error-banner">{error || packs.error?.message || detail.error?.message}</div>}
    <div className="study-workspace">
      <aside className="study-outline" aria-label="Study packs">
        {packs.isPending && <p role="status">Loading packs…</p>}
        {packs.data?.packs.length === 0 && <p>No packs yet. Create one to upload your material.</p>}
        {packs.data?.packs.map((pack) => <button className={pack.pack_id === packId ? 'is-selected' : ''} key={pack.pack_id} onClick={() => { setPackId(pack.pack_id); resetDocument(); setJob(null); setTarget(null); }}><strong>{pack.name}</strong><small>{pack.state} · {pack.domain}</small></button>)}
      </aside>
      {detail.data && <section className="study-detail">
        <div className="study-toolbar"><h2>{detail.data.name}</h2><StatusPill tone={detail.data.state.endsWith('-ready') ? 'success' : 'warning'}>{detail.data.state}</StatusPill></div>
        {['sparse-ready', 'hybrid-ready'].includes(detail.data.state) && <a href={`/ask?pack_id=${encodeURIComponent(packId)}`}>Ask from this pack</a>}
        <p>50 MiB per file. Uploads automatically extract, chunk and index with cached CPU embeddings. Hybrid-ready enables hybrid retrieval; sparse-ready is the explicit fallback. Cached reranking is enabled by default. Scans/images retain upright previews; OCR and vision require an explicit pass. No uploaded instructions are executed.</p>
        <div className="study-toolbar">
          <label className="study-upload">Upload material<input type="file" accept=".pdf,.pptx,.xlsx,.txt,.md,.markdown,.png,.jpg,.jpeg" disabled={busy || detail.data.state === 'purge-pending'} onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = ''; }} /></label>
          <button disabled={busy || !detail.data.documents.length || detail.data.state === 'purge-pending'} onClick={() => void action(async () => setJob(await api.studyPacks.index(packId, true)))}>Build cached dense index (CPU)</button>
          <button disabled={busy} onClick={() => { setTarget({ id: packId }); setConfirmation(''); }}>Delete pack permanently</button>
          {detail.data.state === 'purge-pending' && detail.data.pending_purge && <button disabled={busy} onClick={() => {
            const doc = detail.data.pending_purge?.document_id ?? undefined;
            setTarget({ id: doc ?? packId, doc }); setConfirmation('');
          }}>Retry failed cleanup</button>}
        </div>
        {progress !== null && <div role="status"><p>Upload byte transfer only: {progress}% · extraction/indexing follows separately</p><ProgressBar value={progress} label="Upload byte transfer" /></div>}
        {job && <p role="status">Processing: {jobState.data?.state ?? job.state} {jobState.data?.error && <span>{jobState.data.error}</span>}{jobState.data?.state === 'failed' && job.document_id && <button disabled={busy} onClick={() => void action(async () => setJob(await api.studyPacks.retry(job.job_id)))}>Retry extraction</button>}</p>}
        <div className="study-documents" aria-label="Documents">
          {detail.data.documents.map((doc) => <article key={doc.document_id}>
            <button onClick={() => { setDocId(doc.document_id); setSelected(null); setOffset(0); }} aria-label={`Inspect ${doc.filename}`}><strong>{doc.filename}</strong><small>{doc.state} · {doc.active ? 'active' : 'inactive · original retained'}</small></button>
            <p>{Object.entries(doc.coverage).map(([key, value]) => `${key}: ${value}`).join(' · ')}</p>
            {doc.warnings.length > 0 && <ul>{doc.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
            <div className="study-toolbar"><button disabled={busy || !doc.active || detail.data.state === 'purge-pending'} onClick={() => void action(async () => setJob(await api.studyPacks.deactivate(packId, doc.document_id)))}>Deactivate</button><button disabled={busy} onClick={() => { setTarget({ id: doc.document_id, doc: doc.document_id }); setConfirmation(''); }}>Delete document permanently</button></div>
          </article>)}
        </div>
        {activeDoc?.active && <StudyVisualManager key={`${packId}:${docId}`} pack={packId} doc={docId} />}
        {activeDoc && <div className="study-source-grid">
          <nav className="study-outline" aria-label="Document units">
            <h3>{activeDoc.filename}</h3>
            {units.data?.units.map((unit) => <button key={unit.unit_id} onClick={() => setSelected(unit)}><strong>{unit.locators.map(locatorLabel).join(' · ')}</strong><small>{unit.title} · {unit.role}{!unit.text && ' · no text'}</small></button>)}
            {units.error && <p role="alert">{units.error.message}</p>}
            <div className="study-toolbar"><button disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - 100)); setSelected(null); }}>Previous units</button><button disabled={offset + 100 >= (units.data?.total ?? 0)} onClick={() => { setOffset(offset + 100); setSelected(null); }}>Next units</button></div>
          </nav>
          {selected ? <StudyUnitContent pack={packId} doc={docId} unit={selected} /> : <p>Select a page, slide, notes block or sheet row to inspect its original extracted text.</p>}
        </div>}
        {target && <section className="study-confirm" aria-label="Permanent deletion confirmation">
          <h3>Permanent deletion</h3><p>Deletes original bytes and extracted data. Any document purge also clears this pack’s entire answer/trace history and rebuilds its remaining index. Deactivation is recoverable; this deletion is not. SSD remnants, backups, exports and other browsers are outside this guarantee.</p>
          <code>{target.id}</code><label>Type target ID to confirm<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
          <button disabled={busy || confirmation !== target.id} onClick={() => void purge()}>Confirm permanent deletion</button><button disabled={busy} onClick={() => setTarget(null)}>Cancel deletion</button>
        </section>}
      </section>}
    </div>
  </div>;
}
