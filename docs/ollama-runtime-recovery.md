# Local Ollama cache-crash workaround

On 2026-10-11 the study benchmark's Ollama runner aborted with
`std::bad_alloc` while saving a prompt cache; Windows recorded `0xc0000409`.
Separate requests forcing `num_gpu=99` failed GPU memory fitting. These are
runtime failures, not evidence of poor answer accuracy. Original benchmark
outputs are retained, including their error records.

The isolated benchmark runtime uses the existing installed Ollama executable
and model on `127.0.0.1:11435`, leaving the normal service on 11434 unchanged:

```powershell
$env:OLLAMA_HOST = '127.0.0.1:11435'
$env:OLLAMA_NOPRUNE = 'true'
$env:OLLAMA_NO_CLOUD = 'true'
$env:LLAMA_ARG_CACHE_RAM = '0'
$env:LLAMA_ARG_CTX_CHECKPOINTS = '0'
$env:OLLAMA_NUM_PARALLEL = '1'
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve
```

Set these variables in the **Ollama server process**, not merely the API/client
process. Confirm `prompt cache is disabled` and `context checkpoints disabled`
in the runner log after loading a model. The cache controls are an upstream
workaround, not a guarantee against all native crashes; see the
[Ollama issue documenting the controls](https://github.com/ollama/ollama/issues/17534).

The client explicitly selects `AURA_OLLAMA_HOST=http://127.0.0.1:11435`. The
post-fix operational benchmark profile uses automatic CPU/GPU placement and a
single attempt, avoiding the failed forced-full-offload ladder. The model,
8192-token context, seed, output budget, robust mode, two draft candidates,
hybrid retrieval, reranking and configured verification policy are unchanged.
External criticism remains off. Actual automatic offload is **not** comparable
to fully GPU-offloaded latency; it is disclosed in the runtime sidecar and
generation traces. Checker availability must still be inspected separately.

The initial cache-disabled trial (`pack_20261011_qwen_cacheoff_v1`) passed
three direct generation requests but failed before its first complete pipeline
answer: `GGML_ASSERT(ctx->mem_buffer != NULL)` during `sched_reserve`, with
`n_batch=512`. Cache controls alone therefore did **not** resolve the full run.

The next trial explicitly sets `OllamaGenerator(num_batch=64)` to reduce
prompt-processing scratch allocation without reducing the 8192-token context
or output budget. The generator records this option in completion metadata;
omitting it preserves the server default. A 30-minute keep-alive avoids model
reloads between questions. These are runtime hypotheses until full-pipeline
records demonstrate success, not measured accuracy improvements.

**Observed outcome:** the batch-64 trial also failed during `sched_reserve`
before its first saved answer. The log confirms `n_batch=64` and successful
automatic GPU fitting, so neither an ignored batch option nor GPU fitting
failure explains this attempt. At model load the server reported 2.9 GiB free
RAM and 1.2 GiB free swap; it then allocated 1751.66 MiB of host model buffers
before the graph-memory assertion. Host allocation pressure is the leading
hypothesis, not a proven complete explanation of every native crash. Further
full-pipeline trials require more memory headroom or an explicitly agreed
resource-loading redesign. No pipeline success or accuracy result is claimed.

The new tag is `pack_20261011_qwen_cacheoff_batch64_v2`, with a separate
`.runtime.json` sidecar recording cache controls, host, model digest, Ollama
version and code snapshot. Pre-fix answers are not mixed into this run. Each
completed question is flushed and checkpointed by the normal harness; a first
pipeline exception stops the operational wrapper with a traceback rather than
silently appending many errors. The existing retrieval benchmark is retained.

## Loading-order trial

After freeing memory, the same configuration still failed at model warm-up
with `std::bad_alloc`. A subsequent trial loads Qwen **before** importing and
loading the CPU retrieval models. Keep the same model/context/batch options
on the probe and benchmark so Ollama can reuse the resident runner:

```powershell
$warmup = @{
    model = 'qwen3.5:4b'
    messages = @(@{role='user'; content='Reply with READY only.'})
    stream = $false
    think = $false
    keep_alive = '30m'
    options = @{num_ctx=8192; num_predict=8; num_batch=64; seed=42; temperature=0}
} | ConvertTo-Json -Depth 6
Invoke-RestMethod -Uri 'http://127.0.0.1:11435/api/chat' -Method Post `
    -ContentType 'application/json' -Body $warmup -TimeoutSec 180
```

Only proceed if this succeeds; then explicitly start the operational benchmark
with its recorded runtime profile. No checkpointed answers were present before
this loading-order trial. The first two full-pipeline questions then completed
and were saved (54.3 and 57.1 seconds). This supports a startup-allocation
workaround, not a guarantee of stability for the whole bank. Logs for this trial
are `.local/study-benchmark-20261011/qwen_preload.stdout.log` and
`qwen_preload.stderr.log`.

The saved answers report `semantic_support=unavailable_lexical_fallback` and
`decision=degraded`. Runtime success must **not** be presented as successful
semantic verification or a fully verified benchmark. External criticism is
still explicitly off. No Windows pagefile settings or unrelated apps were
changed, and no model/provider/stage was silently substituted.

## Post-fix validation profiles

The preloaded run later stopped after 13 answers with a PyTorch CPU allocation
failure. Its next attempt crashed in `torch_cpu.dll` during loading (Windows
Application event 1000, access violation `0xc0000005`). A staged diagnostic
with native fault tracing subsequently loaded both cached BGE models and ran
embedding and pair scoring successfully without Ollama. This does not prove
that the native crash was caused solely by memory pressure or that the DLL is
defective.

Study reranking now uses a configurable CPU batch size, default **2** instead
of the inherited **16**. All query/passage candidates are still scored; the
batch limit reduces peak activation memory, not retrieval depth. Configure
`AURA_STUDY_RERANK_BATCH` explicitly when benchmarking. The isolated remaining
17-question run additionally sets `OMP_NUM_THREADS=1` and `MKL_NUM_THREADS=1`
before importing model libraries and enables native fault tracing. It uses
`pack_20261011_qwen_remaining17_fixed_v3` and a separately frozen subset/lineage
record; the old 13 answers remain unchanged and are not copied into this run.
These mitigations require live validation before claiming the native crash is
fixed. The separate semantic-verifier availability issue is not concealed.

Local visual requests now send a compact JSON schema in Ollama's `format`
field: at most 12 labels, 2 axes and 6 visible connections, with short summaries
and explicit omissions. The prompt disallows inferring biological mechanisms
from an unlabelled arrow. This bounds description scope for the existing 1024
output-token budget; it cannot guarantee every image fits or every relation is
correct. Truncation still fails closed, now as `output_truncated`, preserving
the raw response and token usage across the isolated transport for diagnosis.
There is no automatic duplicate inference after truncation or timeout.

The original five real-image cases, crops, images and offline review keys stay
frozen. A new visual run writes under `real-figure-trial-20261011/compact-v2`
because the prompt/schema hash changed. Historical results are retained;
compact descriptions must be evaluated for label omissions and invented edges,
not just valid JSON. The schema mechanism follows the official
[Ollama structured-output documentation](https://docs.ollama.com/capabilities/structured-outputs).
