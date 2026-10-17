import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, expect, it, vi } from 'vitest';
import { StudyPacksPage } from './StudyPacksPage';
import { api } from '../lib/api';

vi.mock('../lib/api', () => ({ api: { studyPacks: {
  list: vi.fn(), detail: vi.fn(), units: vi.fn(), unit: vi.fn(), purge: vi.fn(), upload: vi.fn(), status: vi.fn(),
  originalUrl: vi.fn(() => '/original'), assetUrl: vi.fn(() => '/asset'),
  figures:vi.fn().mockResolvedValue({figures:[],external_allowed:false}),
  visualList:vi.fn().mockResolvedValue({jobs:[]}),
} } }));
const pack = { pack_id: 'p', name: 'Course', state: 'sparse-ready', domain: 'general', generation: 1, created_at: 0 };
const doc = { document_id: 'd', pack_id: 'p', filename: 'slides.pptx', kind: 'pptx', state: 'sparse-ready', active: true,
  warnings: ['slide:2:no_text'], coverage: { slides: 2, text_units: 1 } };
function mount() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><StudyPacksPage /></QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.mocked(api.studyPacks.list).mockResolvedValue({ packs: [pack] } as never);
  vi.mocked(api.studyPacks.detail).mockResolvedValue({ ...pack, documents: [doc] } as never);
  vi.mocked(api.studyPacks.units).mockResolvedValue({ total: 2, units: [
    { unit_id: 'u', document_id: 'd', ordinal: 0, title: 'First slide', text: '<script>unsafe</script>', role: 'body', locators: [{ kind: 'pptx', slide: 1 }], asset_ids: [] },
    { unit_id: 'blank', document_id: 'd', ordinal: 1, title: 'Slide 2', text: '', role: 'body', locators: [{ kind: 'pptx', slide: 2 }], asset_ids: [] },
  ] } as never);
  vi.mocked(api.studyPacks.status).mockResolvedValue({ job_id: 'j', pack_id: 'p', state: 'indexing' } as never);
});
it('shows extraction warnings and original slide numbers; previews untrusted text safely', async () => {
  const { container } = mount();
  fireEvent.click(await screen.findByRole('button', { name: /Course/ }));
  fireEvent.click(await screen.findByRole('button', { name: /Inspect slides.pptx/ }));
  expect(await screen.findByText('slide:2:no_text')).toBeInTheDocument();
  fireEvent.click(await screen.findByRole('button', { name: /Slide 1/ }));
  expect(await screen.findByText('<script>unsafe</script>')).toBeInTheDocument();
  expect(container.querySelector('script')).toBeNull();
  expect(screen.getByRole('button', { name: /Slide 2/ })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Download original' })).toHaveAttribute('href', '/original');
});
it('requires target-specific confirmation and does not claim a failed purge succeeded', async () => {
  vi.mocked(api.studyPacks.purge).mockRejectedValue(new Error('Close viewer and retry purge'));
  mount();
  fireEvent.click(await screen.findByRole('button', { name: /Course/ }));
  fireEvent.click(await screen.findByRole('button', { name: 'Delete pack permanently' }));
  expect(screen.getByRole('button', { name: 'Confirm permanent deletion' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Type target ID to confirm'), { target: { value: 'p' } });
  fireEvent.click(screen.getByRole('button', { name: 'Confirm permanent deletion' }));
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Close viewer and retry purge'));
  expect(api.studyPacks.purge).toHaveBeenCalledWith('p', 'p', undefined);
});

it('retries the pending document target even after its document row is gone', async () => {
  vi.mocked(api.studyPacks.detail).mockResolvedValue({ ...pack, state: 'purge-pending', documents: [], pending_purge: { document_id: 'removed-doc' } } as never);
  vi.mocked(api.studyPacks.purge).mockResolvedValue({ deleted: true, invalidated_history: true });
  mount();
  fireEvent.click(await screen.findByRole('button', { name: /Course/ }));
  fireEvent.click(await screen.findByRole('button', { name: 'Retry failed cleanup' }));
  fireEvent.change(screen.getByLabelText('Type target ID to confirm'), { target: { value: 'p' } });
  expect(screen.getByRole('button', { name: 'Confirm permanent deletion' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Type target ID to confirm'), { target: { value: 'removed-doc' } });
  fireEvent.click(screen.getByRole('button', { name: 'Confirm permanent deletion' }));
  await waitFor(() => expect(api.studyPacks.purge).toHaveBeenCalledWith('p', 'removed-doc', 'removed-doc'));
});

it('reports upload bytes separately from subsequent extraction/indexing', async () => {
  let finish: () => void = () => undefined;
  vi.mocked(api.studyPacks.upload).mockImplementation((_pack, _file, progress) => new Promise((resolve) => {
    progress(70);
    finish = () => resolve({ document: doc, job: { job_id: 'j', pack_id: 'p', state: 'queued' } } as never);
  }));
  mount();
  fireEvent.click(await screen.findByRole('button', { name: /Course/ }));
  fireEvent.change(await screen.findByLabelText('Upload material'), { target: { files: [new File(['ORION'], 'lesson.md')] } });
  expect(await screen.findByRole('progressbar', { name: 'Upload byte transfer' })).toHaveAttribute('aria-valuenow', '70');
  expect(screen.getByText(/Upload byte transfer only/)).toBeInTheDocument();
  await act(async () => finish());
  await waitFor(() => expect(screen.getByText(/Processing:/)).toHaveTextContent('indexing'));
  expect(screen.queryByRole('progressbar')).toBeNull();
});

it('successful purge clears browser history and broadcasts scoped UI invalidation', async () => {
  vi.mocked(api.studyPacks.purge).mockResolvedValue({ deleted: true, invalidated_history: true });
  localStorage.setItem('aura-trace-run:private', JSON.stringify({ request: { pack_id: 'p' } }));
  const purged = vi.fn(); window.addEventListener('study-pack-purged', purged);
  mount(); fireEvent.click(await screen.findByRole('button', { name: /Course/ }));
  fireEvent.click(await screen.findByRole('button', { name: 'Delete pack permanently' }));
  fireEvent.change(screen.getByLabelText('Type target ID to confirm'), { target: { value: 'p' } });
  fireEvent.click(screen.getByRole('button', { name: 'Confirm permanent deletion' }));
  await waitFor(() => expect(purged).toHaveBeenCalled());
  expect(localStorage.getItem('aura-trace-run:private')).toBeNull();
  expect(screen.queryByLabelText('Permanent deletion confirmation')).not.toBeInTheDocument();
  window.removeEventListener('study-pack-purged', purged);
});
