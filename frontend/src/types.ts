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
export type VerificationStatus = "verified" | "partial" | "unsupported" | "pending" | 'interpreted' | 'transcribed' | 'annotated';

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
  dense_score?: number | null;
  sparse_score?: number | null;
  rerank_score?: number | null;
  rank: number;
  source_path?: string;
  pack_id?: string;
  document_id?: string;
  unit_ids?: string[];
  locators?: StudyLocator[];
  generation?: number;
  preview_url?: string;
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
  visuals?: AnswerVisualResult[];
  delivery?: {status: string; delivered_ids: string[]; omitted: {id: string; reason: string}[]} | null;
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
  evidence_scope?: 'core' | 'pack_only';
  pack_id?: string | null;
  attachment_id?: string | null;
  context_pack_id?: string | null;
  think?: boolean;
  figure_ids?: string[];
  answer_mode?: 'tutor' | 'strict';
  visual_output?: VisualOutput;
}

export type VisualOutput = 'none' | 'auto' | 'source' | 'diagram' | 'comparison' | 'procedure' | 'plot';
export interface VisualSupport {claim_ids:string[];cite_ids:string[];status:'native_verified'|'interpreted'|'ocr_transcribed'|'user_annotated'|'native_unverified';provenance:string[];}
export interface VisualBinding {cite_id:number;start:number;end:number;}
interface VisualBase {version:1;id:string;title:string;description:string;sources?:{citation_id:string;title:string;pack_id?:string|null;document_id?:string|null;unit_ids:string[];locators:StudyLocator[];provenance:string;}[];}
export interface SourceVisualV1 extends VisualBase {kind:'source';payload:{claim_ids:string[];pack_id:string;document_id:string;unit_id:string;asset_id:string|null;bbox:NormalizedBox|null;support:VisualSupport;revision_id:string;source_checksum:string;asset_checksum:string|null;generation:number;locators:StudyLocator[];coordinates:'upright_normalized';highlight_precision:'region'|'whole_asset'|'unit_only';resolved:boolean;};}
interface SourceVisualV2 extends Omit<SourceVisualV1,'version'|'payload'> {version:2;payload:Omit<SourceVisualV1['payload'],'highlight_precision'>&{highlight_precision:'region'|'whole_asset'|'unit_only'|'panel'|'table_row';highlights:{id:string;bbox:NormalizedBox;precision:'region'|'panel'|'table_row'}[];warnings:string[];geometry_revision_ids:string[]};}
export type SourceVisualSpec = SourceVisualV1|SourceVisualV2;
export interface VisualNode {id:string;label:string;claim_ids:string[];support:VisualSupport;}
export interface VisualEdge {from_id:string;to_id:string;relation:'precedes'|'part_of'|'associated_with'|'activates'|'inhibits'|'causes'|'visible_arrow';label:string;claim_ids:string[];support:VisualSupport;}
export interface DiagramVisualV1 extends VisualBase {kind:'diagram';payload:{nodes:VisualNode[];edges:VisualEdge[];};}
export interface DiagramVisualV2 extends Omit<DiagramVisualV1,'version'|'payload'> {version:2;payload:{orientation:'TD'|'LR';layout:'pathway'|'cycle'|'hierarchy';nodes:(VisualNode&{role:'entity'|'process'|'condition'})[];edges:(VisualEdge&{qualifiers:string[];conditions:string[];bindings:VisualBinding[]})[];groups:{id:string;label:string;node_ids:string[];mode:'presentation'|'containment';claim_ids:string[];bindings:VisualBinding[];support?:VisualSupport}[]};}
export type DiagramVisualSpec=DiagramVisualV1|DiagramVisualV2;
export interface BoundVisualText {text:string;claim_ids:string[];bindings:VisualBinding[];support:VisualSupport;}
export interface ComparisonVisualSpec extends VisualBase {kind:'comparison';payload:{columns:(BoundVisualText&{id:string})[];rows:{id:string;criterion:BoundVisualText;cells:{column_id:string;text:string;status:'stated'|'not_stated';claim_ids:string[];bindings:VisualBinding[];support?:VisualSupport;}[];}[];};}
export interface ProcedureVisualSpec extends VisualBase {kind:'procedure';payload:{steps:{id:string;text:string;claim_ids:string[];support:VisualSupport;}[];precedes:{from_id:string;to_id:string;claim_ids:string[];support:VisualSupport;}[];ordering:'total'|'partial';};}
export interface VisualPoint {group:string;value:string|null;x?:string;claim_ids:string[];bindings:Record<string,VisualBinding>;support:VisualSupport;}
export interface PlotVisualV1 extends VisualBase {kind:'plot';payload:{chart_type:'bar'|'line'|'scatter';x_label:string;y_label:string;unit:string;x_unit?:string;series:{id:string;label:string;unit:string;points:VisualPoint[];}[];};}
export type PlotUncertainty={kind:'SD'|'SEM';magnitude:string;bindings:Record<string,VisualBinding>}|{kind:'CI'|'source_interval';lower:string;upper:string;level?:string;bindings:Record<string,VisualBinding>};
export interface VisualPointV2 extends VisualPoint {id:string;quantity:string;origin:'source_observation';population?:string;condition?:string;column?:string;bin_lower?:string;bin_upper?:string;uncertainty:PlotUncertainty|null;}
export interface PlotVisualV2 extends Omit<PlotVisualV1,'version'|'payload'> {version:2;payload:Omit<PlotVisualV1['payload'],'chart_type'|'series'>&{chart_type:'bar'|'line'|'scatter'|'heatmap'|'distribution';x_scale:'linear'|'log';y_scale:'linear'|'log';distribution_mode?:'source_bins'|'samples';series:{id:string;label:string;unit:string;identity:BoundVisualText;points:VisualPointV2[]}[]};}
export type PlotVisualSpec=PlotVisualV1|PlotVisualV2;
export type VisualSpec = SourceVisualSpec|DiagramVisualSpec|ComparisonVisualSpec|ProcedureVisualSpec|PlotVisualSpec;
export interface AnswerVisualResult {status:'ready'|'omitted'|'failed';spec:VisualSpec|null;limitations:string[];metadata?:Record<string,unknown>;}

export interface Run {
  run_id: string;
  status: "queued" | "running" | "completed" | "failed";
  query: string;
  request: RunRequest;
  answer?: Answer;
  trace: TraceEvent[];
  created_at: string;
  source_pack_ids?: string[];
}

export type RunStreamEvent =
  | { type: "trace"; event: TraceEvent }
  | { type: "answer.delta"; delta: string }
  | { type: "answer.completed"; answer: Answer }
  | { type: "run.failed"; error: string }
  | { type: 'run.invalidated'; code: string; message: string };

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

export interface EvaluationSystem {
  id: string;
  label: string;
  detail: string;
  srs_config: number;
}

export interface EvaluationSummary {
  total: number;
  by_subdomain: Record<string, number>;
  by_task_type: Record<string, number>;
  by_level: Record<string, number>;
  by_difficulty: Record<string, number>;
  numeric_items: number;
  process_items: number;
  adversarial_items: number;
  systems: EvaluationSystem[];
  metrics: string[];
}

/**
 * One completed run as reported by `GET /api/v1/runs`.
 *
 * These are the facts the teaching-quality and failure-review panels
 * aggregate. They come from the pipeline's own trace, so every number here
 * describes work the system actually did.
 */
export interface RecentRun {
  evidence_scope?: 'core' | 'pack_only';
  pack_id?: string | null;
  run_id: string;
  query: string;
  status: "completed" | "failed";
  created_at: string;
  external_critic_used: boolean;
  decision: string;
  confidence: number;
  provenance: {
    claims?: number;
    cited_claims?: number;
    citations?: number;
    valid_citations?: number;
    dangling_citations?: number;
    distinct_sources?: number;
    claim_citation_rate?: number;
    citation_validity?: number;
    unsupported_assertion_rate?: number;
  };
  task_type: string | null;
  subdomain: string | null;
  learner_level: string | null;
  teaching_mode: string | null;
  passes: number;
  revised: boolean;
  failure_category: string | null;
  evidence_count: number;
  stage_ms: Record<string, number>;
  latency_ms: number;
}

export interface RecentRunsResponse {
  runs: RecentRun[];
  total: number;
}

export interface StudyLocator {
  kind: string; page?: number; page_label?: string; slide?: number; shape_id?: string;
  sheet?: string; cell_range?: string; start_line?: number; end_line?: number; role?: string;
}
export interface StudyPack {
  pack_id: string; name: string; domain: 'general' | 'biology'; created_at: number;
  state: string; generation: number;
  retention?: 'saved'|'temporary'; expires_at?: number|null; lifecycle_schema?: number;
}
export interface ImageAttachment {
  attachment_id:string; pack:StudyPack; document:StudyDocument; job:StudyJob|null;
  visual_jobs:StudyJob[]; processing:boolean; usable:boolean; pending_cleanup:boolean; cleanup_error:string|null;
  preview_asset_id?:string|null;
}
export interface StudyDocument {
  document_id: string; pack_id: string; filename: string; kind: string; checksum: string;
  state: string; active: boolean; warnings: string[]; coverage: Record<string, number>; parser_version: string;
}
export interface StudyJob {
  job_id: string; pack_id: string; document_id?: string | null; state: string; error?: string | null;
}
export interface StudyUnit {
  unit_id: string; document_id: string; ordinal: number; role: string; title: string; breadcrumb: string;
  text: string; locators: StudyLocator[]; metadata: Record<string, unknown>; asset_ids: string[];
  provenance?: SourceMethod; provenance_details?: Record<string, unknown>;
}

export type SourceMethod='native_text' | 'ocr' | 'vlm' | 'user_annotation';
export interface NormalizedBox { x0:number; y0:number; x1:number; y1:number; }
export interface StudyFigure {
  figure_id:string; unit_id:string; asset_id:string; document_id:string; locator:StudyLocator;
  bbox:NormalizedBox; frame:'page_normalized'|'asset_normalized'; reason:string;
  context_hash:string; checksum:string; exclusion_reason:string|null;
  figure_label?:string; caption?:string; reference_kind?:'figure'|'table';
}
export interface VisualConfig {
  provider:'ollama'|'groq'|'ocr'; model:string; managed_swap?:boolean;
  question?:string;
  description_version?:1|2; focus?:boolean;
  think?:boolean; num_predict?:number; timeout_seconds?:number;
  consent?:{external_allowed:boolean;images:boolean;hints:boolean;disclosure_version:string};
}
export interface VisualJob extends StudyJob {
  config:VisualConfig; tokens_used:number;
  indexed?:boolean; index_error?:string|null;
  checkpoints:{item_id:string;state:string;attempts:number;error:string|null;revision_id:string|null;resume_at:number|null}[];
}
export interface VisualPayloadPreview {
  preview_hash:string; provider:string; model:string; disclosure:string;
  figures:{figure_id:string;image_bytes:number;ocr_hint:string;caption_hint:string;crop_sha256:string}[];
}
