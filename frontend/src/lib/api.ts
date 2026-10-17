import type {
  Capabilities,
  CorpusStatus,
  EvaluationSummary,
  HealthStatus,
  RecentRunsResponse,
  RetrievalMode,
  RetrievalResponse,
  Run,
  RunRequest,
  RunStreamEvent,
  StudyPack, StudyDocument, StudyJob, StudyUnit,
  ImageAttachment,
  StudyFigure,NormalizedBox,VisualConfig,VisualJob,VisualPayloadPreview,
} from "../types";

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(message:string, public status:number, public code?:string) { super(message); this.name='ApiError'; }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: 'no-store',
    headers: { ...(!(init?.body instanceof FormData) && { "Content-Type": "application/json" }), ...init?.headers },
  });
  if (!response.ok) {
    // The backend returns {"detail": "..."} for handled errors. Surfacing that
    // text matters: an out-of-memory failure names the component to switch off,
    // and losing it leaves only an opaque status code.
    let detail = `Request failed (${response.status})`;
    let code:string|undefined;
    try {
      const body = await response.json();
      if (body?.detail) detail = typeof body.detail === 'object' ? (body.detail.message ?? JSON.stringify(body.detail)) : String(body.detail);
      code=body?.detail?.code;
    } catch {
      /* response had no JSON body; keep the status-code message */
    }
    throw new ApiError(detail,response.status,code);
  }
  return response.json() as Promise<T>;
}

export const api = {
  attachments: {
    upload:(file:File,signal?:AbortSignal)=>{ const body=new FormData();body.append('file',file);return request<ImageAttachment>('/api/v1/study-attachments',{method:'POST',body,signal}); },
    status:(id:string)=>request<ImageAttachment>(`/api/v1/study-attachments/${encodeURIComponent(id)}`),
    save:(id:string,name:string)=>request<StudyPack>(`/api/v1/study-attachments/${encodeURIComponent(id)}/save`,{method:'POST',body:JSON.stringify({name})}),
    remove:(id:string,confirmation:string)=>request<{deleted:boolean}>(`/api/v1/study-attachments/${encodeURIComponent(id)}`,{method:'DELETE',body:JSON.stringify({confirmation})}),
  },
  studyPacks: {
    resolveVisualQuestion:(pack:string,question:string,signal?:AbortSignal)=>request<{figures:StudyFigure[];warnings:string[]}>(`/api/v1/study-packs/${encodeURIComponent(pack)}/visual-question`,{method:'POST',body:JSON.stringify({question}),signal}),
    figures:(pack:string,doc:string)=>request<{figures:StudyFigure[];external_allowed:boolean;warnings?:string[]}>(`/api/v1/study-packs/${encodeURIComponent(pack)}/documents/${encodeURIComponent(doc)}/figures`),
    crop:(pack:string,doc:string,figure_id:string,bbox:NormalizedBox)=>request<StudyFigure>(`/api/v1/study-packs/${encodeURIComponent(pack)}/documents/${encodeURIComponent(doc)}/figures/crops`,{method:'POST',body:JSON.stringify({figure_id,bbox})}),
    revisions:(pack:string,doc:string,figure:string)=>request<{revisions:(StudyUnit & {active:boolean})[]}>(`/api/v1/study-packs/${encodeURIComponent(pack)}/documents/${encodeURIComponent(doc)}/figures/${encodeURIComponent(figure)}/revisions`),
    annotate:(pack:string,doc:string,figure:string,text:string)=>request<StudyUnit>(`/api/v1/study-packs/${encodeURIComponent(pack)}/documents/${encodeURIComponent(doc)}/figures/${encodeURIComponent(figure)}/annotations`,{method:'POST',body:JSON.stringify({text})}),
    visualPermission:(pack:string,allowed:boolean)=>request<{external_allowed:boolean}>(`/api/v1/study-packs/${encodeURIComponent(pack)}/visual-permission`,{method:'PUT',body:JSON.stringify({allowed})}),
    visualPreview:(pack:string,figure_ids:string[],config:VisualConfig)=>request<VisualPayloadPreview>(`/api/v1/study-packs/${encodeURIComponent(pack)}/visual-jobs/preview`,{method:'POST',body:JSON.stringify({figure_ids,config})}),
    visualStart:(pack:string,figure_ids:string[],config:VisualConfig,preview_hash?:string)=>request<StudyJob>(`/api/v1/study-packs/${encodeURIComponent(pack)}/visual-jobs`,{method:'POST',body:JSON.stringify({figure_ids,config,preview_hash})}),
    visualStatus:(pack:string,job:string)=>request<VisualJob>(`/api/v1/study-packs/${encodeURIComponent(pack)}/visual-jobs/${encodeURIComponent(job)}`),
    visualList:(pack:string,doc:string)=>request<{jobs:StudyJob[]}>(`/api/v1/study-packs/${encodeURIComponent(pack)}/visual-jobs?document_id=${encodeURIComponent(doc)}`),
    visualAction:(pack:string,job:string,action:'pause'|'cancel'|'resume')=>request<StudyJob>(`/api/v1/study-packs/${encodeURIComponent(pack)}/visual-jobs/${encodeURIComponent(job)}/${action}`,{method:'POST'}),
    figureUrl:(pack:string,doc:string,figure:string)=>`${API_BASE}/api/v1/study-packs/${encodeURIComponent(pack)}/documents/${encodeURIComponent(doc)}/figures/${encodeURIComponent(figure)}/preview`,
    list: () => request<{ packs: StudyPack[] }>('/api/v1/study-packs'),
    create: (name: string, domain: string) => request<StudyPack>('/api/v1/study-packs', { method: 'POST', body: JSON.stringify({ name, domain }) }),
    detail: (id: string) => request<StudyPack & { documents: StudyDocument[]; pending_purge?: { document_id: string | null } | null }>(`/api/v1/study-packs/${encodeURIComponent(id)}`),
    upload: (id: string, file: File, progress: (percent: number) => void) => new Promise<{ document: StudyDocument; job: StudyJob | null }>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${API_BASE}/api/v1/study-packs/${encodeURIComponent(id)}/documents`);
      xhr.upload.onprogress = (event) => { if (event.lengthComputable) progress(Math.round(event.loaded / event.total * 100)); };
      xhr.onload = () => {
        try {
          const body = JSON.parse(xhr.responseText);
          if (xhr.status >= 200 && xhr.status < 300) resolve(body);
          else reject(new Error(body.detail?.message ?? body.detail ?? `Upload failed (${xhr.status})`));
        } catch { reject(new Error('Upload returned an invalid response.')); }
      };
      xhr.onerror = () => reject(new Error('Upload connection failed.'));
      const body = new FormData(); body.append('file', file); xhr.send(body);
    }),
    status: (id: string) => request<StudyJob>(`/api/v1/study-jobs/${encodeURIComponent(id)}`),
    retry: (id: string) => request<StudyJob>(`/api/v1/study-jobs/${encodeURIComponent(id)}/retry`, { method: 'POST' }),
    units: (pack: string, doc: string, offset = 0) => request<{ units: StudyUnit[]; total: number }>(`/api/v1/study-packs/${encodeURIComponent(pack)}/documents/${encodeURIComponent(doc)}/units?offset=${offset}&limit=100`),
    unit: (pack: string, doc: string, unit: string) => request<StudyUnit>(`/api/v1/study-packs/${encodeURIComponent(pack)}/documents/${encodeURIComponent(doc)}/units/${encodeURIComponent(unit)}`),
    deactivate: (pack: string, doc: string) => request<StudyJob>(`/api/v1/study-packs/${encodeURIComponent(pack)}/documents/${encodeURIComponent(doc)}/deactivate`, { method: 'POST' }),
    purge: (pack: string, confirmation: string, doc?: string) => request<{ deleted: boolean; invalidated_history: boolean }>(`/api/v1/study-packs/${encodeURIComponent(pack)}${doc ? `/documents/${encodeURIComponent(doc)}` : ''}`, { method: 'DELETE', body: JSON.stringify({ confirmation }) }),
    index: (pack: string, dense = false) => request<StudyJob>(`/api/v1/study-packs/${encodeURIComponent(pack)}/index`, { method: 'POST', body: JSON.stringify({ dense }) }),
    search: (pack: string, query: string, mode = 'hybrid') => request(`/api/v1/study-packs/${encodeURIComponent(pack)}/search`, { method: 'POST', body: JSON.stringify({ query, mode }) }),
    originalUrl: (pack: string, doc: string) => `${API_BASE}/api/v1/study-packs/${encodeURIComponent(pack)}/documents/${encodeURIComponent(doc)}/original`,
    assetUrl: (pack: string, doc: string, asset: string) => `${API_BASE}/api/v1/study-packs/${encodeURIComponent(pack)}/documents/${encodeURIComponent(doc)}/assets/${encodeURIComponent(asset)}`,
  },
  health: () => request<HealthStatus>("/api/v1/health"),
  capabilities: () => request<Capabilities>("/api/v1/capabilities"),
  corpusStatus: () => request<CorpusStatus>("/api/v1/corpus/status"),
  evaluationSummary: () => request<EvaluationSummary>("/api/v1/evaluation/summary"),
  recentRuns: (limit = 25) =>
    request<RecentRunsResponse>(`/api/v1/runs?limit=${encodeURIComponent(String(limit))}`),
  createRun: (payload: RunRequest, signal?:AbortSignal) =>
    request<{ run_id: string; status: string }>("/api/v1/runs", {
      method: "POST",
      body: JSON.stringify(payload),
      signal,
    }),
  getRun: (runId: string) => request<Run>(`/api/v1/runs/${encodeURIComponent(runId)}`),
  retrievalSearch: (query: string, mode: RetrievalMode, sourceType?: string) =>
    request<RetrievalResponse>("/api/v1/retrieval/search", {
      method: "POST",
      body: JSON.stringify({ query, mode, source_type: sourceType || null }),
    }),
  streamRun: (
    runId: string,
    onEvent: (event: RunStreamEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> =>
    new Promise((resolve, reject) => {
      const source = new EventSource(`${API_BASE}/api/v1/runs/${encodeURIComponent(runId)}/events`);
      const abort = () => {
        source.close();
        resolve();
      };
      signal?.addEventListener("abort", abort, { once: true });
      source.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as RunStreamEvent;
          onEvent(event);
          if (event.type === "answer.completed" || event.type === "run.failed" || event.type==='run.invalidated') {
            source.close();
            signal?.removeEventListener("abort", abort);
            resolve();
          }
        } catch (error) {
          source.close();
          reject(error);
        }
      };
      source.onerror = () => {
        source.close();signal?.removeEventListener('abort',abort);reject(new Error('Run stream disconnected; private replay is not retried automatically.'));
      };
    }),
};
