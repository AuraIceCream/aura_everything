# AURA-Bio documentation hub

This is the map for the working AURA-Bio checkout. The root [README](../README.md)
is the complete, reproducible setup guide; this page helps you reach the right
level of detail without scanning it end-to-end.

## Start here

| If you want to… | Read / run |
|---|---|
| Start the local application | [Quick start](../README.md#quick-start) or `python scripts/launcher.py` |
| Install and run every component manually | [Complete-system guide](../README.md#running-the-complete-system) |
| Diagnose a local setup | [Troubleshooting](../README.md#troubleshooting) or `python scripts/launcher.py --headless-check` |
| Understand the product and system requirements | [System requirements specification](../srs.md) |
| See the current evidence and remaining work | [Roadmap and status](../ROADMAP.md) |
| Resume engineering work safely | [Developer handoff](../HANDOFF.md) |
| Plan matched model comparisons, domain packages, and visual support | [Evaluation and expansion plan](EVALUATION_AND_EXPANSION.md) |
| Improve evidence-backed answer accuracy and run the new mode | [Accuracy techniques and experiments](accuracy-boosting.md) |
| Upload and study private PDFs, slide decks, workbooks and notes | [Local study packs](study-packs.md) |
| Run explicit OCR/figure passes and inspect source crops | [Visual study packs](study-packs.md#visual-passes-2026-10-07) |
| Ask varied study questions or resolve figures/pages from a PDF | [Document question flow and limits](document-question-flow.md) |

## Component guides

| Component | Responsibility | Guide |
|---|---|---|
| Corpus acquisition | Provenance, licenses, bounded downloads, integrity checks | [Corpus section](../README.md#corpus-acquisition) |
| Processing pipeline | Cleaning, chunking, embeddings, sparse/dense indexes | [Pipeline README](../corpus_pipeline/README.md) |
| Runtime API | Routing, retrieval, generation, verification, tracing | [Runtime README](../aura_bio_system/README.md) |
| Web interface | Tutor, retrieval lab, evaluation, traces, corpus view | [Frontend README](../frontend/README.md) |
| Evaluation | Benchmark findings and reproducible comparisons | [Findings](../aura_bio_system/benchmarks/FINDINGS.md) |

## Architecture

<img src="images/aura-architecture.svg" alt="AURA-Bio architecture" width="960" />

The system can degrade deliberately: without Ollama it produces extractive,
evidence-based answers; without the dense index it continues with BM25. See the
[runtime guide](../aura_bio_system/README.md) for the precise switches and
resource trade-offs.

## Project conventions

- Keep secrets in `.env` or `frontend/.env.local`; neither belongs in Git.
- Keep large corpora, indexes, model caches, raw benchmark output, and build
  products out of the repository. The root `.gitignore` documents their paths.
- Do not treat a passing startup check as evidence that all stages are used.
  Use the liveness and benchmark checks described in the root README.
