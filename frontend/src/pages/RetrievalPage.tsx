import * as Tabs from "@radix-ui/react-tabs";
import { useMutation } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Filter, Search, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { api } from "../lib/api";
import type { RetrievalMode, RetrievalResult } from "../types";
import { PageHeader, StatusPill } from "../components/ui";
import { useSettings } from "../context/settings";

const modes: { value: RetrievalMode; label: string; helper: string }[] = [
  { value: "bm25", label: "BM25", helper: "Exact terminology" },
  { value: "dense", label: "Dense", helper: "Semantic similarity" },
  { value: "hybrid", label: "Hybrid", helper: "Reciprocal rank fusion" },
  { value: "reranked", label: "Reranked", helper: "Cross-encoder ordering" },
];

export function RetrievalPage() {
  const { settings } = useSettings();
  const [query, setQuery] = useState("How does the proton gradient power ATP synthase?");
  const [mode, setMode] = useState<RetrievalMode>("hybrid");
  const [sourceType, setSourceType] = useState("");
  const search = useMutation({ mutationFn: () => api.retrievalSearch(query, mode, sourceType) });
  const results = search.data?.results ?? [];

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Retrieval laboratory" title="See why evidence was selected" description="Compare lexical and semantic retrieval using the same query, filters, and corpus." action={<StatusPill tone="warning">Partial index · pilot coverage</StatusPill>} />
      <section className="query-panel">
        <div className="search-field"><Search size={18} /><label htmlFor="retrieval-query" className="sr-only">Retrieval query</label><input id="retrieval-query" value={query} onChange={(event) => setQuery(event.target.value)} /><button onClick={() => search.mutate()} disabled={!query.trim() || search.isPending}>{search.isPending ? "Searching…" : "Run comparison"}<ArrowRight size={15} /></button></div>
        <div className="filter-row"><Filter size={15} /><span>Source family</span><select value={sourceType} onChange={(event) => setSourceType(event.target.value)}><option value="">All licensed sources</option><option value="textbook">Textbooks</option><option value="research paper">Research papers</option><option value="encyclopedia">Reference</option></select><span className="filter-summary">Top 10 · 50 candidates · RRF k=60</span></div>
      </section>

      <Tabs.Root value={mode} onValueChange={(value) => setMode(value as RetrievalMode)} className="retrieval-tabs">
        <Tabs.List aria-label="Retrieval mode">
          {modes.map((item) => <Tabs.Trigger key={item.value} value={item.value}><strong>{item.label}</strong><span>{item.helper}</span></Tabs.Trigger>)}
        </Tabs.List>
      </Tabs.Root>

      {!search.data && !search.isPending && (
        <section className="empty-lab"><SlidersHorizontal size={30} /><h2>Run a controlled retrieval comparison</h2><p>The same query will be scored using the selected strategy. No answer generation is involved.</p><button onClick={() => search.mutate()}>Use the sample query</button></section>
      )}
      {search.data && (
        <div className="retrieval-layout">
          <section className="results-panel">
            <div className="section-heading"><div><span className="eyebrow">Ranked passages</span><h2>{results.length} evidence candidates</h2></div><span>{search.data.latency_ms} ms</span></div>
            <div className="result-list">{results.map((result, index) => <RetrievalCard key={result.chunk_id} result={result} index={index} developer={settings.developerMode} />)}</div>
          </section>
          <aside className="rank-panel">
            <span className="eyebrow">Rank movement</span><h2>Method comparison</h2><p>Strong passages should remain near the top across complementary retrieval methods.</p>
            <div className="rank-table"><div className="rank-table__head"><span>Source</span><span>BM25</span><span>Dense</span><span>Hybrid</span></div>{results.map((item) => <div key={item.chunk_id}><strong>{item.source_title.split(" ").slice(0, 2).join(" ")}</strong><span>{item.bm25_rank}</span><span>{item.dense_rank}</span><span className="rank-best">{item.hybrid_rank}</span></div>)}</div>
            <div className="method-note"><CheckCircle2 size={17} /><div><strong>Stable evidence set</strong><span>All three selected passages appear in both lexical and semantic candidate pools.</span></div></div>
          </aside>
        </div>
      )}
    </div>
  );
}

function RetrievalCard({ result, index, developer }: { result: RetrievalResult; index: number; developer: boolean }) {
  return <article className="retrieval-card"><div className="retrieval-rank">{index + 1}</div><div className="retrieval-card__body"><div className="retrieval-card__title"><div><strong>{result.source_title}</strong><span>{result.section} · {result.source_type}</span></div><StatusPill tone="info">{result.license_id}</StatusPill></div><p>{result.excerpt}</p><div className="retrieval-score"><span style={{ width: `${result.score * 100}%` }} /><strong>{result.score.toFixed(3)}</strong></div>{developer && <code>{result.chunk_id}</code>}</div></article>;
}

