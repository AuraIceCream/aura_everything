# AURA-Bio Frontend

Local-first React interface for evidence-grounded biology tutoring, hybrid
retrieval inspection, structured pipeline traces, and corpus readiness.

## Run locally

```powershell
cd G:\aura_llm\frontend
npm install
npm run dev
```

The mock API is enabled by default, so every route and streaming interaction
works before the FastAPI application exists. Copy `.env.example` to `.env.local`
and set `VITE_USE_MOCKS=false` to use a live backend.

## Routes

- `/ask` — adaptive tutoring, streaming answers, citations, and evidence drawer
- `/retrieval` — BM25, dense, hybrid, and reranked comparison
- `/traces/:runId` — structured operational trace without chain-of-thought
- `/corpus` — source and preparation coverage
- `/settings` — device-local pedagogy, model, privacy, and developer preferences

## Contracts and verification

```powershell
npm run types:api
npm test
npm run build
npm run test:e2e
```

`openapi/aura-bio.openapi.json` is the contract-first API definition. Generated
types live in `src/generated/api.ts`; MSW handlers implement the same endpoints.
API keys are backend-only and must never use a `VITE_` environment variable.
