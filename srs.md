# Software Requirements Specification and Project Implementation Plan

## AURA-Bio

### A Transparent, Evidence-Grounded, Adaptive Biology Tutoring and Reasoning System Using Local LLMs, Hybrid Retrieval, Verification, Critique, and Modular Domain Expansion

---

# 1. Project Overview

## 1.1 Project Title

**AURA-Bio: Adaptive Utility-Routed Assistant for Biology Learning and Reasoning**

## 1.2 Technical Title

**A Transparent Local Language Model System for Evidence-Grounded Biology Question Answering, Adaptive Teaching, Hybrid Retrieval, Structured Verification, and Failure-Driven Improvement**

## 1.3 Short Project Description

AURA-Bio is a local-first biology tutoring and question-answering system designed to improve the reliability of lightweight open-source language models.

Instead of relying entirely on the knowledge stored inside a small language model, the system combines:

- a biology-focused knowledge corpus,
- hybrid retrieval,
- adaptive task routing,
- teaching-style selection,
- evidence-grounded answer generation,
- biological claim verification,
- external critique during development,
- revision loops,
- transparent pipeline logging,
- benchmark-based evaluation,
- and optional LoRA-based domain adaptation.

The system is initially focused on biology because biology provides a sufficiently broad but manageable technical domain for developing and evaluating the complete architecture.

The same core architecture can later support additional specialist modules for:

- coding,
- mathematics,
- physics,
- logic,
- engineering,
- medicine,
- or other technical domains.

---

# 2. Explanation of the Idea

## 2.1 Problem Being Addressed

Small open-source language models are attractive because they can run locally, preserve privacy, reduce recurring API costs, and work without permanent dependence on commercial platforms.

However, these models often have several limitations:

1. They may hallucinate facts.
2. Their biology knowledge may be incomplete or outdated.
3. They may confuse similar biological terms.
4. They may produce explanations that are too simple or too technical.
5. They may fail to adapt their teaching style to the learner.
6. They may produce answers without source support.
7. They may misunderstand complex biological processes.
8. They may not clearly communicate uncertainty.
9. They may provide fluent but scientifically inaccurate answers.
10. Their improvement is often claimed without measurable evidence.

AURA-Bio addresses these limitations by surrounding the local model with a structured reasoning and verification pipeline.

---

## 2.2 Core Idea

The central idea is:

> A small local language model can become significantly more useful for biology education when combined with domain-specific knowledge retrieval, adaptive teaching, evidence checking, structured critique, and measurable evaluation.

Instead of using the model as a standalone chatbot, AURA-Bio treats the model as one component within a larger system.

The system performs the following operations:

1. Understands the user’s question.
2. Determines the biology subdomain.
3. Determines the learner’s academic level.
4. Determines the type of answer required.
5. Chooses an appropriate teaching style.
6. Retrieves relevant biological information.
7. Reranks and filters the retrieved evidence.
8. Generates a draft answer.
9. Verifies claims and terminology.
10. Uses a structured critic to identify weaknesses.
11. Revises the answer where required.
12. Provides the final answer with citations and confidence.
13. Logs the complete pipeline for analysis.
14. Stores failures for future improvement and fine-tuning.

---

## 2.3 Difference from a Basic RAG Chatbot

A basic Retrieval-Augmented Generation system usually follows:

```text
Question
→ Retrieve documents
→ Generate answer
```

AURA-Bio follows:

```text
Question
→ Task router
→ Biology subdomain classifier
→ Learner-level classifier
→ Teaching-style router
→ Context-level selector
→ BM25 retrieval
→ Dense retrieval
→ Result fusion
→ Reranking
→ Evidence selection
→ Draft generation
→ Biological verification
→ Structured critique
→ Revision
→ Final answer
→ Citations and confidence
→ Trace logging
→ Failure learning
```

Therefore, the project is not positioned as merely a chatbot.

It is positioned as:

> A transparent, evaluation-driven biology tutoring and reasoning system.

---

# 3. Project Vision

The long-term vision of AURA is to create a modular technical learning and reasoning platform in which a shared local LLM infrastructure can support several specialist domains.

The first implemented specialist module will be biology.

Future modules may include:

```text
AURA Core
├── Biology Module
├── Coding Module
├── Mathematics Module
├── Physics Module
├── Logic Module
└── Additional Domain Modules
```

Each module may contain its own:

- corpus,
- retrieval policy,
- prompts,
- verifier,
- evaluation benchmark,
- LoRA adapter,
- teaching modes,
- and domain-specific tools.

---

# 4. Project Objectives

## 4.1 Primary Objectives

The primary objectives are:

1. To develop a local-first biology tutoring system using an open-source language model.

2. To rebuild a validated biology corpus with a raw-data ceiling of approximately 50 GB for retrieval and possible future domain adaptation.

3. To implement document ingestion, cleaning, deduplication, chunking, and metadata generation.

4. To implement dense semantic retrieval using BGE embeddings.

5. To implement sparse keyword retrieval using BM25.

6. To combine dense and sparse retrieval through hybrid fusion.

7. To implement reranking for selecting the most useful context.

8. To build a biology-specific task and subdomain router.

9. To build a learner-level and teaching-style router.

10. To provide multiple adaptive teaching modes.

11. To verify biological claims against retrieved evidence.

12. To detect unsupported statements, terminology mistakes, and process inconsistencies.

13. To use Python-based tools for numerical biology questions.

14. To use an optional external model during development for critique and judging.

15. To implement a structured critique-revision loop.

16. To expose the entire pipeline through trace logs and dashboards.

17. To evaluate the contribution of each system component using ablation studies.

18. To build a failure-learning dataset for future LoRA or supervised fine-tuning.

19. To design the architecture so additional domains can later be added as modules.

---

## 4.2 Secondary Objectives

Secondary objectives include:

- generating revision notes,
- creating quizzes,
- generating flashcards,
- identifying misconceptions,
- supporting exam-oriented answers,
- supporting research-style explanations,
- adapting explanations to school and undergraduate levels,
- and measuring learning improvement where possible.

---

# 5. Project Scope

## 5.1 Initial Scope

The first implementation will focus on biology.

Supported areas may include:

- general biology,
- cell biology,
- molecular biology,
- genetics,
- evolution,
- ecology,
- botany,
- zoology,
- microbiology,
- human physiology,
- anatomy,
- immunology,
- biochemistry,
- biotechnology,
- developmental biology,
- neuroscience basics,
- bioinformatics concepts,
- and introductory research-paper interpretation.

---

## 5.2 Supported Task Types

AURA-Bio should support:

- factual questions,
- conceptual explanations,
- process explanations,
- comparison questions,
- definition-based questions,
- short-answer questions,
- long-answer questions,
- exam-oriented responses,
- homework assistance,
- misconception correction,
- numerical genetics questions,
- research-paper-based questions,
- revision notes,
- flashcards,
- quizzes,
- and self-assessment questions.

---

## 5.3 Out-of-Scope Features for the Initial Version

The following are not primary goals of the first version:

- diagnosis of diseases,
- treatment recommendation,
- prescription advice,
- clinical decision support,
- large-scale medical image analysis,
- full coding assistance,
- advanced symbolic mathematics,
- autonomous scientific research,
- or replacing human teachers.

Medical and health-related responses must remain educational and must not be presented as professional medical advice.

---

# 6. Intended Users

## 6.1 Primary Users

### School Students

Students studying biology at secondary or senior-secondary level.

They may use AURA-Bio for:

- concept explanations,
- exam preparation,
- homework support,
- revision,
- and misconception correction.

### Undergraduate Students

Students studying biology, biotechnology, life sciences, or related subjects.

They may use AURA-Bio for:

- deeper explanations,
- pathways,
- molecular mechanisms,
- research-paper understanding,
- and structured assignments.

### Teachers and Teaching Assistants

Teachers may use the system for:

- generating question sets,
- preparing revision material,
- identifying student misconceptions,
- and explaining topics at different levels.

### Researchers and Lab Students

Researchers may use it for:

- summarising papers,
- retrieving information from a controlled corpus,
- understanding biological terminology,
- and navigating documents.

---

## 6.2 User Personas

### Persona 1: High-School Student

Needs:

- simple explanations,
- examples,
- diagrams,
- exam-style answers,
- and revision material.

### Persona 2: Undergraduate Student

Needs:

- technically accurate explanations,
- mechanisms,
- terminology,
- citations,
- and deeper context.

### Persona 3: Instructor

Needs:

- level-adapted explanations,
- quizzes,
- learning objectives,
- and misconception analysis.

### Persona 4: Research-Oriented User

Needs:

- source-grounded answers,
- uncertainty communication,
- paper summaries,
- and detailed citations.

---

# 7. System Architecture

> **Implementation note.** This architecture is realised as three Python
> packages: `aura_corpus` (acquisition), `aura_bio_pipeline` (preparation and
> index building), and `aura_bio` (the per-query runtime — routing, retrieval,
> reranking, verification, critique, generation prompts, and tracing). The
> runtime stages below are implemented and unit-tested; the local model, the
> external critic client, and the dashboard are the remaining integrations.

## 7.1 High-Level Architecture

```text
                           User Query
                                ↓
                     Query Preprocessing
                                ↓
                       Task-Type Router
                                ↓
                  Biology Subdomain Router
                                ↓
                    Learner-Level Detector
                                ↓
                    Teaching-Style Router
                                ↓
                    Context-Level Selector
                                ↓
          ┌─────────────────────┴─────────────────────┐
          ↓                                           ↓
   Dense Retrieval                               BM25 Retrieval
   using BGE                                     Sparse Search
          ↓                                           ↓
          └─────────────────────┬─────────────────────┘
                                ↓
                         Hybrid Fusion
                                ↓
                            Reranker
                                ↓
                      Evidence Selection
                                ↓
                     Local Biology LLM
                                ↓
                         Draft Answer
                                ↓
               Biology Verification Framework
                                ↓
                      Structured Critic
                                ↓
                     Accept or Revise
                                ↓
                         Final Answer
                                ↓
               Citations, Confidence and Trace
                                ↓
                     Evaluation Dashboard
                                ↓
                     Failure Dataset
```

---

# 8. End-to-End Processing Pipeline

## 8.1 Query Processing

The system receives a user query and performs:

- text normalization,
- language detection,
- question-type detection,
- ambiguity detection,
- optional spelling correction,
- and query expansion.

Example query:

> Explain how DNA replication occurs for a Class 12 student.

The system should extract:

```json
{
  "domain": "biology",
  "subdomain": "molecular_biology",
  "task_type": "process_explanation",
  "learner_level": "senior_secondary",
  "teaching_mode": "guided_explanation",
  "context_level": 2,
  "needs_retrieval": true,
  "needs_process_verification": true
}
```

---

## 8.2 Task Router

The task router classifies the request into categories such as:

- factual recall,
- definition,
- concept explanation,
- process explanation,
- comparison,
- numerical question,
- misconception correction,
- research-paper question,
- exam answer,
- quiz generation,
- revision request,
- or summary.

The router should initially use:

- deterministic rules,
- keyword patterns,
- and a lightweight JSON-producing LLM classifier.

A small supervised router may later replace the LLM router.

---

## 8.3 Biology Subdomain Router

The system should classify the question into one or more biology subdomains.

Possible labels:

- general biology,
- cell biology,
- molecular biology,
- genetics,
- microbiology,
- botany,
- zoology,
- ecology,
- evolution,
- physiology,
- anatomy,
- immunology,
- biochemistry,
- biotechnology,
- neuroscience,
- developmental biology,
- bioinformatics,
- or interdisciplinary.

The subdomain may influence:

- corpus selection,
- retrieval filters,
- answer template,
- verifier policy,
- and LoRA adapter selection.

---

## 8.4 Learner-Level Detector

The system should support academic levels such as:

- elementary,
- middle school,
- high school,
- senior secondary,
- undergraduate,
- postgraduate,
- research,
- and general public.

The user may explicitly choose the level.

If no level is provided, the system may infer it from:

- terminology used,
- question complexity,
- conversation history,
- requested answer type,
- or selected course.

---

# 9. Adaptive Teaching System

## 9.1 Teaching-Style Router

The teaching-style router selects how the answer should be presented.

Possible teaching modes include:

### Direct Answer Mode

Provides a concise response.

Used for:

- quick factual queries,
- definitions,
- and simple revision.

### Guided Explanation Mode

Explains the topic through:

1. prerequisite knowledge,
2. intuition,
3. technical explanation,
4. example,
5. summary,
6. self-check.

### Socratic Mode

The system does not reveal the full answer immediately.

Instead, it asks guiding questions and provides hints.

### Exam Mode

Produces:

- definition,
- key points,
- mechanism,
- diagram guidance,
- applications,
- conclusion,
- and common mistakes.

### Homework Support Mode

Provides a complete structured explanation but includes reasoning and sources.

### Revision Mode

Produces:

- short notes,
- tables,
- mnemonics,
- flashcards,
- and recall questions.

### Misconception Repair Mode

Identifies an incorrect mental model and replaces it with a correct explanation.

### Research Mode

Uses:

- technical terminology,
- detailed evidence,
- source citations,
- uncertainty statements,
- and research-level explanations.

### Teach-Back Mode

Asks the learner to explain the concept and evaluates their explanation.

---

## 9.2 Standard Teaching Response Structure

A normal teaching response may contain:

1. Prerequisite concepts
2. Core idea
3. Simple explanation
4. Technical explanation
5. Ordered mechanism
6. Example or analogy
7. Limitation of analogy
8. Common misconception
9. Source-backed evidence
10. Summary
11. Self-check question

---

## 9.3 Pedagogical Adaptation

The output should adapt according to:

- age,
- academic level,
- prior knowledge,
- response length,
- preferred format,
- difficulty,
- and user intent.

The system should avoid unnecessary technical terminology for school-level users.

It should avoid oversimplification for advanced users.

---

# 10. Adaptive Context Levels

## 10.1 Level 0: No Retrieval

Used for:

- simple interactions,
- conversational assistance,
- and questions confidently handled by the local model.

## 10.2 Level 1: Standard Retrieval

Used for:

- definitions,
- one-topic explanations,
- and straightforward document questions.

Pipeline:

```text
Retrieve top 10
→ Rerank top 5
→ Generate answer
```

## 10.3 Level 2: Expanded Retrieval

Used for:

- multi-concept explanations,
- comparisons,
- and long exam answers.

Pipeline:

```text
Retrieve top 30
→ Rerank top 10
→ Compress evidence
→ Generate answer
```

## 10.4 Level 3: Hierarchical Retrieval

Used for:

- long books,
- large document collections,
- research papers,
- and broad biological topics.

Pipeline:

```text
Retrieve document summaries
→ Select relevant sections
→ Retrieve detailed chunks
→ Generate synthesis
```

## 10.5 Level 4: Deep Reasoning Mode

Used for:

- complex biological mechanisms,
- research questions,
- multi-document analysis,
- and ambiguous questions.

Pipeline:

```text
Plan
→ Broad retrieval
→ Evidence summary
→ Targeted retrieval
→ Draft
→ Verify
→ Critique
→ Revise
→ Final answer
```

---

# 11. Biology Dataset and Corpus

## 11.1 Dataset Status

### Data Collection Status: COMPLETE AND PROCESSED

The previously collected biology corpus became corrupted. It has been rebuilt from official bulk sources, verified, cleaned, deduplicated, and chunked.

All 3,659 completed manifest entries passed the full verifier with zero non-`ok`
results (compressed-stream integrity, archive safety, XML/JSON openability, PDF
signatures, and provider checksums where published). The acquisition root is
now treated as frozen and read-only.

The retrieval chunk corpus is **25.0 GiB compressed** across nine retrieval
sources plus one evaluation-only source:

| Source | Shards | GiB | Dense-embedded |
|---|---:|---:|---|
| `pubmed_filtered` | 1,262 | 21.799 | no — BM25 only |
| `pmc_oa_comm_xml` | 1,231 | 2.007 | yes |
| `uniprot_sprot` | 1 | 0.707 | yes |
| `wikipedia_biology` | 1,693 | 0.297 | yes |
| `nlm_litarch_biology` | 6,941 | 0.147 | yes |
| `gene_ontology` | 1 | 0.013 | yes |
| `mesh_descriptors` | 1 | 0.011 | yes |
| `biolibretexts_catalog` | 70 | 0.004 | yes |
| `reactome_summaries` | 1 | 0.002 | yes |
| `pubmedqa_labeled` | 1 | 0.001 | excluded from retrieval |

The `core` embedding profile is complete: **10,394,250 normalised
`BAAI/bge-base-en-v1.5` float16 vectors** (768 dimensions, 14.9 GiB) produced as
eleven atomic Kaggle GPU jobs, each carrying its exact source-shard range
mapping, input signatures, and a vector SHA-256. The dense FAISS index is built
in one pass directly from these job files; there is no need to re-expand them
into a per-source layout, which would duplicate 14.9 GiB for no retrieval
benefit.

`pubmed_filtered` is deliberately **not** dense-embedded. Its 26.4M chunks would
cost roughly 37.8 GiB of additional vectors, and SRS 14.2 wants PubMed for exact
terminology, which BM25 already serves. Dense PubMed is a later decision gated
on retrieval evaluation, not an assumption.

`pubmedqa_labeled` is excluded from every retrieval index. It is supervised and
evaluation material, and indexing it would contaminate the benchmark.

The 50 GB raw ceiling was a ceiling, not a target; quality, coverage, licensing,
reproducibility, and retrieval performance took priority over byte volume.

The collection includes:

- school-level books,
- undergraduate textbooks,
- open educational resources,
- biology reference material,
- research papers,
- encyclopedic sources,
- technical documentation,
- open-access biological resources,
- and domain-specific text.

Inventory, licence review, cleaning, deduplication, classification, and
chunking are complete. Retrieval chunks target 450 BGE tokens with 64-token
overlap and never exceed 510, because BGE Base v1.5 truncates above 512 and the
generic 500–900 range in SRS 13.1 would have silently discarded text from every
oversized chunk.

---

## 11.2 Important Distinction

The recovered raw corpus should not be used directly as LoRA instruction data.

It should be divided into different data categories.

### Knowledge Corpus

Used for retrieval.

Contains:

- books,
- papers,
- notes,
- educational resources,
- and reference material.

### Domain-Adaptive Pretraining Corpus

A cleaned subset may later be used for continued pretraining if sufficient hardware becomes available.

This is optional.

### Instruction-Tuning Dataset

A smaller, high-quality dataset containing:

- question-answer pairs,
- explanations,
- misconception corrections,
- context-grounded answers,
- and structured teaching examples.

### Evaluation Dataset

A completely separate dataset used only for measuring performance.

### Failure Dataset

Collected from system failures during development and testing.

---

# 12. Data Ingestion Pipeline

## 12.1 Supported Input Formats

The system should support:

- PDF,
- TXT,
- Markdown,
- HTML,
- DOCX,
- EPUB where possible,
- JSON,
- CSV,
- research-paper XML,
- and structured biological data documentation.

---

## 12.2 Data Processing Steps

```text
Raw Files
→ File Validation
→ Text Extraction
→ OCR if required
→ Encoding Normalisation
→ Header/Footer Removal
→ Reference Section Detection
→ Duplicate Detection
→ Language Filtering
→ Quality Filtering
→ Source Classification
→ Section Detection
→ Chunking
→ Metadata Creation
→ Embedding
→ Indexing
```

---

## 12.3 Data Cleaning

Cleaning may include:

- removing corrupted files,
- removing repeated headers,
- removing page numbers,
- removing watermarks,
- correcting broken line breaks,
- normalising Unicode,
- removing navigation text,
- removing repeated references,
- filtering extremely low-quality OCR,
- and excluding irrelevant content.

---

## 12.4 Deduplication

Deduplication should occur at:

- file level,
- document level,
- paragraph level,
- and chunk level.

Possible techniques:

- file hashes,
- normalised-text hashes,
- MinHash,
- locality-sensitive hashing,
- cosine similarity,
- and repeated n-gram detection.

Chunk ids are `sha256(document_id, ordinal, text)`. Structured sources dedupe
only within a shard, so an identical document that reaches two shards — for
example a PMC article returned in two fetch windows — yields two chunks with the
same id. The BM25 index builder therefore skips exact-duplicate chunk ids
(`INSERT OR IGNORE`) and reports the count, and the dense id map tolerates two
dense ids pointing at one chunk id. This keeps a duplicated passage from
appearing twice in results without discarding either representation upstream.

---

## 12.5 Data Quality Labels

Each source may receive:

- quality score,
- source type,
- academic level,
- domain,
- licence status,
- reliability level,
- publication year,
- and verification status.

Example:

```json
{
  "source_id": "bio_textbook_0023",
  "title": "Introduction to Molecular Biology",
  "source_type": "textbook",
  "academic_level": "undergraduate",
  "subdomain": "molecular_biology",
  "language": "en",
  "quality_score": 0.91,
  "licence": "open_access",
  "verification_status": "reviewed"
}
```

---

# 13. Chunking Strategy

## 13.1 Textbook Chunking

Use:

- chapter-aware splitting,
- section-aware splitting,
- subsection metadata,
- and token-based chunking.

Recommended initial size:

- 500–900 tokens,
- 10–20% overlap.

## 13.2 Research-Paper Chunking

Split using:

- abstract,
- introduction,
- methodology,
- results,
- discussion,
- conclusion,
- and figure captions.

## 13.3 Process-Oriented Content

For biological pathways and mechanisms, chunks should preserve:

- ordered steps,
- causes,
- outcomes,
- cellular location,
- and involved entities.

## 13.4 Metadata

Each chunk should include:

```json
{
  "chunk_id": "source_004_chapter_03_section_02_chunk_07",
  "source_id": "source_004",
  "title": "Cellular Respiration",
  "subdomain": "biochemistry",
  "section": "Electron Transport Chain",
  "academic_level": "undergraduate",
  "page": 143,
  "licence": "open_access",
  "text": "..."
}
```

---

# 14. Retrieval Architecture

## 14.1 Dense Retrieval

Dense retrieval uses BGE embeddings.

Candidate models:

- BGE Small,
- BGE Base,
- BGE Large,
- BGE-M3.

Initial recommendation:

- BGE Base for balanced performance,
- or BGE Small for faster testing.

Dense retrieval is useful when the user’s wording differs from the source.

---

## 14.2 Sparse Retrieval

BM25 should be used for:

- exact biological terms,
- gene names,
- protein names,
- enzyme names,
- abbreviations,
- pathways,
- technical keywords,
- and rare terminology.

---

## 14.3 Hybrid Retrieval

The results of BM25 and dense retrieval are combined with Reciprocal Rank
Fusion (k = 60) over three channels that are kept explicitly separate:

| Channel | Coverage | Weight |
|---|---|---:|
| Dense BGE | `core` profile, 10.4M vectors | 1.00 |
| Core BM25 | same eight sources as dense | 0.65 |
| PubMed BM25 | `pubmed_filtered`, lexical only | 0.85 |

The core BM25 channel is down-weighted because it is largely redundant with the
dense channel over the same documents. PubMed carries its own weight because it
is the only channel covering that corpus at all, so its rank information is not
duplicated anywhere else. A retrieval manifest records exactly which of the
three channels a given deployment actually has, so PubMed is never silently
reported as dense coverage.

Dense hits are resolved back to full evidence rows through the core BM25 store,
which is therefore required even when only dense retrieval is wanted.

---

## 14.3.1 Measured Storage and Query Decisions

These were settled by measurement on the real corpus, not by estimate.

**FTS5 `detail` level.** Over 12 biology queries scored to depth 50, a
`detail=none` index returned byte-identical BM25 scores and identical ordering
to `detail=full`, at 23% less disk and roughly 3x the query time. `detail=none`
is therefore the PubMed default and `detail=full` the core default, which keeps
phrase and NEAR queries available where they are cheap.

Projected full-PubMed index size at 26.4M chunks:

| Schema | Bytes/chunk | Projected |
|---|---:|---:|
| `detail=full` | 2,925 | 72.0 GiB |
| `detail=none` | 2,267 | 55.8 GiB |

**Rejected: compressed contentless FTS5.** Storing zlib text beside a
`content=''` index would have reached about 29 GiB, but `bm25()` returns `-0.0`
for every row of a contentless table, destroying ranking entirely. It is
recorded here so the idea is not retried.

**Query shape.** `ORDER BY bm25()` must score every matching row, so an OR of
all query terms degrades badly at PubMed scale where a single common term
matches millions of rows. Sparse search is conjunctive first and relaxes to OR
only when AND is too selective. This is also the semantics the exact-term
PubMed channel wants.

**Dense index layout.** The default is `IVF,PQ` rather than SQ8, forced by two
measured facts about the installed FAISS 1.14.3 on Windows:

- `IO_FLAG_MMAP` cannot read an IVF index on this build — it fails on a
  5,000-vector test index, not only at scale — so an index that does not fit in
  RAM cannot be served at all, and the on-disk inverted-list merge recipe
  (which reads its blocks through the same mmap path) is unusable.
- An SQ8 `core` index is ~7.6 GiB. With ~11.7 GiB free, loading it alongside
  the BGE query encoder and the cross-encoder reranker is too tight.

A `PQ96x8` core index (8 dimensions per 8-bit subquantizer) is roughly 1 GiB.
It is built in a single in-memory pass — train on a stratified sample across all
eleven jobs, then add every job in float32 batches — and loaded normally at
query time. Vectors are added in job-then-vector order, so their sequential
FAISS ids equal the `dense_map` ids without any explicit id bookkeeping. The
dense-id-to-chunk-id map is committed per shard and is resumable, because
mapping ten million chunks across 9,939 shards is itself slow. SQ8 and flat
remain available for smaller corpora and for exact-recall evaluation baselines.

---

## 14.4 Reranking

A reranker should score query-chunk relevance.

Candidate models:

- BGE reranker base,
- lightweight cross-encoders,
- or an external reranker for experimental comparison.

Pipeline:

```text
Dense top 30
+ BM25 top 30
→ Fusion
→ Top 30 combined
→ Rerank
→ Final top 5–10
```

---

## 14.5 Retrieval Evaluation

Metrics should include:

- Recall@5,
- Recall@10,
- MRR,
- nDCG,
- context precision,
- source diversity,
- and correct-source rank.

---

# 15. Base Model and Domain Adaptation

## 15.1 Local Base Model

Candidate lightweight models may include:

- Qwen-class small models,
- Phi-class models,
- Gemma-class models,
- Llama-class quantised models,
- or other suitable open models.

Selection should be based on:

- VRAM usage,
- RAM usage,
- inference speed,
- context length,
- licence,
- biology performance,
- and instruction-following quality.

---

## 15.2 Baseline Evaluation

Before any adaptation, the base model should be tested on:

- biology factual questions,
- process questions,
- misconception questions,
- numerical questions,
- and source-grounded questions.

This provides the baseline for later comparison.

---

## 15.3 LoRA-Based Domain Adaptation

LoRA should be introduced after:

- retrieval is stable,
- evaluation datasets exist,
- failure cases have been collected,
- and training examples have been curated.

Initial adapters may include:

### Biology Teaching Adapter

Improves:

- explanations,
- structure,
- examples,
- and level adaptation.

### Biology Grounding Adapter

Improves:

- citation discipline,
- source adherence,
- and refusal when evidence is insufficient.

### Biology Critic Adapter

Optional later module for structured critique.

---

## 15.4 Training Data Size

Initial instruction-tuning target:

- 5,000–20,000 high-quality examples.

Later expansion:

- 20,000–50,000 examples.

The priority is quality, not maximum quantity.

---

# 16. Biology Verification Framework

## 16.1 Evidence Support Checker

The system should divide the answer into claims.

Each claim should be matched against retrieved evidence.

Possible labels:

- supported,
- partially supported,
- unsupported,
- contradictory,
- or unverifiable.

---

## 16.2 Terminology and Entity Checker

The checker should identify issues involving:

- gene names,
- protein names,
- enzyme names,
- species names,
- anatomical terms,
- biological pathways,
- abbreviations,
- and synonyms.

It should detect:

- misspellings,
- invalid entities,
- species mixing,
- name confusion,
- and inconsistent abbreviations.

---

## 16.3 Process-Consistency Checker

For biological processes, the system should check:

- step order,
- missing steps,
- reversed causality,
- cellular location,
- reactants,
- products,
- and involved biological structures.

Examples:

- DNA replication,
- transcription,
- translation,
- mitosis,
- meiosis,
- glycolysis,
- Krebs cycle,
- electron transport chain,
- immune response,
- and photosynthesis.

---

## 16.4 Numerical Biology Verifier

Python or SymPy may be used for:

- Mendelian inheritance,
- Hardy–Weinberg calculations,
- population growth,
- enzyme kinetics,
- dilution calculations,
- probability,
- biostatistics,
- and sequence statistics.

---

## 16.5 Uncertainty Checker

The system should distinguish between:

- well-established textbook knowledge,
- debated scientific claims,
- incomplete evidence,
- hypothesis,
- and unsupported speculation.

---

# 17. External Critic and Judge

## 17.1 Role

A hosted model such as Gemini Flash, GLM Flash, or another available free model may be used during development as an external critic.

Its role is to:

- detect unsupported statements,
- evaluate completeness,
- compare answers against rubrics,
- identify terminology errors,
- propose corrections,
- and act as an external benchmark.

---

## 17.2 Important Constraint

The external model should not become the primary answer generator.

The core answer should still be produced through:

- the local model,
- retrieval,
- local context,
- and internal verification.

The external model should be treated as:

- an independent reviewer,
- a development-time judge,
- or an optional fallback.

---

## 17.3 Structured Critic Output

Example:

```json
{
  "answer_supported": true,
  "unsupported_claims": [],
  "terminology_errors": [],
  "process_errors": [],
  "missing_concepts": [
    "role of helicase"
  ],
  "academic_level_match": true,
  "teaching_quality_score": 4,
  "decision": "revise"
}
```

---

# 18. Critique and Revision Loop

## 18.1 Normal Mode

```text
Draft answer
→ Verification
→ Structured critique
→ One revision
→ Final answer
```

## 18.2 Deep Mode

```text
Draft
→ Evidence check
→ Biological verification
→ External critique
→ Revision
→ Second verification
→ Final answer
```

## 18.3 Revision Limits

Normal mode:

- maximum one revision.

Deep mode:

- maximum two revisions.

This prevents unnecessary latency and cost.

---

# 19. Pipeline Transparency

## 19.1 Trace Information

For every answer, the system should store:

- original query,
- task classification,
- subdomain classification,
- learner level,
- teaching mode,
- context level,
- retrieval strategy,
- BM25 results,
- dense retrieval results,
- fusion results,
- reranked results,
- final evidence,
- draft answer,
- verification output,
- critic output,
- revision output,
- final answer,
- latency,
- model used,
- API usage,
- and failure category.

---

## 19.2 User-Visible Transparency

The interface may allow users to view:

- sources used,
- why those sources were selected,
- confidence,
- verification status,
- and whether the answer was revised.

Detailed low-level traces may remain available only in developer mode.

---

# 20. Dashboard Requirements

## 20.1 Query Playground

Displays:

- user question,
- task classification,
- learner level,
- teaching mode,
- retrieval evidence,
- draft answer,
- verification results,
- critic feedback,
- final answer,
- and latency.

---

## 20.2 Retrieval Lab

Compares:

- BM25,
- dense retrieval,
- hybrid retrieval,
- and hybrid retrieval with reranking.

Metrics:

- Recall@k,
- MRR,
- nDCG,
- context precision,
- and final answer quality.

---

## 20.3 Biology Verification Page

Displays:

- extracted claims,
- supporting chunks,
- unsupported claims,
- terminology issues,
- process errors,
- and confidence.

---

## 20.4 Teaching Evaluation Page

Displays:

- academic-level appropriateness,
- prerequisite coverage,
- clarity,
- analogy quality,
- misconception correction,
- self-check quality,
- and readability.

---

## 20.5 Ablation Dashboard

Compares:

- base model,
- base with prompts,
- dense RAG,
- hybrid RAG,
- hybrid plus reranker,
- router,
- teaching router,
- verifier,
- critic,
- LoRA,
- and full system.

---

## 20.6 Failure Analysis Page

Displays:

- failed query,
- bad answer,
- failure category,
- missed evidence,
- critic comments,
- corrected answer,
- and training-data status.

---

# 21. Failure-Learning Pipeline

## 21.1 Failure Categories

Failures should be classified as:

- retrieval miss,
- incorrect reranking,
- unsupported claim,
- terminology error,
- process-order error,
- numerical error,
- incomplete answer,
- wrong learner level,
- poor teaching style,
- wrong routing,
- excessive context,
- insufficient context,
- critic error,
- or model hallucination.

---

## 21.2 Failure Record

```json
{
  "query": "Explain meiosis.",
  "learner_level": "high_school",
  "bad_answer": "...",
  "failure_type": "process_order_error",
  "verifier_feedback": "...",
  "critic_feedback": "...",
  "corrected_answer": "...",
  "approved_for_training": false
}
```

---

## 21.3 Future Use

Approved failure records may be used for:

- supervised fine-tuning,
- LoRA,
- preference optimisation,
- prompt improvement,
- router improvement,
- and retrieval evaluation.

---

# 22. Functional Requirements

## FR-01: User Query Input

The system shall accept biology questions through a user interface or API.

## FR-02: Task Classification

The system shall classify the type of user request.

## FR-03: Biology Subdomain Classification

The system shall classify the relevant biology domain.

## FR-04: Learner-Level Selection

The system shall allow explicit or inferred academic-level selection.

## FR-05: Teaching-Style Selection

The system shall select an appropriate teaching style.

## FR-06: Context-Level Selection

The system shall choose retrieval depth according to task complexity.

## FR-07: Document Ingestion

The system shall ingest supported document formats.

## FR-08: Metadata Generation

The system shall store source and section metadata.

## FR-09: Dense Retrieval

The system shall retrieve semantically relevant chunks.

## FR-10: Sparse Retrieval

The system shall retrieve exact biological terms using BM25.

## FR-11: Hybrid Fusion

The system shall combine sparse and dense retrieval results.

## FR-12: Reranking

The system shall rerank candidate chunks.

## FR-13: Answer Generation

The system shall generate answers using a local language model.

## FR-14: Citation Generation

The system shall attach source references where retrieval is used.

## FR-15: Biological Claim Verification

The system shall check major factual claims against evidence.

## FR-16: Terminology Verification

The system shall detect biological terminology inconsistencies.

## FR-17: Process Verification

The system shall check the ordering and consistency of biological processes.

## FR-18: Numerical Verification

The system shall verify supported numerical biology questions.

## FR-19: Structured Critique

The system shall generate structured critic output.

## FR-20: Revision

The system shall revise answers when errors are detected.

## FR-21: Trace Logging

The system shall log the complete processing pipeline.

## FR-22: Failure Logging

The system shall save failed answers and corrections.

## FR-23: Dashboard

The system shall provide evaluation and analytics pages.

## FR-24: Quiz Generation

The system should generate quizzes from selected topics.

## FR-25: Revision Material

The system should generate notes, flashcards, and recall questions.

## FR-26: Future Module Support

The architecture shall allow new domain modules to be integrated.

---

# 23. Non-Functional Requirements

## NFR-01: Accuracy

The system should improve factual accuracy over the raw base model.

## NFR-02: Faithfulness

Answers using retrieved context should remain consistent with that context.

## NFR-03: Transparency

The system should expose source and verification information.

## NFR-04: Privacy

Local documents should remain local unless the user explicitly enables external processing.

## NFR-05: Modularity

Components should be independently replaceable.

## NFR-06: Reproducibility

Experiments should be configuration-driven and logged.

## NFR-07: Performance

Simple queries should avoid the full deep pipeline.

## NFR-08: Scalability

The retrieval system should support growth of the corpus.

## NFR-09: Reliability

Failures should be detected and logged gracefully.

## NFR-10: Usability

The interface should be understandable to students.

## NFR-11: Maintainability

Code should follow a modular repository structure.

## NFR-12: Security

Code execution tools should be sandboxed.

## NFR-13: Explainability

The system should explain evidence and revision decisions.

## NFR-14: Cost Control

External API use should be optional and monitored.

---

# 24. Evaluation Framework

## 24.1 Biology Factual Evaluation

Tests:

- definitions,
- terminology,
- structures,
- functions,
- and established facts.

Metrics:

- factual accuracy,
- unsupported claim rate,
- and terminology correctness.

---

## 24.2 Process Evaluation

Tests:

- DNA replication,
- transcription,
- translation,
- mitosis,
- meiosis,
- respiration,
- photosynthesis,
- and immunity.

Metrics:

- correct step order,
- missing-step rate,
- causal correctness,
- and location accuracy.

---

## 24.3 Teaching Evaluation

Metrics:

- level appropriateness,
- prerequisite coverage,
- clarity,
- conceptual completeness,
- analogy accuracy,
- misconception correction,
- and self-check quality.

---

## 24.4 Retrieval Evaluation

Metrics:

- Recall@5,
- Recall@10,
- MRR,
- nDCG,
- context precision,
- and source coverage.

---

## 24.5 Grounding Evaluation

Metrics:

- citation coverage,
- claim support,
- faithfulness,
- unsupported claim count,
- and contradiction count.

---

## 24.6 Numerical Evaluation

Metrics:

- final-answer correctness,
- formula correctness,
- calculation accuracy,
- and correction success.

---

## 24.7 Learning Evaluation

A small student study may use:

```text
Pre-test
→ AURA teaching interaction
→ Post-test
→ Learning-gain measurement
```

Possible metrics:

- raw improvement,
- normalised learning gain,
- misconception reduction,
- and learner satisfaction.

---

# 25. Ablation Study

The following configurations should be compared:

1. Base model only
2. Base model with prompt templates
3. Base model with dense RAG
4. Base model with hybrid RAG
5. Hybrid RAG with reranking
6. Hybrid RAG with router
7. Hybrid RAG with teaching router
8. Hybrid RAG with biological verification
9. Hybrid RAG with critic
10. Hybrid RAG with revision
11. Hybrid RAG with biology LoRA
12. Full system

Example structure:

| System | Biology Accuracy | Faithfulness | Teaching Score | Unsupported Claims | Latency |
|---|---:|---:|---:|---:|---:|
| Base model | — | — | — | — | — |
| Dense RAG | — | — | — | — | — |
| Hybrid RAG | — | — | — | — | — |
| + Reranker | — | — | — | — | — |
| + Verifier | — | — | — | — | — |
| + Critic | — | — | — | — | — |
| + LoRA | — | — | — | — | — |
| Full system | — | — | — | — | — |

---

# 26. Hardware Requirements

## 26.1 Existing Resources

- Two laptops with NVIDIA GTX 1650 GPUs
- Kaggle free GPU access
- NVIDIA free development APIs
- General-purpose CPU and RAM
- Local storage
- Internet access

---

## 26.2 Local Hardware Usage

The GTX 1650 laptops will be used for:

- development,
- API/backend development,
- BM25,
- FAISS,
- dashboards,
- data preprocessing,
- small-model inference,
- and testing.

---

## 26.3 Cloud Resource Usage

Free or credited cloud resources will be used for:

- large embedding batches,
- reranker evaluation,
- batch model evaluation,
- optional LoRA experiments,
- and external judging.

---

# 27. Software Requirements

Core stack:

- Python
- FastAPI
- Streamlit
- Hugging Face Transformers
- Ollama or llama.cpp
- BGE embeddings
- FAISS
- Qdrant
- BM25
- cross-encoder reranker
- PyTorch
- PEFT
- bitsandbytes
- TRL
- SQLite
- PostgreSQL optionally
- Pandas
- NumPy
- scikit-learn
- SymPy
- pytest for future coding modules
- Git and GitHub
- Docker optionally

---

# 28. Repository Structure

```text
aura-bio/
│
├── README.md
├── requirements.txt
├── docker-compose.yml
├── .env.example
│
├── data/
│   ├── raw/
│   ├── inventory/
│   ├── cleaned/
│   ├── deduplicated/
│   ├── chunks/
│   ├── indexes/
│   ├── evals/
│   ├── training/
│   └── failures/
│
├── src/
│   ├── ingestion/
│   │   ├── parser.py
│   │   ├── cleaner.py
│   │   ├── deduplicator.py
│   │   ├── chunker.py
│   │   └── metadata.py
│   │
│   ├── retrieval/
│   │   ├── embedder.py
│   │   ├── faiss_store.py
│   │   ├── qdrant_store.py
│   │   ├── bm25.py
│   │   ├── fusion.py
│   │   └── reranker.py
│   │
│   ├── routing/
│   │   ├── task_router.py
│   │   ├── biology_router.py
│   │   ├── learner_router.py
│   │   ├── pedagogy_router.py
│   │   └── context_router.py
│   │
│   ├── generation/
│   │   ├── model_loader.py
│   │   ├── prompts.py
│   │   ├── generator.py
│   │   └── adapter_manager.py
│   │
│   ├── verification/
│   │   ├── claim_checker.py
│   │   ├── terminology_checker.py
│   │   ├── process_checker.py
│   │   ├── numerical_checker.py
│   │   └── uncertainty_checker.py
│   │
│   ├── critique/
│   │   ├── external_critic.py
│   │   ├── critic_schema.py
│   │   └── revision.py
│   │
│   ├── evaluation/
│   │   ├── eval_factual.py
│   │   ├── eval_process.py
│   │   ├── eval_retrieval.py
│   │   ├── eval_teaching.py
│   │   ├── eval_grounding.py
│   │   └── ablation.py
│   │
│   ├── logging/
│   │   ├── trace_logger.py
│   │   ├── failure_logger.py
│   │   └── metrics_logger.py
│   │
│   └── app/
│       ├── api.py
│       ├── cli.py
│       └── dashboard.py
│
├── training/
│   ├── prepare_sft.py
│   ├── prepare_preferences.py
│   ├── train_lora.py
│   └── configs/
│
├── notebooks/
│   ├── corpus_analysis.ipynb
│   ├── retrieval_experiments.ipynb
│   ├── eval_analysis.ipynb
│   └── lora_analysis.ipynb
│
└── reports/
    ├── architecture.md
    ├── dataset_report.md
    ├── evaluation_report.md
    ├── ablation_report.md
    └── final_report.pdf
```

---

# 29. Phase-Wise Implementation Plan

## Phase 0: Idea Finalisation and Scope Definition

### Status: COMPLETED

Tasks completed:

- selected biology as the first domain,
- finalised local-first architecture,
- retained modular future expansion,
- defined teaching and tutoring direction,
- defined retrieval and verification approach,
- defined external critic role,
- and identified available hardware.

Deliverables:

- project definition,
- architecture concept,
- scope,
- and initial requirements.

---

## Phase 1: Biology Data Collection

### Status: COMPLETED

The corrupted collection was rebuilt from official bulk datasets and APIs.

Completed:

- identification and licence review of official biology sources,
- resumable official-source acquisition,
- checksum and archive validation,
- manifests and quarantine handling,
- local Qwen curation with optional GLM fallback,
- the full bulk download across all nine retrieval sources,
- Wikipedia biology-category filtering,
- XML and structured-data normalisation,
- and a full verification pass: 3,659 of 3,659 entries `ok`, zero non-`ok`.

Deliverables produced: validated raw corpus, reproducible source registry,
checksum and file manifest, licence and provenance records, and source-aware
corpus folders.

---

## Phase 2: Corpus Inventory and Licence Review

### Status: COMPLETED

Tasks:

1. Create a complete file inventory.
2. Record source title and origin.
3. Identify file type.
4. Record licence status.
5. Mark redistribution restrictions.
6. Assign subdomain.
7. Assign academic level.
8. Detect corrupted files.
9. Detect missing metadata.
10. Generate corpus statistics.

Deliverables:

- `corpus_inventory.csv`
- licence summary,
- source classification report,
- corpus statistics dashboard.

---

## Phase 3: Data Cleaning and Deduplication

### Status: COMPLETED

Structured sources (PubMed, PMC, UniProt, GO, MeSH, Reactome, Wikipedia) use
their stable provider IDs as trusted uniqueness keys and skip the global
paragraph-fingerprint database, which is what makes a PubMed-scale ingest
tractable. Less structured books retain source-scoped document, paragraph, and
chunk fingerprints in SQLite.

Tasks:

1. Extract text.
2. Remove headers and footers.
3. Normalise Unicode.
4. Remove corrupted text.
5. Fix line breaks.
6. Detect OCR problems.
7. Remove irrelevant sections.
8. Deduplicate documents.
9. Deduplicate paragraphs.
10. Deduplicate chunks.
11. Assign quality scores.

Deliverables:

- cleaned corpus,
- deduplicated corpus,
- data quality report,
- removed-data log.

---

## Phase 4: Corpus Structuring and Chunking

### Status: COMPLETED

Tasks:

1. Detect chapters and sections.
2. Detect research-paper sections.
3. Create source-aware chunks.
4. Preserve process ordering.
5. Attach metadata.
6. Store chunk IDs.
7. Build chunk validation scripts.
8. Generate chunk statistics.

Deliverables:

- structured chunk dataset,
- metadata schema,
- chunk quality report.

---

## Phase 5: Baseline Local Model

### Status: PENDING

Tasks:

1. Select two or three candidate local models.
2. Run hardware benchmarks.
3. Measure RAM and VRAM usage.
4. Measure latency.
5. Create initial biology benchmark.
6. Run raw-model evaluation.
7. Select one primary base model.

Deliverables:

- baseline model,
- baseline evaluation report,
- hardware benchmark report.

---

## Phase 6: Dense Retrieval Prototype

### Status: SUBSTANTIALLY COMPLETE — evaluation outstanding

Done:

1. `BAAI/bge-base-en-v1.5` selected and used for the whole `core` profile.
2. Embeddings generated for all 10,394,250 core chunks on Kaggle GPUs.
3. FAISS `IVF,PQ96` index built in one pass from the eleven job shards and
   loaded into RAM at query time (this FAISS build cannot mmap IVF indexes).
4. Query embedding applied with the BGE query prefix.
5. Top-k retrieval with a dense-id to chunk-id map.
6. Source metadata carried on every hit.

Outstanding: Recall@k measurement, which needs the Phase 18 benchmark set.

---

## Phase 7: BM25 and Hybrid Retrieval

### Status: SUBSTANTIALLY COMPLETE — comparison report outstanding

Done: SQLite FTS5/BM25 indexes with a measured schema choice per corpus,
conjunctive-first sparse search, three-channel Reciprocal Rank Fusion, and a
retrieval manifest that records which channels a deployment actually has.

Outstanding: the dense-versus-sparse-versus-hybrid comparison report, which
needs the Phase 18 benchmark set.

---

## Phase 8: Reranking

### Status: IMPLEMENTED — benchmark outstanding

Done: a `BAAI/bge-reranker-base` cross-encoder stage that scores fused
candidates as query-passage pairs, reports latency, rank movement, and how many
passages it promoted from beyond the pre-rerank cut, and an evidence selector
with a per-source cap. The per-source cap matters because UniProt is 52% of the
dense corpus and would otherwise crowd out the prompt.

The reranker is optional at runtime so SRS 25 can measure with and without it.

Outstanding: the improvement and latency benchmark, which needs Phase 18.

---

## Phase 9: Biology Router

### Status: IMPLEMENTED — routing benchmark outstanding

Done: 13 task labels, 18 subdomain labels, a rule table carried as inspectable
data, margin-aware confidence, multi-subdomain detection that escalates to
`interdisciplinary`, and an optional JSON LLM classifier consulted only where
the rules are not confident. A classifier that fails, or returns a label outside
the allowed set, cannot take routing down.

Outstanding: a labelled routing evaluation dataset and accuracy measurement.

---

## Phase 10: Teaching and Learner-Level Router

### Status: IMPLEMENTED — teaching evaluation set outstanding

Done: 8 learner levels and 9 teaching modes, explicit user override recorded in
the trace, level inference from stated class or from the vocabulary the asker
used, and task-derived default teaching modes.

Outstanding: teaching templates per mode and the teaching-appropriateness
evaluation set.

---

## Phase 11: Adaptive Context Manager

### Status: IMPLEMENTED

Done: context levels 0–4 with per-level retrieve/rerank/revision budgets,
escalation on deep-reasoning markers and long queries, and a cap that stops
young-learner queries pulling depth the answer will not be allowed to use.

The two deep levels now have real strategies rather than a deeper top-k:

- **Level 3, hierarchical.** Broad retrieval ranks *documents* by the best score
  any of their chunks achieved, then neighbouring chunks from the top documents
  are pulled in, so a section split across several chunks is read as continuous
  context. Requires `document_id` on retrieved evidence, which the searcher now
  carries.
- **Level 4, deep reasoning.** The query is decomposed into sub-queries
  ("difference between mitosis and meiosis" → `mitosis`, `meiosis`), each is
  retrieved for separately, and the union is rank-fused so a passage found by
  several sub-queries ranks higher. It then applies the Level 3 expansion.
- **Evidence compression** trims each passage to the sentences that overlap the
  query, preserving original order, so a deep retrieval set fits the prompt
  budget. A passage with nothing relevant is passed through whole rather than
  emptied.

Outstanding: the quality-versus-latency benchmark for the deep levels.

---

## Phase 12: Biology Answer Generator

### Status: PROMPT LAYER IMPLEMENTED — local model integration outstanding

Done: a prompt builder that turns a route plus numbered evidence into system
and user messages. The system prompt enforces grounding, inline `[n]` citation,
first-use term definition below undergraduate level, and the medical-advice
disclaimer. Each teaching mode imposes its own answer structure and each learner
level its own vocabulary guidance, so mode and level visibly change the output
(SRS 35.5). Revision instructions are appended verbatim on a revision pass.

The generator is an adapter over any chat model, so the specific local model
(SRS 15.1) does not change the pipeline. The local model is now wired: the API's
`OllamaGenerator` drives **`aura-bio:v0`** (a persona-customised Qwen 3.5 4B)
through Ollama, with thinking disabled so the tutor answer — not the reasoning
scratchpad — fills the token budget. When Ollama is unreachable it falls back to
the extractive generator, so the system always runs.

Outstanding: the baseline hardware benchmark (Phase 5) and an optional LoRA
adapter (Phase 21).

---

## Phase 13: Biology Verification Framework

### Status: IMPLEMENTED

All seven tasks are implemented and covered by tests:

1. Claim extraction splits a draft into sentence-level statements, dropping
   headings, questions, and scaffolding, and stripping citation markers so
   `[1]` is not mistaken for an asserted quantity.
2. Claim-context matching labels each claim `supported`, `partially_supported`,
   `unsupported`, `contradictory`, or `unverifiable`. `unverifiable` (nothing
   retrieved) is kept distinct from `unsupported` (evidence exists and does not
   cover the claim) because those demand different responses. A claim whose
   numbers appear nowhere in the evidence cannot be labelled fully supported
   however many of its words match.
3. Terminology checking covers misspellings, confusable pairs, invalid
   binomials, and unexpanded abbreviations, the last only at school levels.
4. Process-order checking compares stated step order against canonical
   orderings for nine processes, and separately catches a process placed in the
   wrong cellular compartment.
5. The numerical verifier recomputes Hardy-Weinberg, Mendelian ratios,
   population growth, Michaelis-Menten, dilution, and carrier-cross probability
   through SymPy. A solver that cannot recognise a question returns nothing, so
   silence means "not checkable", never "correct". A method stated without a
   figure is `unstated`, not `incorrect`. No model-generated code is executed,
   which satisfies NFR-12 directly.
6. Uncertainty labelling separates established, debated, incomplete,
   hypothesis, and speculation, and flags an unsupported absolute stated as
   settled fact as an error.
7. The structured report carries claims, issues by severity, citation coverage,
   grounded fraction, numerical checks, a decision, and a confidence.

Each checker can be disabled independently so SRS 25 can attribute its
contribution.

### Calibration against real model output

Running the verifier over 243 real answers exposed three false-positive rules
that would have driven pointless revisions — making the full pipeline score
*worse* and run slower than the baseline. All three are fixed and pinned by
regression tests:

1. **Overstatement.** The absolutes list contained bare `all`, `every`, and
   `none`, so a true statement like "the cell is the basic unit of all living
   organisms" was flagged. Biology is full of correct universals; the list now
   holds only genuinely risky ones (`always`, `never`, `without exception`,
   `every single`, `invariably`).
2. **Absence of evidence.** A claim labelled `unverifiable` — meaning nothing
   was retrieved — could raise an overstatement *error*. That is a statement
   about corpus coverage, not about the answer, so only `unsupported` (evidence
   retrieved and failing to cover the claim) can now raise it.
3. **Misspellings.** Detection used substring matching, so the correct
   `chlorophyll` matched the misspelling `chlorophyl`. It now requires word
   boundaries.
4. **Step order.** This one needed three passes, each exposing the next layer:
   - first-mention position was read as asserted order, so an answer to "what
     happens during S phase?" was flagged for naming its own topic first. Order
     is now judged only when the answer asserts a sequence;
   - a sequence marker anywhere in a multi-thousand-character answer was enough
     to qualify, so the named steps must also sit within ~600 characters of each
     other, and a *bulleted* list no longer counts (it enumerates parts; a
     numbered list implies order);
   - step names matched inside unrelated compounds — "anaphase" in
     "anaphase-promoting complex" (a protein) and "termination" in "termination
     signal" (a stop codon) — so lookup now requires whole-term boundaries that
     reject hyphenated compounds;
   - finally, a connective must appear *between* the two step mentions, not
     merely somewhere in the answer. A checkpoint explainer is organised by
     checkpoint rather than chronologically, so it names anaphase before
     metaphase without ever claiming that order. "anaphase, **then** metaphase"
     is a claim; "anaphase. If errors are found … during metaphase" is not.
5. **Process location.** The checker flagged a wrong compartment whenever the
   process and that compartment co-occurred within a 220-character window. But
   "mature red blood cells lack mitochondria entirely, because they rely on
   anaerobic glycolysis" asserts the *opposite* of what it was flagged for. It
   now requires an explicit locative link ("occurs in the", "is where") between
   process and compartment inside a single sentence.
6. **Hardy-Weinberg premise parsing.** The solver treated any number near the
   word "recessive" as q², so "dominant allele frequency p = 0.7 … homozygous
   recessive individuals" was read as q² = 0.7 and a correct answer of 0.09 was
   marked wrong. It now reads an explicitly stated p or q as the premise, and
   grades whichever quantity the question actually asks for (q², 2pq, p², or q)
   rather than always grading 2pq.
7. **Overstatement is a warning, not an error.** Even with a narrowed absolutes
   list, the rule fires mostly on rhetorical absolutes in teaching prose —
   "membranes are never static" is correct biology and is precisely the point
   of the misconception question it answers. Surface keywords cannot separate
   epistemic overreach from emphasis, so the rule now surfaces the claim for
   review instead of forcing a revision. The claim-support labels carry the
   hard signal, and an unsupported claim still prevents acceptance on its own.

The lesson generalises: a checker tuned only on synthetic examples will fire on
real prose, and the failure is asymmetric — a false error costs a wasted
revision and a worse score, while a missed warning costs only a review. Rules
that cannot be made precise belong at warning severity. Every rule here is now
exercised against real generated answers.

---

## Phase 14: External Critic Integration

### Status: IMPLEMENTED

Done: the validated critic schema and tolerant parser; concrete clients for
**GLM (Z.AI, `glm-4.7-flash`)** and **Gemini (`gemini-2.5-flash`)** behind one
`Critic` interface; per-call latency and token accounting; and the SRS 17.2
guarantee that the external model is never the primary generator. The critic is
opt-in per request (`allow_external_critic`, NFR-14 cost control) and per
deployment (`AURA_CRITIC`).

A labelled comparison harness (`compare_critics`) scores each critic on 12
biology answers with planted errors — decision accuracy, false-accept rate
(the dangerous direction), false-revise rate, agreement with the deterministic
verifier, latency, and tokens. Measured live: **GLM `glm-4.7-flash` scored
0.92-1.0 decision accuracy with zero false-revises, versus 0.75 for the
deterministic verifier alone**, so the external critic adds real error-catching
without nagging on sound answers. Gemini runs the moment a `GEMINI_API_KEY` is
present.

The two Risk-4 safety properties are enforced and tested: an untrusted critic
cannot block a clean answer, and an approving critic cannot override a verifier
error.

GLM is the selected critic; Gemini is implemented but deprioritised. Free-tier
providers rate-limit bursts, so the client retries 429/5xx with exponential
backoff honouring `Retry-After`, and the comparison paces its calls. A call
that still fails is marked untrusted, which by the Risk-4 rule can never clear
or block an answer on its own.

Outstanding: longer-run cost tracking across a full evaluation, and the Gemini
side of the comparison if a key is ever added.

---

Tasks:

1. Select free or low-cost critic model.
2. Define critic schema.
3. Add API abstraction.
4. Add token and cost logging.
5. Implement critic fallback.
6. Compare multiple critics.
7. Ensure local model remains primary generator.

Deliverables:

- external critic module,
- structured judge outputs,
- critic comparison report.

---

## Phase 15: Critique-Revision Loop

### Status: IMPLEMENTED — before/after evaluation outstanding

Done: verifier and critic are combined into one decision, revision runs to the
per-context-level budget (one loop normally, two in deep mode), and every pass
re-verifies. Revision instructions are derived from actual findings, so the
revision prompt names the specific defect rather than asking for a better
answer.

Two safety properties are enforced and tested, both from SRS 31 Risk 4:

- a critic returning malformed output is marked untrusted and cannot block an
  answer the deterministic verifier already cleared;
- a critic saying `accept` cannot override a verifier error.

Outstanding: measuring accuracy improvement and added latency, which needs
Phase 18.

---

## Phase 16: Pipeline Transparency and Logging

### Status: IMPLEMENTED — viewer outstanding

Done: a versioned trace schema recording routing, retrieval channel counts,
reranking movement, selected evidence, every draft with its verification and
critique, the decision, per-stage latency, and the failure category. Traces go
to SQLite for the dashboard and to JSONL for export. A separate user-facing
view exposes sources, confidence, verification status, and whether the answer
was revised, keeping low-level internals to developer mode as SRS 19.2 requires.

Failure records follow the SRS 21.2 shape and default to
`approved_for_training = 0`, so nothing reaches a training export without the
human approval SRS 21.3 requires.

Outstanding: the developer trace viewer, which is part of Phase 17.

---

## Phase 17: Dashboard Development

### Status: FRONTEND AND API IMPLEMENTED — some panels use pipeline output directly

The dashboard is a Vite + React 19 + TanStack Query + Tailwind app
(`frontend/`), not Streamlit: Ask (query playground), Retrieval lab, Evaluation
(benchmark and ablation), Corpus readiness, Pipeline traces, and Settings.

A FastAPI backend (`aura_bio.api`) serves the app against the real runtime:
`/api/v1/health`, `/capabilities`, `/corpus/status`, `/runs` (POST + GET),
`/runs/{id}/events` (SSE), `/retrieval/search`, and `/evaluation/summary`. Runs
execute the real pipeline; the SSE endpoint replays the genuine trace and
streams the real answer, so the progressive UI is backed by real routing,
retrieval, and verification. Every dependency is optional (NFR-09): with no
model it answers extractively from evidence; with no dense index it serves the
instant BM25 channels. `AURA_DENSE=1` opts into the dense channel where RAM
allows.

Outstanding: wiring the local model for fluent generation, and the failure and
teaching-quality panels beyond what the trace already exposes.

---

Tasks:

1. Build query playground.
2. Build retrieval lab.
3. Build verification page.
4. Build teaching-quality page.
5. Build ablation page.
6. Build failure-analysis page.
7. Add export functions.

Deliverables:

- Streamlit dashboard,
- evaluation visualisations,
- downloadable result files.

---

## Phase 18: Evaluation Dataset Development

### Status: BENCHMARK AND HARNESS IMPLEMENTED — retrieval-relevance labels outstanding

A curated benchmark of **441 biology questions** spans all 18 subdomains, the
task types, and learner levels from high school to research
(`aura_bio.evaluation`, exported to `benchmarks/biology_benchmark.jsonl`). Every
item carries a machine-checkable answer key so grading does not depend on an LLM
judge (SRS 31 Risk 4): factual items list required and forbidden concepts,
numerical items (10) are recomputed with SymPy, process items (12) are checked
for step order, and **8 adversarial items** name non-existent entities to score
hallucination — a correct answer refuses rather than fabricates.

A deterministic scorer and a four-system harness implement the SRS 25 ablation:
`baseline`, `basic_rag` (hybrid retrieval only), `full_rag` (the whole
pipeline), and `finetuned_rag`. The harness produces the SRS 25 comparison
table (overall, concept recall, numeric accuracy, process-order accuracy,
hallucination rate, forbidden-claim rate, latency) and skips a system that is
not available yet rather than faking it.

Outstanding: gold retrieval-relevance labels for Recall@k/MRR/nDCG on the
built indexes, and the held-out train/validation/test split.

---

Tasks:

1. Create factual questions.
2. Create process questions.
3. Create misconception questions.
4. Create numerical questions.
5. Create source-grounded questions.
6. Create teaching-quality rubrics.
7. Create adversarial hallucination questions.
8. Create train-validation-test separation.

Deliverables:

- biology benchmark dataset,
- retrieval benchmark,
- teaching benchmark,
- verification benchmark.

---

## Phase 19: Full Ablation Study

### Status: PENDING

Tasks:

1. Evaluate base model.
2. Evaluate dense RAG.
3. Evaluate hybrid RAG.
4. Evaluate reranker.
5. Evaluate router.
6. Evaluate teaching router.
7. Evaluate verifier.
8. Evaluate critic.
9. Evaluate revision.
10. Evaluate full pipeline.

Deliverables:

- ablation tables,
- graphs,
- component contribution analysis,
- error analysis.

---

## Phase 20: Failure-Learning Dataset

### Status: CAPTURE IMPLEMENTED — curation UI outstanding

Done: the 14-category failure taxonomy, automatic categorisation from stage
output, failure records in the SRS 21.2 shape, and an export that emits
`failures.jsonl`. Records default to `approved_for_training = 0`, so nothing
reaches a training export without the human approval SRS 21.3 requires.

Outstanding: the human approval interface and the corrected-answer capture flow.

---

Tasks:

1. Define failure categories.
2. Store failed answers.
3. Store verifier feedback.
4. Store critic feedback.
5. Store corrected answers.
6. Add human approval.
7. Export training records.

Deliverables:

- `failures.jsonl`
- approved SFT dataset,
- failure-analysis dashboard.

---

## Phase 21: Biology LoRA Adapter

### Status: DATA PREPARED — training not started

A ~300 MB training corpus is built at `G:\aura_data\AURA-Training\`, mixing
**30% question-answer records with 70% biology prose**. Every record carries its
provenance, because the three QA sources are not equally valuable:

- `gold` — 125 answers that passed both the benchmark answer key and corpus
  verification, with supporting chunk ids;
- `pubmedqa` — ~723 expert-labelled research questions with evidence and a
  conclusion;
- `template` — questions derived structurally from a chunk's title and section.
  These teach answer *format* and grounding, not reasoning: a question
  mechanically derived from the answer it is paired with cannot supervise
  inference. A training run can down-weight or drop them by `kind`.

Selection is by teaching register rather than coverage. Structured record
sources (UniProt, GO, MeSH, Reactome — 5.7M chunks) are excluded, since training
on a database record teaches the model to emit database records. A
topical-relevance check was necessary beyond prose quality: biographies of
biologists and clinical systematic reviews are excellent prose that teaches no
biology, and rejecting them removed roughly 19,000 chunks per 20 MB kept.

Sizing is deliberate and argued in `benchmarks/FINETUNING_DATA.md`. Measured at
~4.1 characters per token, 1 GiB would be ~262M tokens — 10–15 days of
continuous training on a GTX 1650, or about two weeks of Kaggle quota, to move a
metric that is already at 0.822 with 55% of questions perfect. The measured gap
is behavioural (hallucination at 0.375), which is learned from demonstrations,
not from more prose. **Start with SFT and explicit refusal examples**; consider
continued pretraining only if the benchmark then shows knowledge gaps that
retrieval cannot close.

Tasks:

1. Curate high-quality instruction examples.
2. Split training and evaluation data.
3. Configure QLoRA.
4. Run small pilot training.
5. Compare adapter with base model.
6. Evaluate catastrophic degradation.
7. Integrate adapter routing.

Deliverables:

- biology LoRA adapter,
- training report,
- adapter ablation results.

---

## Phase 22: User Study

### Status: OPTIONAL

Tasks:

1. Recruit a small student group.
2. Create pre-test and post-test.
3. Conduct teaching interaction.
4. Measure learning gain.
5. Collect user feedback.
6. Analyse usability and teaching quality.

Deliverables:

- user study report,
- learning-gain analysis,
- usability findings.

---

## Phase 23: Final Documentation and Demonstration

### Status: PENDING

Tasks:

1. Write final report.
2. Create architecture diagrams.
3. Prepare README.
4. Prepare installation guide.
5. Record demonstration video.
6. Create evaluation summary.
7. Document limitations.
8. Prepare final presentation.

Deliverables:

- final technical report,
- GitHub repository,
- demo video,
- presentation,
- model card,
- dataset card.

---

# 30. Milestones

## Milestone 1 — DONE

Corpus recovered, verified (3,659/3,659 `ok`), inventoried, cleaned,
deduplicated, and chunked (25.0 GiB across nine retrieval sources).

## Milestone 2 — DONE

Cleaned and chunked biology corpus, plus the complete `core` embedding set
(10,394,250 BGE vectors).

## Milestone 3 — PARTIAL

Dense retrieval (IVF-PQ index) built; baseline local model still to be selected.

## Milestone 4 — PARTIAL

Hybrid retrieval and the reranker are implemented; the comparison needs the
Phase 18 benchmark set.

## Milestone 5 — DONE

Task, subdomain, learner-level, teaching, and context routers implemented and
tested.

## Milestone 6 — DONE

Biology verification framework implemented (claims, terminology, process order
and location, SymPy numerical, uncertainty, citations).

## Milestone 7 — DONE

Critic schema and the bounded critique-revision loop integrated, with the
deterministic-checks-win safety guarantees.

## Milestone 8 — PARTIAL

Trace and failure logging implemented (SQLite + JSONL); the Streamlit dashboard
is the remaining piece.

## Milestone 9

Full benchmark and ablation.

## Milestone 10

Optional LoRA and user study.

---

# 31. Risks and Mitigation

## Risk 1: Corpus Quality

Problem:

The recovered corpus may contain low-quality, duplicated, or inconsistent sources.

Mitigation:

- quality scoring,
- licence tracking,
- deduplication,
- source filtering,
- and controlled subsets.

---

## Risk 2: Limited Hardware

Problem:

GTX 1650 laptops cannot perform heavy model training.

Mitigation:

- use quantised models,
- use Kaggle,
- use cloud credits,
- limit LoRA size,
- and prioritise retrieval over heavy pretraining.

---

## Risk 3: External Critic Dependency

Problem:

The system may appear dependent on Gemini or GLM.

Mitigation:

- keep local model as generator,
- treat external critic as optional,
- compare with and without critic,
- and report the critic contribution separately.

---

## Risk 4: LLM Judge Errors

Problem:

An LLM critic may approve incorrect answers.

Mitigation:

- prioritise evidence checks,
- use structured rubrics,
- use deterministic numerical checks,
- and include human review in evaluation.

---

## Risk 5: Biology Hallucinations

Problem:

Answers may contain fluent but inaccurate biological claims.

Mitigation:

- strict source grounding,
- claim support checking,
- terminology checking,
- uncertainty labelling,
- and revision.

---

## Risk 6: Teaching-Style Mismatch

Problem:

The explanation may not match the learner’s level.

Mitigation:

- explicit user-level selection,
- readability checks,
- pedagogy evaluation,
- and user feedback.

---

## Risk 7: Copyright and Licensing

Problem:

Some collected data may not be redistributable.

Mitigation:

- maintain source and licence metadata,
- separate private corpus from distributable corpus,
- do not upload restricted sources,
- and release only permitted derived assets.

---

## Risk 8: Overcomplexity

Problem:

Too many components may delay the project.

Mitigation:

Build in this order:

1. clean corpus,
2. baseline,
3. dense retrieval,
4. hybrid retrieval,
5. teaching system,
6. verification,
7. critic,
8. dashboard,
9. LoRA.

---

# 32. Security and Privacy

The system should:

- process private documents locally where possible,
- avoid uploading private documents to external critics,
- redact sensitive information,
- store API keys securely,
- sandbox code execution for future coding modules,
- maintain access controls,
- and log external API usage.

---

# 33. Future Domain Modules

## 33.1 Coding Module

Possible features:

- code corpus,
- repository retrieval,
- code-aware chunking,
- pytest,
- runtime sandbox,
- linting,
- code repair,
- and coding LoRA.

---

## 33.2 Mathematics Module

Possible features:

- mathematical corpus,
- equation parsing,
- SymPy,
- numeric verification,
- proof rubrics,
- and step checking.

---

## 33.3 Physics Module

Possible features:

- formula database,
- unit consistency,
- dimensional analysis,
- numerical solver,
- and simulation tools.

---

## 33.4 Logic Module

Possible features:

- constraint solving,
- symbolic reasoning,
- contradiction detection,
- and multi-path consistency checking.

---

## 33.5 Modular Plugin Interface

Each plugin should define:

```text
domain name
corpus
router labels
prompt templates
verification tools
evaluation dataset
optional LoRA adapter
dashboard metrics
```

---

# 34. Expected Deliverables

The final project should produce:

1. Cleaned and structured biology corpus.
2. Corpus inventory and licence report.
3. Local biology LLM interface.
4. Dense retrieval system.
5. BM25 retrieval system.
6. Hybrid fusion pipeline.
7. Reranking module.
8. Biology task router.
9. Learner-level router.
10. Teaching-style router.
11. Adaptive context manager.
12. Evidence-grounded answer generator.
13. Biological claim verifier.
14. Terminology checker.
15. Process checker.
16. Numerical verifier.
17. Structured external critic.
18. Critique-revision loop.
19. Transparent trace logger.
20. Evaluation dashboard.
21. Biology benchmark dataset.
22. Full ablation study.
23. Failure-learning dataset.
24. Optional biology LoRA adapter.
25. Final report.
26. Demo video.
27. GitHub repository.
28. Future plugin architecture.

---

# 35. Acceptance Criteria

The project will be considered successfully implemented when:

1. The system can ingest and retrieve from the biology corpus.

2. Hybrid retrieval performs better than at least one single retrieval method on the prepared benchmark.

3. The router correctly assigns most evaluation questions to their expected categories.

4. The system can generate answers at multiple learner levels.

5. Teaching modes visibly change answer structure.

6. Retrieved answers include source references.

7. Unsupported claims can be flagged.

8. At least selected biological processes can be checked for ordering and consistency.

9. Numerical biology questions can be verified programmatically where applicable.

10. The critic produces valid structured output.

11. The revision loop can improve at least a measurable subset of failed answers.

12. The dashboard displays pipeline traces and metrics.

13. The complete system is compared against the base model.

14. Limitations and failures are reported honestly.

---

# 36. Final Project Positioning

AURA-Bio should be presented as:

> A transparent, evidence-grounded adaptive biology tutoring system that combines a lightweight local language model, a curated biology corpus, hybrid retrieval, learner-aware pedagogy routing, biological verification, structured critique, and evaluation-driven failure learning.

It should not be presented as:

- merely a biology chatbot,
- a ChatGPT clone,
- a generic RAG application,
- or a fully autonomous teaching system.

Its main contribution is:

> Demonstrating how a lightweight local model can be made more reliable, adaptive, and educationally useful through system-level architecture rather than model size alone.

---

# 37. Conclusion

AURA-Bio is a modular biology tutoring and reasoning system designed to improve the usefulness of lightweight local language models.

The project begins by rebuilding the corrupted biology collection from official, reproducible sources. The recovered corpus will be checksummed, licence-tracked, cleaned, structured, indexed, and used for retrieval and possible later domain adaptation.

The system will combine:

- hybrid BM25 and BGE retrieval,
- reranking,
- task and subdomain routing,
- adaptive teaching styles,
- learner-level adaptation,
- context-level selection,
- evidence-grounded generation,
- biological verification,
- optional external critique,
- revision loops,
- transparent tracing,
- benchmark evaluation,
- and failure-driven improvement.

The project is designed to be technically meaningful while remaining feasible on limited hardware.

Biology serves as the first specialist domain, while the architecture remains extensible to coding, mathematics, physics, logic, and other technical areas.

The final goal is not simply to produce fluent answers.

The goal is to build a system that can:

- retrieve evidence,
- teach at the correct level,
- identify uncertainty,
- verify important claims,
- explain how an answer was produced,
- learn from failures,
- and prove its improvements through evaluation.
