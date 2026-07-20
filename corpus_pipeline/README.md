# AURA-Bio Processing Pipeline

This is the data-preparation project that follows the acquisition pipeline. It
reads the verified corpus at `D:\aura_data\AURA-Bio-Corpus` and writes every
derived artifact under `G:\aura_llm\AURA-Bio-Processed`. It never edits or
deletes an acquired source file.

## What it does

The stages are intentionally separate and resumable:

1. `inventory` selects one preferred representation of each configured source.
2. `ingest` parses all supported formats, cleans text, repairs encoding damage,
   removes boilerplate, and performs exact document/paragraph deduplication.
3. `chunk` creates section-aware passages using the BGE tokenizer.
4. `embed` generates normalized BGE Base v1.5 vectors in independent float16
   shards.
5. `index` builds a compact FAISS SQ8 dense index for embedded chunks and an
   SQLite FTS5 sparse index over every available chunk.
6. `search` applies Reciprocal Rank Fusion to dense and sparse candidates.

Large structured sources use their provider IDs as trusted uniqueness keys.
In particular, filtered PubMed records are PMID-partitioned and therefore skip
the expensive global paragraph-fingerprint database. Small/core sources are
processed before PubMed, and large shards use faster gzip settings.
Trusted shards use four workers by default; only the main process updates the
resume database after a worker has atomically completed its output.

Supported inputs include gzip JSONL, MediaWiki JSON/wikitext, JATS/NLM XML and
NXML, PDF, TXT, CSV, TSV, UniProt DAT, OBO, Reactome summaries, and PubMedQA
JSON. Raw PubMed and LitArch archives are excluded when their normalized forms
exist. PubMedQA held-out ground truth is intentionally excluded from retrieval.
Canonical records inherit SHA-256/checksum provenance, provider URLs, license
evidence, and exact item-level Creative Commons identifiers from the acquisition
manifest whenever those fields are available.

## Canonical schemas

Canonical documents are gzip JSONL records containing:

```json
{
  "document_id": "wikipedia_biology:stable-hash",
  "source_id": "wikipedia_biology",
  "category": "reference",
  "title": "Cell biology",
  "text": "## Introduction\n\n...",
  "source_path": "D:/.../biology-pages-00001.json",
  "external_id": "12345",
  "url": "https://en.wikipedia.org/wiki/Cell_biology",
  "license_id": "CC-BY-SA-4.0",
  "authors": [],
  "published": "2026-...",
  "section": null,
  "metadata": {"content_sha256": "...", "parser": "wikipedia_json"},
  "schema_version": "1.0"
}
```

Chunk records retain that provenance and add `chunk_id`, `ordinal`,
`token_count`, and the active section. Retrieval chunks target 450 BGE tokens,
have a 64-token overlap, and never exceed 510 tokens. BGE Base v1.5 has a
512-token input limit, so using the SRS's generic 500–900 range would silently
truncate embeddings.

## Installation

From `G:\aura_llm`:

```powershell
python -m pip install -e .\corpus_pipeline
```

The model configured in `config/pipeline.toml` is
`BAAI/bge-base-en-v1.5`. The first tokenizer/model use downloads it from
Hugging Face if it is not already cached.

## Safe pilot

Run a small end-to-end pilot before estimating the full embedding job:

```powershell
aura-process inventory
aura-process probe
aura-process ingest --source wikipedia_biology --max-files 2
aura-process chunk --source wikipedia_biology --max-files 2
aura-process embed --source wikipedia_biology --max-files 2 --max-chunks 32 --device cpu
aura-process index
aura-process search "How does mitochondrial apoptosis work?"
```

Or run the same bounded workflow with one command:

```powershell
aura-process run --source wikipedia_biology --max-files 2 --device cpu
```

Inspect progress at any time:

```powershell
aura-process status
```

If an older run created a very large global fingerprint database, compact it
once without deleting any finished document shards or resume markers:

```powershell
aura-process compact-state
```

## Full processing

Cleaning and chunking can be run source by source and resumed safely:

```powershell
aura-process ingest
aura-process chunk --workers 4
aura-process embed --source wikipedia_biology --device cuda
aura-process embed --source nlm_litarch_biology --device cuda
aura-process index --index-type sq8
```

An unbounded all-in-one run requires explicit confirmation because embedding
the full PubMed-scale corpus can take days and produce many gigabytes:

```powershell
aura-process run --yes --device cuda --index-type sq8
```

`flat` preserves float32 vectors in the final FAISS index but is much larger.
The default `sq8` index learns per-dimension quantization ranges from up to
100,000 vectors and stores roughly one byte per dimension.

Dense and sparse coverage are deliberately decoupled. It is reasonable to
chunk all sources, embed Wikipedia/textbooks/knowledge bases/PMC first, and
leave the very large PubMed abstract collection BM25-searchable until compute
and evaluation justify dense embedding it.

For resumable Kaggle GPU packaging, real-corpus benchmarking, bounded dual-GPU
jobs, and verified local import, see [`kaggle/README.md`](kaggle/README.md).

`--delete-documents-after-success` is the low-disk mode. A canonical document
shard is removed only after its compressed chunk shard has been atomically
written and its resume marker committed. The frozen source corpus remains
untouched and can reproduce that intermediate shard if needed.

## Output layout

```text
G:\aura_llm\AURA-Bio-Processed\
  00_inventory\
  01_documents\
  03_embeddings\
  04_indexes\
  05_reports\
  state\

D:\aura_data\AURA-Bio-Processed\
  02_chunks\
```

Each input shard is written to a `.part` file and atomically renamed only after
success. SQLite records its size/mtime signature and duplicate fingerprints.
Re-running a stage skips completed inputs with the same source and configuration signature.
Structured sources use their stable provider IDs plus shard-local exact chunk
deduplication. Less structured books retain source-scoped document, paragraph,
and chunk fingerprints in SQLite. A changed frozen input or processing
configuration requires a deterministic rebuild rather than an ambiguous
incremental replacement:

```powershell
aura-process reset --yes
```

`reset` is guarded and deletes only the configured `AURA-Bio-Processed` output
tree; it refuses to run if that path equals the acquired corpus root.

## Tests

```powershell
python -m unittest discover -s .\corpus_pipeline\tests -v
```
