import { useQuery } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Database, FileStack, HardDrive, Layers3, RefreshCw, SearchCheck, Sparkles } from "lucide-react";
import { api } from "../lib/api";
import { Metric, PageHeader, ProgressBar, StatusPill } from "../components/ui";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const format = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
const formatBytes = (value: number) => `${(value / 1024 ** 3).toFixed(1)} GiB`;

export function CorpusPage() {
  const status = useQuery({ queryKey: ["corpus-status"], queryFn: api.corpusStatus, refetchInterval: 10_000 });
  return (
    <div className="page-stack">
      <PageHeader eyebrow="Corpus readiness" title="From source files to searchable evidence" description="Track each transformation without mixing downloaded, canonical, chunked, and indexed data." action={<button className="secondary-button" onClick={() => status.refetch()}><RefreshCw size={15} />Refresh</button>} />
      {status.data && <>
        <section className="readiness-banner"><div className="readiness-icon"><Layers3 size={24} /></div><div><span className="eyebrow">Current capability</span><h2>Sparse and pilot dense retrieval are available</h2><p>Chunking is still in progress. Queries use only indexed sources, and coverage is shown with every answer.</p></div><StatusPill tone="warning"><AlertCircle size={13} /> Partial index</StatusPill></section>
        <section className="metrics-grid"><Metric label="Source families" value={String(status.data.totals.sources)} helper="All licence-reviewed" /><Metric label="Canonical records" value={format.format(status.data.totals.documents)} helper="Parsed and cleaned" /><Metric label="Retrieval chunks" value={format.format(status.data.totals.chunks)} helper={`${status.data.stages.chunking}% generated`} /><Metric label="Processed storage" value={formatBytes(status.data.totals.bytes)} helper="Across G: and D:" /></section>
        <section className="pipeline-card">
          <div className="section-heading"><div><span className="eyebrow">Pipeline</span><h2>Preparation stages</h2></div><span>Updated {new Date(status.data.last_updated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span></div>
          <div className="stage-grid">
            <Stage icon={FileStack} label="Ingestion" value={status.data.stages.ingestion} helper="Canonical JSONL" />
            <Stage icon={Layers3} label="Chunking" value={status.data.stages.chunking} helper="BGE-safe passages" />
            <Stage icon={Sparkles} label="Embedding" value={status.data.stages.embedding} helper="BGE base v1.5" />
            <Stage icon={SearchCheck} label="Indexing" value={status.data.stages.indexing} helper="FAISS + FTS5" />
          </div>
        </section>
        <section className="corpus-chart-card">
          <div className="section-heading"><div><span className="eyebrow">Dense coverage</span><h2>Embedding progress by source</h2></div><span>{format.format(status.data.totals.embedded_chunks)} vectors written</span></div>
          <div className="coverage-chart" role="img" aria-label="Bar chart showing dense embedding coverage by corpus source">
            <ResponsiveContainer width="100%" height={210}>
              <BarChart data={status.data.sources.map((source) => ({ name: source.label.replace("Wikipedia Biology", "Wikipedia").replace("PubMed abstracts", "PubMed").replace("PMC open-access papers", "PMC OA").replace("UniProtKB / Swiss-Prot", "UniProt"), coverage: source.chunks ? Math.round(source.embedded_chunks / source.chunks * 100) : 0 }))} margin={{ top: 12, right: 12, left: -25, bottom: 0 }}>
                <CartesianGrid stroke="#e8ede9" vertical={false} />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: "#71817e", fontSize: 9 }} />
                <YAxis domain={[0, 100]} axisLine={false} tickLine={false} tick={{ fill: "#899692", fontSize: 8 }} />
                <Tooltip cursor={{ fill: "#edf5f1" }} contentStyle={{ border: "1px solid #dce3de", borderRadius: 8, fontSize: 10 }} formatter={(value) => [`${value}%`, "Dense coverage"]} />
                <Bar dataKey="coverage" fill="#2d786f" radius={[5, 5, 0, 0]} maxBarSize={48} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
        <section className="source-section">
          <div className="section-heading"><div><span className="eyebrow">Coverage</span><h2>Sources in the active corpus</h2></div><span>{status.data.sources.length} shown of {status.data.totals.sources}</span></div>
          <div className="source-table" role="table" aria-label="Corpus source progress"><div className="source-table__head" role="row"><span>Source</span><span>Documents</span><span>Chunks</span><span>Dense coverage</span><span>Status</span></div>{status.data.sources.map((source) => { const coverage = source.chunks ? Math.round(source.embedded_chunks / source.chunks * 100) : 0; return <div role="row" key={source.source_id}><span className="source-name"><i>{source.label.slice(0, 2).toUpperCase()}</i><span><strong>{source.label}</strong><small>{source.source_type} · {source.license_id}</small></span></span><span data-label="Documents">{format.format(source.documents)}</span><span data-label="Chunks">{format.format(source.chunks)}</span><span className="coverage-cell" data-label="Dense coverage"><ProgressBar value={coverage} /><small>{coverage}%</small></span><span data-label="Status"><StatusPill tone={source.status === "ready" ? "success" : source.status === "warning" ? "danger" : "warning"}>{source.status}</StatusPill></span></div>; })}</div>
        </section>
        <section className="storage-note"><HardDrive size={20} /><div><strong>Separated by purpose</strong><p>Canonical documents remain on G:. Chunk outputs are written to <code>D:\aura_data\AURA-Bio-Processed\02_chunks</code>.</p></div><Database size={22} /></section>
      </>}
    </div>
  );
}

function Stage({ icon: Icon, label, value, helper }: { icon: typeof Database; label: string; value: number; helper: string }) {
  return <div className="stage-card"><div><span><Icon size={18} /></span>{value === 100 && <CheckCircle2 size={16} className="complete-icon" />}</div><strong>{label}</strong><small>{helper}</small><ProgressBar value={value} label={`${label} ${value}%`} /><b>{value}%</b></div>;
}
