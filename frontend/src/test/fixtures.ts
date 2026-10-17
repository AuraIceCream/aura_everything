import type { Answer, Citation, TraceEvent } from "../types";

/**
 * Fixtures for component and hook tests only.
 *
 * The application itself has no sample-data path: every page reads from the
 * backend. These live under src/test/ so they cannot be imported by app code
 * by accident.
 */

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

