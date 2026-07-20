import type {
  Answer,
  Capabilities,
  Citation,
  CorpusStatus,
  HealthStatus,
  RetrievalMode,
  RetrievalResult,
  Run,
  RunRequest,
  RunSummary,
  RunStreamEvent,
  ProcessSummary,
  TraceEvent,
} from "../types";

export const citations: Citation[] = [
  {
    citation_id: "cit-1",
    source_id: "nlm_litarch_biology",
    source_title: "Molecular Biology of the Cell",
    source_type: "textbook",
    section: "The proton-motive force",
    chunk_id: "chunk:8e4f1c2",
    excerpt:
      "Electron transfer through respiratory-chain complexes is coupled to proton translocation, establishing an electrochemical gradient across the inner mitochondrial membrane.",
    license_id: "NLM-LitArch item licence",
    dense_score: 0.91,
    sparse_score: 7.82,
    rerank_score: 0.96,
    rank: 1,
    url: "https://www.ncbi.nlm.nih.gov/books/",
    source_path: "02_Textbooks/normalized/nlm_litarch_biology/sample.nxml",
  },
  {
    citation_id: "cit-2",
    source_id: "wikipedia_biology",
    source_title: "Oxidative phosphorylation",
    source_type: "encyclopedia",
    section: "ATP synthase",
    chunk_id: "chunk:42b1d93",
    excerpt:
      "ATP synthase allows protons to flow down their electrochemical gradient and couples that movement to ATP formation from ADP and phosphate.",
    license_id: "CC-BY-SA-4.0",
    dense_score: 0.88,
    sparse_score: 6.94,
    rerank_score: 0.92,
    rank: 2,
    url: "https://en.wikipedia.org/wiki/Oxidative_phosphorylation",
    source_path: "01_Literature/raw/wikipedia_biology/biology-pages-00001.json",
  },
  {
    citation_id: "cit-3",
    source_id: "pmc_oa_comm_xml",
    source_title: "Mitochondrial respiratory chain organization",
    source_type: "research paper",
    section: "Mechanistic overview",
    chunk_id: "chunk:c9037aa",
    excerpt:
      "The magnitude of the proton-motive force reflects both the membrane potential and the transmembrane pH gradient, which jointly drive ATP synthesis.",
    license_id: "CC-BY-4.0",
    dense_score: 0.86,
    sparse_score: 5.18,
    rerank_score: 0.89,
    rank: 3,
    url: "https://pmc.ncbi.nlm.nih.gov/",
    source_path: "01_Literature/raw/pmc_oa_comm_xml/pmc-commercial-00001.xml",
  },
];

export const demoAnswer: Answer = {
  markdown: `## Core idea

The electron transport chain does **not** make most ATP directly. Instead, it converts energy from electrons into a proton gradient — a stored form of potential energy. [1](#citation-cit-1)

### The mechanism

1. **NADH and FADH₂ donate high-energy electrons** to protein complexes in the inner mitochondrial membrane.
2. As electrons move through the chain, complexes I, III and IV use the released energy to pump H⁺ from the matrix into the intermembrane space.
3. This creates the **proton-motive force**, combining a voltage difference with a pH difference. [3](#citation-cit-3)
4. Protons then return through ATP synthase. Their movement rotates part of the enzyme and drives **ADP + Pᵢ → ATP**. [2](#citation-cit-2)

> Think of the chain as charging a biological battery; ATP synthase is the motor connected to that battery.

### Check your understanding

Why would ATP production fall if the inner mitochondrial membrane became freely permeable to protons?`,
  citations,
  confidence: "high",
  confidence_rationale: "Three mutually consistent sources support the mechanism and terminology.",
  verification_status: "verified",
  revised: true,
  limitations: ["The explanation omits detailed Q-cycle stoichiometry."],
  latency_ms: 4280,
};

const now = Date.now();
export const traceEvents: TraceEvent[] = [
  {
    event_id: "evt-routing",
    stage: "routing",
    status: "completed",
    timestamp: new Date(now - 4200).toISOString(),
    duration_ms: 84,
    model: "Qwen 3.6 local",
    summary: "Classified as a guided cellular-biology explanation.",
    details: { task: "mechanism explanation", subdomain: "cell biology", context_depth: "expanded" },
  },
  {
    event_id: "evt-retrieval",
    stage: "retrieval",
    status: "completed",
    timestamp: new Date(now - 4050).toISOString(),
    duration_ms: 436,
    model: "BGE base v1.5 + FTS5",
    summary: "Hybrid search selected 12 candidates from 3 source families.",
    details: { dense_candidates: 50, sparse_candidates: 50, fused: 32, selected: 12 },
  },
  {
    event_id: "evt-evidence",
    stage: "evidence",
    status: "completed",
    timestamp: new Date(now - 3500).toISOString(),
    duration_ms: 118,
    summary: "Selected three complementary passages with source diversity.",
  },
  {
    event_id: "evt-generation",
    stage: "generation",
    status: "completed",
    timestamp: new Date(now - 3300).toISOString(),
    duration_ms: 2088,
    model: "Qwen 3.6 local",
    token_usage: 774,
    summary: "Generated a level-adapted answer with source markers.",
  },
  {
    event_id: "evt-verification",
    stage: "verification",
    status: "completed",
    timestamp: new Date(now - 1100).toISOString(),
    duration_ms: 368,
    summary: "Six claims supported; one analogy was qualified.",
    details: { supported_claims: 6, unsupported_claims: 0, terminology_issues: 0 },
  },
  {
    event_id: "evt-revision",
    stage: "revision",
    status: "completed",
    timestamp: new Date(now - 650).toISOString(),
    duration_ms: 521,
    model: "Qwen 3.6 local",
    token_usage: 168,
    summary: "Clarified that the pH gradient and membrane potential jointly store energy.",
  },
  {
    event_id: "evt-complete",
    stage: "complete",
    status: "completed",
    timestamp: new Date(now).toISOString(),
    summary: "Answer completed with on-device verification.",
  },
];

export const demoRequest: RunRequest = {
  query: "How does the electron transport chain create ATP?",
  learner_level: "undergraduate",
  teaching_mode: "guided",
  response_length: "balanced",
  context_depth: "expanded",
  source_types: [],
  allow_external_critic: false,
};

export const demoRun: Run = {
  run_id: "run-demo-4821",
  status: "completed",
  query: demoRequest.query,
  request: demoRequest,
  answer: demoAnswer,
  trace: traceEvents,
  created_at: new Date(now - 4500).toISOString(),
};

export const demoProcesses: ProcessSummary[] = [
  {
    process_id: "process-chunking",
    label: "Chunk generation",
    detail: "UniProt final shard · 1 worker",
    progress: 99,
    status: "running",
    helper: "11,201 of 11,202 shard outputs committed",
  },
  {
    process_id: "process-sparse-index",
    label: "Sparse index refresh",
    detail: "FTS5 incremental build",
    progress: 61,
    status: "running",
    helper: "Searchable while refreshing",
  },
  {
    process_id: "process-embedding",
    label: "Dense embedding",
    detail: "BGE base v1.5 · GTX 1650",
    progress: 8,
    status: "queued",
    helper: "Waiting for chunk generation",
  },
];

export const demoRuns: RunSummary[] = [
  {
    run_id: "run-demo-4821",
    query: "How does the electron transport chain create ATP?",
    status: "completed",
    teaching_mode: "guided",
    external_critic_used: false,
    duration: "4.3s",
  },
  {
    run_id: "run-demo-4818",
    query: "Compare mitosis and meiosis for an exam.",
    status: "completed",
    teaching_mode: "exam",
    external_critic_used: true,
    duration: "6.8s",
  },
  {
    run_id: "run-demo-4814",
    query: "Explain operon regulation step by step.",
    status: "completed",
    teaching_mode: "socratic",
    external_critic_used: false,
    duration: "5.1s",
  },
];

export const health: HealthStatus = {
  status: "partial",
  backend: true,
  model: true,
  retrieval: true,
  index_ready: false,
  version: "0.1.0-dev",
};

export const capabilities: Capabilities = {
  local_models: ["Qwen 3.6 local", "Qwen 3.6 compact"],
  teaching_modes: ["direct", "guided", "socratic", "exam", "revision", "research", "teach_back"],
  retrieval_modes: ["bm25", "dense", "hybrid", "reranked"],
  external_critic_available: true,
};

export const corpusStatus: CorpusStatus = {
  stages: { ingestion: 100, chunking: 99, embedding: 8, indexing: 61 },
  totals: {
    sources: 10,
    documents: 8_746_212,
    chunks: 4_928_340,
    embedded_chunks: 389_120,
    bytes: 42_718_338_048,
  },
  index_ready: false,
  sparse_ready: true,
  dense_ready: true,
  last_updated: new Date().toISOString(),
  sources: [
    { source_id: "pubmed_filtered", label: "PubMed abstracts", source_type: "Literature", documents: 7_903_422, chunks: 3_206_820, embedded_chunks: 120_000, bytes: 16_148_000_000, status: "processing", license_id: "NLM PubMed Terms" },
    { source_id: "pmc_oa_comm_xml", label: "PMC open-access papers", source_type: "Literature", documents: 123_100, chunks: 1_102_880, embedded_chunks: 92_100, bytes: 14_956_000_000, status: "processing", license_id: "Item-level OA licence" },
    { source_id: "wikipedia_biology", label: "Wikipedia Biology", source_type: "Reference", documents: 84_650, chunks: 392_140, embedded_chunks: 105_020, bytes: 1_181_000_000, status: "processing", license_id: "CC-BY-SA-4.0" },
    { source_id: "uniprot_sprot", label: "UniProtKB / Swiss-Prot", source_type: "Knowledge base", documents: 575_503, chunks: 187_900, embedded_chunks: 61_000, bytes: 4_211_000_000, status: "ready", license_id: "CC-BY-4.0" },
    { source_id: "gene_ontology", label: "Gene Ontology", source_type: "Knowledge base", documents: 44_324, chunks: 38_600, embedded_chunks: 11_000, bytes: 33_000_000, status: "ready", license_id: "CC-BY-4.0" },
  ],
};

export function retrievalResults(mode: RetrievalMode): RetrievalResult[] {
  return citations.map((citation, index) => ({
    ...citation,
    text: citation.excerpt,
    mode,
    score:
      mode === "bm25"
        ? (citation.sparse_score ?? 0) / 10
        : mode === "dense"
          ? citation.dense_score ?? 0
          : mode === "reranked"
            ? citation.rerank_score ?? 0
            : 0.93 - index * 0.05,
    bm25_rank: [2, 1, 5][index],
    dense_rank: [1, 3, 2][index],
    hybrid_rank: [1, 2, 3][index],
    reranked_rank: [1, 2, 3][index],
  }));
}

const delay = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export async function streamDemoRun(onEvent: (event: RunStreamEvent) => void, signal?: AbortSignal) {
  for (const event of traceEvents.slice(0, 4)) {
    if (signal?.aborted) return;
    await delay(180);
    onEvent({ type: "trace", event });
  }
  const parts = demoAnswer.markdown.split(/(?<=\s)/);
  for (let index = 0; index < parts.length; index += 8) {
    if (signal?.aborted) return;
    await delay(22);
    onEvent({ type: "answer.delta", delta: parts.slice(index, index + 8).join("") });
  }
  for (const event of traceEvents.slice(4)) {
    if (signal?.aborted) return;
    await delay(150);
    onEvent({ type: "trace", event });
  }
  onEvent({ type: "answer.completed", answer: demoAnswer });
}
