import type { RecentRun, Run } from "../types";

/**
 * Browser-side archive of runs.
 *
 * The backend keeps runs in memory, so restarting it loses every trace. That
 * is a poor fit for the one page whose whole purpose is retrospective: you
 * come back to a trace precisely because you want to re-examine an answer you
 * have already seen. Mirroring completed runs into localStorage means the
 * history survives a backend restart, a reload, and a machine reboot.
 *
 * The backend stays authoritative while it has the run; this is a fallback,
 * not a cache to read first.
 */

const RUNS_KEY = "aura-trace-index";
const RUN_PREFIX = "aura-trace-run:";
const MAX_ARCHIVED = 100;

function safeParse<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

/** Summaries of every archived run, newest first. */
export function archivedRuns(): RecentRun[] {
  return safeParse<RecentRun[]>(localStorage.getItem(RUNS_KEY), []);
}

/** The full trace for one run, if this browser still holds it. */
export function archivedRun(runId: string): Run | null {
  return safeParse<Run | null>(localStorage.getItem(RUN_PREFIX + runId), null);
}

export function archiveSummary(summary: RecentRun): void {
  if (summary.evidence_scope === 'pack_only' || summary.pack_id) return;
  const existing = archivedRuns().filter((run) => run.run_id !== summary.run_id);
  const next = [summary, ...existing].slice(0, MAX_ARCHIVED);
  try {
    localStorage.setItem(RUNS_KEY, JSON.stringify(next));
  } catch {
    /* quota exceeded: the archive is a convenience, never a requirement */
  }
}

export function archiveRun(run: Run): void {
  if (run.request?.evidence_scope === 'pack_only' || run.request?.pack_id) return;
  try {
    localStorage.setItem(RUN_PREFIX + run.run_id, JSON.stringify(run));
  } catch {
    // Traces carry full answer text and can be large. Rather than fail, drop
    // the oldest archived traces and retry once.
    const index = archivedRuns();
    for (const old of index.slice(Math.floor(MAX_ARCHIVED / 2))) {
      localStorage.removeItem(RUN_PREFIX + old.run_id);
    }
    try {
      localStorage.setItem(RUN_PREFIX + run.run_id, JSON.stringify(run));
    } catch {
      /* still no room; skip archiving this one */
    }
  }
}

/**
 * Server runs first, then any archived run the server no longer holds.
 *
 * Archived-only entries are marked so the interface can say plainly that a
 * trace came from this browser rather than from the running backend.
 */
export function mergeRuns(serverRuns: RecentRun[]): (RecentRun & { archived?: boolean })[] {
  const live = new Set(serverRuns.map((run) => run.run_id));
  const archivedOnly = archivedRuns()
    .filter((run) => !live.has(run.run_id))
    .map((run) => ({ ...run, archived: true }));
  return [...serverRuns, ...archivedOnly];
}

export function clearArchive(): void {
  for (const run of archivedRuns()) localStorage.removeItem(RUN_PREFIX + run.run_id);
  localStorage.removeItem(RUNS_KEY);
}

export function clearPackArchive(packId: string): void {
  const removed = new Set<string>();
  const index = archivedRuns().filter((run) => {
    if (run.pack_id === packId) { removed.add(run.run_id); return false; }
    return true;
  });
  for (let i = localStorage.length - 1; i >= 0; i--) {
    const key = localStorage.key(i);
    if (key?.startsWith(RUN_PREFIX)) {
      const run = safeParse<Run | null>(localStorage.getItem(key), null);
      if (run?.request?.pack_id === packId || removed.has(key.slice(RUN_PREFIX.length))) {
        removed.add(key.slice(RUN_PREFIX.length)); localStorage.removeItem(key);
      }
    }
  }
  const remaining = index.filter((run) => !removed.has(run.run_id));
  if (remaining.length) localStorage.setItem(RUNS_KEY, JSON.stringify(remaining));
  else localStorage.removeItem(RUNS_KEY);
}
