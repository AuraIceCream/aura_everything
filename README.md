# AURA-Bio Corpus Pipeline

This repository contains a provenance-first acquisition pipeline for rebuilding the corrupted AURA-Bio corpus. It uses official dumps, FTP-over-HTTPS endpoints, and machine-readable catalogues instead of scraping rendered web pages.

The pipeline is intentionally conservative:

- large downloads are never started by the default command;
- bulk sources require both `--yes` and `--allow-bulk`;
- interrupted downloads resume from `.part` files when the server supports ranges;
- a shared 50 GB hard cap prevents concurrent workers from silently exceeding the corpus ceiling;
- official MD5/SHA1 values are checked when the provider publishes them;
- gzip, bzip2, zip, and tar integrity is verified;
- unsafe or invalid downloads are moved to `90_Quarantine`;
- every file and decision is recorded in SQLite and exported as JSONL;
- external GLM review is optional and never receives files automatically.

## Included official sources

- PubMed 2026 annual baseline XML
- PMC Open Access commercial-use XML through licence-filtered ESearch and 100-article EFetch batches
- English Wikipedia biology-category revision batches and the Wikibooks dump
- NLM LitArch Open Access biology book packages
- reviewed UniProtKB/Swiss-Prot
- Gene Ontology
- Reactome pathway summaries
- 2026 MeSH descriptors
- PubMedQA expert-labeled QA and held-out ground truth
- Biology LibreTexts, E-Books Directory, and FreeBookCentre biology catalogs as licence-review queues

Source URLs, licence references, and selection policy are in [`config/sources.toml`](config/sources.toml). OpenStax is deliberately absent because its current Biology 2e page places an additional restriction on generative-AI ingestion.

BioASQ is recorded as a potential later manual import, not an automated source, because its training downloads currently require participant registration. PubMedQA test ground truth is stored under `04_QA` but must remain evaluation-only.

## Quick start

Python 3.11 or newer is sufficient; the acquisition path has no third-party dependencies.

Copy your Z.AI key into `ZAI_API_KEY=` in `.env`. The corpus root is already configured as `D:\aura_data\AURA-Bio-Corpus`; a key is optional unless `--use-glm` is requested.

Run the complete bounded pilot (catalog discovery, small datasets, two PubMed files, 25 PMC articles, five NLM books, verification):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_pipeline.ps1 -Profile pilot
```

To create only the textbook review queues:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_pipeline.ps1 -Profile catalog
```

```powershell
python -m aura_corpus sources
python -m aura_corpus plan --source gene_ontology --source reactome_summaries
python -m aura_corpus fetch --source gene_ontology --source reactome_summaries --yes
python -m aura_corpus verify
python -m aura_corpus status
```

The three directory sources are intentionally handled by `catalog`, not `fetch`:

```powershell
python -m aura_corpus catalog
```

This writes JSONL candidates under `05_Metadata/catalog_candidates/`. BioLibreTexts carries open content with per-page conditions, while the other two sites point to third-party material. A candidate remains `license_state: unknown` until its actual author/publisher licence is reviewed; the pipeline will not automatically download it.

For this research-only, non-commercial corpus, audit candidates and download only explicitly supported items:

```powershell
python -m aura_corpus audit-books
python -m aura_corpus fetch-books --yes
```

The allowlist is CC0, CC BY, CC BY-SA, CC BY-NC, and CC BY-NC-SA. Mixed, undeclared, CK-12, ND, all-rights-reserved, and directory-only claims are rejected. Every accepted PDF retains its item page, licence-evidence URL, use scope, and checksum.

The `plan` command accesses only provider indexes/catalogues and writes:

```text
AURA-Bio-Corpus/05_Metadata/corpus.sqlite3
AURA-Bio-Corpus/05_Metadata/manifests/files.jsonl
```

Downloaded files are stored under `<category>/raw/<source-id>/`. PMC EFetch batches are already XML. Compressed LitArch, UniProt, MeSH and Wikibooks files can be safely normalized with:

```powershell
python -m aura_corpus extract
```

For a large manifest, normalize one source at a time. Archive extraction is resumable through per-archive completion markers:

```powershell
python -m aura_corpus extract --source uniprot_sprot
python -m aura_corpus extract --source nlm_litarch_biology
```

To stay within the corpus ceiling while normalizing a large archive collection, replace each verified archive with its expanded output:

```powershell
python -m aura_corpus extract --source nlm_litarch_biology --delete-raw
```

For 10,000 commercially reusable PMC articles, discovery creates 100 XML batches rather than making per-article S3 metadata calls:

```powershell
python -m aura_corpus fetch --source pmc_oa_comm_xml --max-files 10000 --allow-bulk --yes --workers 3
```

Repeating that exact command intentionally returns the same first 10,000 results. Use non-overlapping PMC release-date windows to continue, or let the CLI split an entire year into seven-day windows:

```powershell
python -m aura_corpus fetch --source pmc_oa_comm_xml --pmc-window 2025-01-01:2025-01-07 --max-files 10000 --allow-bulk --yes --workers 3
python -m aura_corpus fetch --source pmc_oa_comm_xml --pmc-year 2024 --max-files 10000 --allow-bulk --yes --workers 3 --max-source-bytes 8GB
```

## Pilot and bulk downloads

Always plan first. A two-file PubMed pipeline test is:

```powershell
python -m aura_corpus plan --source pubmed_baseline --max-files 2
python -m aura_corpus fetch --source pubmed_baseline --max-files 2 --allow-bulk --yes
```

The full PubMed baseline is intentionally explicit:

```powershell
python -m aura_corpus plan --source pubmed_baseline
python -m aura_corpus fetch --source pubmed_baseline --allow-bulk --yes --workers 3
```

Optional per-file protection accepts decimal or binary units:

```powershell
python -m aura_corpus fetch --source wikibooks_en --allow-bulk --yes --max-file-bytes 1GiB
```

The default total corpus cap is 50 decimal GB. It can be lowered explicitly with `--max-total-bytes`; increasing it should be a deliberate storage decision.

Wikipedia is deliberately collected through `Category:Biology`, not the full English dump:

```powershell
python -m aura_corpus plan --source wikipedia_biology
python -m aura_corpus fetch --source wikipedia_biology --allow-bulk --yes --max-source-bytes 7GB
```

The configured traversal is bounded to 250,000 main-namespace articles, six category levels, and 50 pages per revision-JSON batch, targeting roughly 6–7 GB while the byte cap remains authoritative. Category graphs and article sizes change, so monitor actual size and relevance during acquisition.

Discovery is checkpointed locally. Collect incrementally by increasing `--max-files`; 1,000 batches means up to 50,000 pages. Later runs resume category traversal and skip batches already downloaded:

```powershell
python -m aura_corpus fetch --source wikipedia_biology --max-files 1000 --allow-bulk --yes --workers 1 --max-source-bytes 8GB
python -m aura_corpus fetch --source wikipedia_biology --max-files 2000 --allow-bulk --yes --workers 1 --max-source-bytes 8GB
```

## Compact the PubMed baseline

The annual baseline is citation-heavy and can occupy roughly 45 GB compressed. Convert it into training-oriented English records with abstracts, MeSH headings, identifiers, provenance, and retraction/type gates:

```powershell
python -m aura_corpus filter-pubmed --max-files 2
python -m aura_corpus filter-pubmed
```

After inspecting the filtered shards and manifest, reclaim raw storage safely:

```powershell
python -m aura_corpus filter-pubmed --delete-raw
```

Raw files are deleted individually only after their corresponding `.jsonl.gz` output passes a full gzip verification. Existing output shards are skipped, so the operation is resumable.

Do not run all bulk sources merely to reach a byte target. Build and evaluate a controlled retrieval pilot first.

## Qwen and optional GLM curation

The curator accepts JSONL records containing source metadata and a short `text` or `excerpt`. A record should include a deterministic licence decision:

```json
{"source_id":"pmc_oa_comm_xml","title":"Example","license_state":"allowed","license_id":"CC BY","retracted":false,"text":"A sufficiently long excerpt..."}
```

Local Qwen only:

```powershell
python -m aura_corpus curate --input candidates.jsonl --output decisions.jsonl
```

Local Qwen with GLM-4.5-Flash fallback:

```powershell
python -m aura_corpus curate --input candidates.jsonl --output decisions.jsonl --use-glm
```

Rules run before either model. Documents with unknown licences or retraction flags are quarantined deterministically. Qwen is the primary classifier. GLM is called only when Qwen's confidence is below the configured threshold. Disagreement always produces quarantine. API keys are read from the environment and are never written to the corpus manifest.

Only send externally licensed, non-private snippets to GLM. The program truncates excerpts to 6,000 characters, but legal permission still needs to be established before invoking the external API.

## Verification

Run the test suite without installing anything:

```powershell
python -m unittest discover -s tests -v
```
