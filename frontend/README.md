# AURA-Bio Frontend

Local-first React interface for evidence-grounded biology tutoring, hybrid
retrieval inspection, structured pipeline traces, and corpus readiness.

## Running it

The interface talks to the real backend only. There is no mock or demo mode:
every page reads from the API, so start the backend first (see the root
[`README.md`](../README.md) for the full setup, including the index and the
local model).

```powershell
# from the repository root, runtime installed
$env:AURA_DENSE = "1"
$env:AURA_RERANK = "1"
aura-bio-api --index-root G:\aura_data\AURA-Bio-Index
```

Then:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The API base defaults to
`http://127.0.0.1:8000`; override it in `frontend/.env.local` (gitignored):

```ini
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Vite reads env files only at startup, so restart the dev server after changing
one.

A real answer takes tens of seconds, because it is genuinely routing,
retrieving, generating, and verifying. Panels with nothing to show say so
rather than displaying sample content, so empty panels on a fresh backend are
the correct state.

The backend degrades gracefully. With no local model it answers extractively
from evidence; with no dense index it serves the BM25 channels alone.

## Routes

Study material supports explicit figure/OCR passes, upright manual crops and
immutable interpretation/user-edit previews. Groq requires per-pack permission
plus an exact crop/hint payload preview and job approval; no API keys enter the
frontend. Figure/OCR answers are labelled interpreted/transcribed, not verified.
See [visual setup and limits](../docs/study-packs.md#visual-passes-2026-10-07).

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

## Ask with an image

Attach PNG/JPEG, enter the question, optionally select saved study material,
then click Ask once. Processing, indexing and answering show separate stages;
upload/polling alone do not start inference. Inspect/crop the original in the
existing figure controls. Choose OCR for text or the exact installed local
vision model for diagrams. Busy/missing models stop visibly; inspect the job
and resume explicitly. Hosted processing requires its own payload preview and
approval, separate from private external-critic consent.

Temporary images are stored locally for one hour by default, not just in memory.
Save retains the same citation IDs without expiry; Detach never deletes saved
material. Private runs stay out of browser archives. Described figures and OCR
numbers remain interpreted/unverified. Real model quality has not been established
by the frontend/fake-provider tests.
