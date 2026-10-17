import { beforeEach, expect, it } from 'vitest';
import { archiveRun, archiveSummary, archivedRuns, clearPackArchive } from './trace-store';
import type { Run } from '../types';
const fixtureRun = { run_id: 'core', request: { query: 'core question' } } as Run;

beforeEach(() => localStorage.clear());
it('does not archive private pack runs or summaries', () => {
  const privateRun = { ...fixtureRun, request: { ...fixtureRun.request, evidence_scope: 'pack_only' as const, pack_id: 'pack-one' } };
  archiveRun(privateRun);
  archiveSummary({ run_id: 'private', query: 'secret', status: 'completed', created_at: '', evidence_scope: 'pack_only', pack_id: 'pack-one' } as never);
  expect(localStorage.length).toBe(0);
});
it('removes legacy pack records while retaining core archives', () => {
  archiveRun(fixtureRun);
  localStorage.setItem('aura-trace-run:private', JSON.stringify({ request: { pack_id: 'pack-one' } }));
  localStorage.setItem('aura-trace-index', JSON.stringify([{ run_id: 'private', pack_id: 'pack-one' }, { run_id: fixtureRun.run_id }]));
  clearPackArchive('pack-one');
  expect(localStorage.getItem('aura-trace-run:private')).toBeNull();
  expect(localStorage.getItem('aura-trace-run:' + fixtureRun.run_id)).not.toBeNull();
  expect(archivedRuns()).toHaveLength(1);
});
