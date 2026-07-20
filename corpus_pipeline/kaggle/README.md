# AURA-Bio embeddings on Kaggle

This workflow sends completed **retrieval chunks**, not raw archives or
canonical documents, to a private Kaggle Dataset. It produces normalized
`BAAI/bge-base-en-v1.5` passage vectors as float16 job files and reconstructs
the existing AURA source-sharded embedding layout after download.

## Profiles

| Profile | Included sources | Chunks | Float16 vectors |
|---|---|---:|---:|
| `open-core` | Wikipedia, PMC OA, UniProt, Gene Ontology, Reactome | 9,873,339 | 14.12 GiB |
| `core` | `open-core` plus NLM LitArch, BioLibreTexts and MeSH | 10,394,250 | 14.87 GiB |
| `pubmed` | Filtered PubMed abstracts only | 26,416,670 | 37.79 GiB |
| `full` | `core` plus filtered PubMed | 36,810,920 | 52.66 GiB |

`pubmedqa_labeled` is excluded from all profiles and from the sparse index. It
is supervised/evaluation material, not retrieval evidence.

Recommended rollout:

1. Run `open-core` first if you want the safest third-party upload scope.
2. Run `core` instead if the item-level textbook/NLM terms have been reviewed
   for private Kaggle processing.
3. Evaluate hybrid retrieval before paying the large PubMed dense-embedding
   cost. All PubMed chunks can remain BM25/FTS5 searchable.
4. If dense PubMed improves evaluation, prepare the separate `pubmed` profile
   and import it alongside the core output. There is no need to rerun core.

## 1. See the plan locally

From `G:\aura_llm`:

```powershell
python .\corpus_pipeline\kaggle\aura_kaggle_embeddings.py plan `
  --chunks-per-second 100 `
  --gpus 1
```

The rate is deliberately an input. Replace it with the rate printed by the
Kaggle benchmark; the script then gives an evidence-based ETA for every scope.

## 2. Package a private Kaggle input Dataset

The packer creates uncompressed TAR bundles around the existing gzip shards.
It does not recompress ordinary shards. Exceptionally large shards such as
UniProt are split into bounded tasks so the GPU worker never loads a multi-GB
document into memory.

```powershell
python .\corpus_pipeline\kaggle\aura_kaggle_embeddings.py prepare `
  --profile open-core `
  --output D:\aura_data\AURA-Kaggle-Embedding\open-core `
  --kaggle-username YOUR_KAGGLE_USERNAME `
  --dataset-slug aura-bio-open-core-embedding-input
```

For the larger alternatives, change the profile and output directory:

```powershell
# All non-PubMed retrieval sources
--profile core

# PubMed only, to add after core
--profile pubmed

# Everything except PubMedQA, from scratch
--profile full
```

The default job is at most about one million chunks, producing approximately
1.43 GiB of float16 vectors. The manifest, worker script, source signatures,
job boundaries and Kaggle Dataset metadata are generated automatically.

## 3. Install and authenticate the Kaggle CLI

```powershell
python -m pip install --upgrade kaggle
kaggle auth login
```

Upload the generated directory. Datasets are private unless `--public` is
explicitly supplied, so do not add that flag:

```powershell
kaggle datasets create `
  -p D:\aura_data\AURA-Kaggle-Embedding\open-core
```

If the dataset already exists, publish a new private version:

```powershell
kaggle datasets version `
  -p D:\aura_data\AURA-Kaggle-Embedding\open-core `
  -m "AURA-Bio chunk manifest refresh"
```

Keep the dataset private. Before uploading `core` or `pubmed`, verify that the
applicable NLM and item-level source terms permit processing through a private
third-party compute service. Non-commercial research intent alone is not a
substitute for that check.

## 4. Configure the Kaggle notebook

1. Create a new Kaggle Notebook.
2. Add the private Dataset created above as notebook input.
3. Enable a GPU accelerator. A dual-T4 session is useful because the worker can
   process two independent jobs concurrently; a P100/single GPU also works.
4. Enable Internet for the first run so Sentence Transformers can download
   `BAAI/bge-base-en-v1.5`, or attach a cached model Dataset.
5. Install the runtime dependency:

```python
!pip install -q "sentence-transformers>=3,<6"
```

Find the mounted dataset directory:

```python
from pathlib import Path
manifest = next(Path("/kaggle/input").rglob("embedding-manifest.json"))
print(manifest.parent)
```

## 5. Benchmark before the full run

Replace `DATASET_DIR` with the printed directory:

```python
!python DATASET_DIR/aura_kaggle_embeddings.py benchmark \
  --input-root DATASET_DIR \
  --chunks 20000 \
  --batch-size 48 \
  --device cuda:0 \
  --gpus 2
```

Use `--gpus 1` for a P100/single-GPU session. The benchmark warms up the model,
measures real 450-token AURA chunks, and prints the projected profile ETA.

## 6. Run bounded embedding jobs

For a dual-T4 notebook, process two one-million-chunk jobs concurrently:

```python
!python DATASET_DIR/aura_kaggle_embeddings.py embed \
  --input-root DATASET_DIR \
  --output-root /kaggle/working/aura-embeddings \
  --job-start 0 \
  --job-count 2 \
  --parallel-jobs 0 \
  --batch-size 48
```

`--parallel-jobs 0` detects the GPU count. On one GPU the selected jobs run
sequentially. CUDA out-of-memory errors automatically halve the batch size and
retry the same batch.

Each job is atomic and includes:

- normalized float16 BGE vectors;
- exact source-shard/range mapping;
- input signatures;
- vector SHA-256;
- measured runtime and final batch size.

After a successful run, save the Notebook version with output. Download it
before replacing that output with the next pair of jobs, then advance
`--job-start` by `--job-count`.

The official CLI can download the latest saved output:

```powershell
kaggle kernels output YOUR_USERNAME/YOUR_NOTEBOOK_SLUG `
  -p D:\aura_data\AURA-Kaggle-Embedding\downloads\run-000 `
  -o
```

Put every downloaded run beneath the same `downloads` directory. The importer
searches recursively, so the individual run folders can remain separate.

## 7. Import and verify locally

```powershell
python .\corpus_pipeline\kaggle\aura_kaggle_embeddings.py import `
  --kaggle-output D:\aura_data\AURA-Kaggle-Embedding\downloads `
  --chunk-root D:\aura_data\AURA-Bio-Processed\02_chunks `
  --embedding-root G:\aura_llm\AURA-Bio-Processed\03_embeddings
```

The importer verifies every original chunk-shard signature and reconstructs
the pipeline's expected per-source `.vectors.npy` files. It does not duplicate
the 25 GiB chunk corpus beside the embeddings; completion markers point the
indexer back to the immutable D-drive chunks.

Then build the hybrid index locally:

```powershell
aura-process index --index-type sq8
```

The SQ8 dense index is about one byte per dimension: roughly 7.4 GiB for core
or 26.3 GiB for the full dense corpus, plus the SQLite sparse/text store.

## Resuming and checking completeness

- Re-running the same Kaggle job skips it when its vector file and matching
  completion marker are already present in the output directory.
- Re-running local import skips source shards whose signatures, model and
  vector counts already match.
- A missing job is visible as a gap in `job_index`; do not build the intended
  profile's final index until all its outputs have been downloaded and imported.
- `open-core`/`core` and `pubmed` may be imported independently and combined in
  the same `03_embeddings` directory.

