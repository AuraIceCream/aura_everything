export type LearnerLevel = "high_school" | "undergraduate" | "postgraduate" | "research";
export type TeachingMode =
  | "direct"
  | "guided"
  | "socratic"
  | "exam"
  | "revision"
  | "research"
  | "teach_back";
export type RetrievalMode = "bm25" | "dense" | "hybrid" | "reranked";
export type ContextDepth = "none" | "standard" | "expanded" | "hierarchical";
export type Confidence = "high" | "medium" | "low";
export type VerificationStatus = "verified" | "partial" | "unsupported" | "pending";

export interface Citation {
  citation_id: string;
  source_id: string;
  source_title: string;
  source_type: string;
  section: string;
  chunk_id: string;
  excerpt: string;
  url?: string;
  license_id: string;
  dense_score?: number;
  sparse_score?: number;
  rerank_score?: number;
  rank: number;
  source_path?: string;
}

export interface Answer {
  markdown: string;
  citations: Citation[];
  confidence: Confidence;
  confidence_rationale: string;
  verification_status: VerificationStatus;
  revised: boolean;
  limitations: string[];
  latency_ms: number;
}

export type TraceStage =
  | "routing"
  | "retrieval"
  | "evidence"
  | "generation"
  | "verification"
  | "critique"
  | "revision"
  | "complete";

export interface TraceEvent {
  event_id: string;
  stage: TraceStage;
  status: "queued" | "running" | "completed" | "skipped" | "failed";
  timestamp: string;
  duration_ms?: number;
  model?: string;
  token_usage?: number;
  api_usage?: boolean;
  summary: string;
  details?: Record<string, unknown>;
  error?: string;
}

export interface RunRequest {
  query: string;
  learner_level: LearnerLevel;
  teaching_mode: TeachingMode;
  response_length: "concise" | "balanced" | "detailed";
  context_depth: ContextDepth;
  source_types: string[];
  allow_external_critic: boolean;
}

export interface Run {
  run_id: string;
  status: "queued" | "running" | "completed" | "failed";
  query: string;
  request: RunRequest;
  answer?: Answer;
  trace: TraceEvent[];
  created_at: string;
}

export type RunStreamEvent =
  | { type: "trace"; event: TraceEvent }
  | { type: "answer.delta"; delta: string }
  | { type: "answer.completed"; answer: Answer }
  | { type: "run.failed"; error: string };

export interface RetrievalResult extends Citation {
  text: string;
  mode: RetrievalMode;
  score: number;
  bm25_rank?: number;
  dense_rank?: number;
  hybrid_rank?: number;
  reranked_rank?: number;
}

export interface RetrievalResponse {
  query: string;
  mode: RetrievalMode;
  latency_ms: number;
  results: RetrievalResult[];
}

export interface SourceProgress {
  source_id: string;
  label: string;
  source_type: string;
  documents: number;
  chunks: number;
  embedded_chunks: number;
  bytes: number;
  status: "ready" | "processing" | "queued" | "warning";
  license_id: string;
}

export interface CorpusStatus {
  stages: {
    ingestion: number;
    chunking: number;
    embedding: number;
    indexing: number;
  };
  totals: {
    sources: number;
    documents: number;
    chunks: number;
    embedded_chunks: number;
    bytes: number;
  };
  index_ready: boolean;
  sparse_ready: boolean;
  dense_ready: boolean;
  last_updated: string;
  sources: SourceProgress[];
}

export interface HealthStatus {
  status: "ready" | "partial" | "offline";
  backend: boolean;
  model: boolean;
  retrieval: boolean;
  index_ready: boolean;
  version: string;
}

export interface Capabilities {
  local_models: string[];
  teaching_modes: TeachingMode[];
  retrieval_modes: RetrievalMode[];
  external_critic_available: boolean;
}

export interface ProcessSummary {
  process_id: string;
  label: string;
  detail: string;
  progress: number;
  status: "running" | "paused" | "queued" | "completed";
  helper: string;
}

export interface RunSummary {
  run_id: string;
  query: string;
  status: "completed" | "running" | "failed";
  teaching_mode: TeachingMode;
  external_critic_used: boolean;
  duration: string;
}
