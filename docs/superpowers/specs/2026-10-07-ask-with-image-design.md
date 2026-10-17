# Temporary ask-with-image — design

Status: design and inline implementation approved; execution started 2026-10-08.

## Approved amendment (2026-10-08; overrides separate-click wording below)

One click on Ask binds the typed question, attachment, selected sources and chosen
provider/configuration and runs visible processing → indexing → answering stages.
Picking/uploading an image, typing or polling never starts inference. Hosted
payload and model-unload consent remain separate prerequisites. Failure/busy GPU
stops the chain visibly; resuming requires an explicit click. Navigation, expiry,
removal or changed sources invalidate pending intent and prevent late answers.

The single structured figure-description call can use the question as untrusted
focus context for temporary images. Record its hash in provenance/config/cache;
changed questions do not silently reuse question-specific interpretations. Empty
question study-pack/figure-bank behaviour remains unchanged. Question text cannot
certify facts or labels. Live quality evaluation remains separately GPU-authorised.

## Intent and success

A student can attach a diagram to a question without creating permanent study
material. Reuse the implemented visual intake, OCR, description jobs, study
retrieval, grounding policy and source previews. The submitted image remains
inspectable beside the answer, and model interpretation stays distinct from
independent source support. An optional saved study pack supplies context.

Keep implementation and verification GPU-free while the user's GPU is occupied.
Fake-provider tests establish behaviour, not scientific accuracy. Real image
understanding and GPU memory/latency evaluation remain a separately started run.

## Scope and approach

Use a temporary pack in the existing private StudyStore, not an independent image
store or a second inference pipeline. This reuses pack-owned originals, previews,
derived revisions, indexes, jobs, leases and purge. Add a small lifecycle service
for attachment creation, expiry, deletion and promotion, and a composite study
searcher for attachment plus one optional saved pack.

Alternatives considered:

- A memory-only image request would avoid disk retention but duplicate durable
  checkpoints, source previews and restart/error handling.
- Copying a saved pack into the temporary pack would simplify search but duplicate
  private documents and make expiry, deletion and citation provenance misleading.

The selected approach uses two read-only search snapshots when context is selected.
Never copy, alter or reindex that saved pack as an attachment side effect.

Initial scope is one single-frame PNG/JPEG attachment per question, reusable for
follow-up questions until expiry. PDF/PPTX attachment intake stays on the existing
Study material page. Multiple images, camera capture, visual embeddings, generated
diagrams/charts and automatic scientific interpretation are excluded.

## Global constraints

- Work in the current dirty checkout; preserve unrelated work. No commits or pushes.
- Do not change the original biology corpus, its indexes or benchmark banks.
- Do not run GPU inference, pull models or send private content to a hosted provider
  as part of implementation/testing. Use real safe asset/storage code and fake providers.
- Inherit existing 50 MiB upload, 25-million-pixel decode and single-frame PNG/JPEG
  validation limits, EXIF correction, sanitised previews and bounded worker decoding.
- Inherit provenance, numerical-verification restrictions, structured VLM schema,
  one normal call/one repair maximum, provider identity pinning and visible failures.
- Upload performs validation/extraction only. OCR/vision is an explicitly started
  job, and answering is a separate explicit action after usable evidence is indexed.
- Use existing local-origin protections, owned IDs, no-store responses and escaped
  previews. No arbitrary file paths, remote image fetching, generated-code execution,
  private browser localStorage/sessionStorage or private global trace persistence.

## Temporary lifecycle and retention

Extend Pack with backward-compatible lifecycle metadata: `retention` is `saved`
or `temporary`, and `expires_at` is a server-generated UTC timestamp or null.
Existing records lacking fields are saved packs. Add a lifecycle-schema version
to support migration without rebuilding existing document/visual indexes.

Temporary creation/upload must be atomic from the caller's perspective: return
only when the image is owned by a valid temporary pack and its extraction job has
been recorded. Failed upload must not leave an ordinary saved pack or unbounded
orphan originals. Native extraction/indexing uses the current CPU job machinery.

Default expiry is 3,600 seconds after upload. It is absolute, not extended by
polling, questions, visual retries or browser reload. Show the deadline in the UI.
One deployment setting may choose 300–86,400 seconds; clients cannot set arbitrary
retention deadlines. Limit the local server to 20 live temporary packs; reject
additional uploads visibly rather than silently deleting a previous attachment.

Temporary packs are absent from ordinary saved-pack listings/selectors. They are
accessible only through their explicit attachment IDs and never become a source
for another request implicitly. Do not advertise multi-user authentication: this
remains the existing single-user local application, with its existing origin checks.

Check expiry at access, inference start/resume, answer start and final publication.
All existing routes that can read a temporary pack must honour the same guard;
using its pack ID in the regular source/visual API must not bypass expiry. An
expired resource returns a safe `410 attachment_expired` response until removed;
once removed it returns 404. It never falls back to the core corpus or model memory.

Perform a cleanup sweep when private services open after restart, then every 60
seconds while they run. Runtime expiry prevents new access immediately even if
physical cleanup is delayed. The sweeper uses the existing contained, lease-aware
hard purge, cancels work and invalidates run caches/references for that attachment.
If a reader/provider call still holds a lease, mark deletion pending, reject new
access and retry cleanup; report pending/failed cleanup visibly. No promise of
instant secure erasure from SSDs, browser pixels, OS backups or hosted retention.

Explicit Remove/Delete deletes only the attachment-owned pack. Selecting a context
pack must never make it a cleanup target. Closing/navigating the page clears client
state and revokes blob URLs, but does not depend on an unreliable browser unload
request: server expiry is the durable fallback. Uploaded documents remain local
until explicit deletion or expiry, so describe the feature as temporary, not disk-free.

## Saving an attachment

“Save as study pack” promotes the same temporary pack to saved retention with an
explicit user-chosen name. Keep document/figure/revision IDs so current citations
remain valid. Clear its expiry and expose it in saved-material lists atomically
under the lifecycle/purge lock. This does not silently append to the context pack.

Promotion does not save or relabel old temporary answer histories; users can ask a
new saved-pack question afterwards. It does not grant new hosted permissions.
Reject expired, purge-pending or already deleted attachments. Promotion racing
expiry has one deterministic winner: a successful promotion prevents purge;
otherwise saving fails visibly and must not recreate partial files.

## User flow and GPU control

Extend AskPage with one image picker, upright preview, filename, expiry notice,
remove control, optional saved-pack selector and visual processing panel. Disable
ordinary submit while attachment extraction/description/indexing is unfinished.
Show why it is blocked and let users remove the attachment to return to text-only Ask.

Reuse figure review/manual crop, OCR/vision start controls, progress, failures,
pause/resume/cancel and provider disclosure. No job starts when an image is picked,
a question is typed or the page is reloaded. After a completed visual job publishes
usable evidence, the student explicitly submits the question. OCR-only usable
evidence can support a labelled transcription answer without forcing vision.

Reuse local-model preflight and explicit model-swap consent. A busy GPU leaves the
attachment waiting with a visible explanation; no automatic polling-triggered
inference, CPU fallback, retry, provider switch or unloading unrelated processes.
VLM and answer generation do not overlap: finish the visual stage, then explicitly
start the answer stage. Expose which configured generator will answer, including
an explicitly labelled extractive mode when no text model is configured.

Hosted vision requires consent for this temporary attachment plus each started
job, with a preview of the crop and hint categories being sent. A saved context
pack is not automatically a source of uploaded hints. Existing external-critic
preferences default off for attachment questions; separate explicit consent must
disclose that both image-derived text and selected private context may be sent.
Local expiry cannot revoke remote retention; say so in the consent panel.

## Retrieval, answers and source referencing

The attachment remains the primary request-owned evidence scope. With no selected
saved pack, use the ordinary private pack pipeline. With one selected saved pack,
open both immutable index generations under bounded leases in deterministic ID
order; release/close them on every failure path. No core runtime initialisation.

A composite StudySearcher implements the existing search/hierarchical-neighbour
contract. Query each index using its actual readiness (BM25 or cached dense+BM25),
merge ranked candidates with reciprocal-rank fusion rather than mixing incomparable
raw scores, then use the existing configured CPU reranker/evidence selection.
Deduplicate by `(pack_id, chunk_id)`; sibling expansion stays inside its originating
pack/document. Carry pack IDs on every evidence object and pin both generations
in the private trace. Reserve up to two highest-ranked nonempty attachment chunks
within the existing final passage/token budget (never append an unbounded block),
so a short figure description is not lost among a large book's top-k candidates.
If no usable attachment text exists, block the image answer instead of returning a
context-only answer disguised as image understanding. Reservation is not a
relevance exemption: unrelated attachment content cannot earn independent support.

Keep pack-only prompt policy and verification. Image/OCR/user annotation are
untrusted evidence, including instructions printed inside the image. A selected
saved pack may provide independent native-text support for a claim, but unrelated
native passages cannot promote image interpretation to verified grounding.
Unsupported questions revise/refuse rather than borrowing uncited model memory.

Show the submitted image beside the question/answer and reuse the source preview
and citation drawer. Citations preserve actual source pack/document, immutable
revision, asset and normalised bbox/coordinate transform. The temporary upload
never masquerades as a textbook page or as verified native text.

Answer caches/streams are private and attachment-owned. Record all source pack
dependencies: deleting either the attachment or context invalidates a dependent
run, without deleting the other source. Revalidate availability before publishing
an answer; expiry/context purge during inference cannot publish a fresh accessible
answer. Historical preview fetches fail visibly after expiry; browser memory cannot
be recalled, so clear mounted answers/previews when an expiry/purge is observed.

## Implementation boundaries

- `study/schema.py`, `storage.py`: backward-compatible retention metadata and common
  access guards; preserve saved-pack behaviour and contained purge.
- New `study/attachments.py`: temporary lifecycle, sweeper and promotion only.
- New `study/composite.py`: multi-pack search snapshots and neighbour dispatch only.
- `study/runtime.py`, API run mapping/cache: attachment-aware pipeline composition
  and complete private source dependency tracking; ordinary requests stay compatible.
- New `api/study_attachments.py`, existing private middleware/lifespan: bounded
  upload, status, promotion and deletion; existing visual/source APIs are reused.
- New Ask attachment component plus `AskPage.tsx`, API/types and run hook: temporary
  preview/controls, explicit processing and privacy-aware answer lifecycle.
- Tests and `docs/study-packs.md`: behaviour, constraints and manual GPU checklist.

No new database service, vector store, provider implementation or product dependency
is needed. Internal interface names/routes will be pinned in the implementation
plan after this written design is approved.

## GPU-free acceptance tests

1. Real PNG/JPEG fixtures validate/correct orientation; disguised/multiframe/oversize
   files fail without orphan saved packs. Upload never calls a model/provider.
2. Fake-clock expiry survives restart, cannot be extended by polling, blocks all
   source/run/visual routes and purges only attachment-owned originals/derivatives.
3. Save-versus-expire, remove-versus-inference, context purge and delayed stream
   races reject late writes/publication. Pending cleanup is visible and retried.
4. Ordinary old saved packs remain readable/listed and unaffected by cleanup;
   promotions retain IDs/citations and do not mutate the selected context pack.
5. Fake providers prove explicit start, same-provider bounded repair, busy GPU
   waiting, no fallback and independent hosted-vision/external-critic consent.
6. Fake CPU encoders/rerankers plus real pack indexes prove both-pack retrieval,
   distinct source IDs, neighbour isolation and truthful sparse/hybrid diagnostics.
7. Derived-only responses remain interpreted/transcribed; unrelated native context
   cannot certify a figure or its numbers. Unsupported controls return insufficient
   support; printed image instructions never become system instructions.
8. Frontend tests cover attachment upload/removal, crop/status/expiry, promotion,
   original preview, clear-on-purge, blocked submit and no private browser archive.
9. Run existing private visual/study and core regression tests, frontend tests,
   TypeScript/Vite build and whitespace checks without downloading or loading models.

Live vision label/relation accuracy, unsupported-question abstention, answer quality,
generator/VLM swap behaviour and 4 GB fit are explicitly not established by these
tests. Use the frozen figure-bank controls for the later authorised hardware run.

## References

- [Visual study-pack design](2026-10-07-visual-study-packs-design.md)
- [Existing user/implementation guide](../../study-packs.md)
