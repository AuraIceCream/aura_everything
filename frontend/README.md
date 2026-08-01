# AURA-Bio Frontend

Local-first React interface for evidence-grounded biology tutoring, hybrid
retrieval inspection, structured pipeline traces, and corpus readiness.

## Two modes: mock and live

This app ships with **mocks enabled by default** so every route and streaming
interaction works with no backend at all, which is useful for UI work and
demos. Nothing in mock mode touches the real pipeline.

| | `VITE_USE_MOCKS=true` (default) | `VITE_USE_MOCKS=false` |
|---|---|---|
| Data source | Mock Service Worker, canned responses | the real FastAPI backend |
| Answer latency | instant | tens of seconds, it is really generating |
| Citations | fixed sample passages | real retrieved passages |
| Requires backend | no | yes |

If answers appear instantly and never change, you are in mock mode.

## Run against mocks

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Run against the real pipeline

First start the backend (see the root [`README.md`](../README.md) for the full
setup, including the index and the local model):

```powershell
# from the repository root, runtime installed
$env:AURA_DENSE = "1"
$env:AURA_RERANK = "1"
aura-bio-api --index-root G:\aura_data\AURA-Bio-Index
```

Then create `frontend/.env.local`:

```ini
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_USE_MOCKS=false
```

Restart the dev server, because Vite only reads env files at startup:

```powershell
npm run dev
```

Confirm it is live: the backend should log `POST /api/v1/runs` when you submit a
question. `.env.local` is gitignored.

The backend degrades gracefully. With no local model it answers extractively
from evidence; with no dense index it serves the BM25 channels alone.

## Routes

- `/ask` — adaptive tutoring, streaming answers, citations, and evidence drawer
- `/retrieval` — BM25, dense, hybrid, and reranked comparison
- `/evaluation` — benchmark composition and the four-system ablation
- `/traces/:runId` — structured operational trace without chain-of-thought
- `/corpus` — source and preparation coverage
- `/settings` — device-local pedagogy, model, privacy, and developer preferences

The sidebar's "Demo activity" panel is always simulated and labels itself as
such; it is a UI affordance, not pipeline state.

## Contracts and verification

```powershell
npm run types:api     # regenerate types from the OpenAPI contract
npm test              # unit tests
npx tsc --noEmit      # type check
npm run build         # production build
npm run test:e2e      # end-to-end
```

`openapi/aura-bio.openapi.json` is the contract-first API definition. Generated
types live in `src/generated/api.ts`; MSW handlers implement the same endpoints.

API keys are backend-only and must never be placed in a `VITE_` variable:
anything prefixed `VITE_` is inlined into the client bundle and shipped to the
browser.

## Note on optional response fields

Several fields in the API contract are genuinely absent for some answers, and
the backend sends them as JSON `null` rather than omitting them. Guard these
with `!= null`, not `!== undefined`, since `null !== undefined` in JavaScript
and the stricter check lets `null` through into arithmetic. `dense_score` is
the common case: it is always `null`, because no per-citation dense score is
computed.

A top-level error boundary wraps the app, so an unhandled render error shows a
recoverable message instead of a blank page.
