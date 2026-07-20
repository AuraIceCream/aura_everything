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

### Data Collection Status: RECOVERY / IN PROGRESS

The previously collected biology corpus became corrupted and is not considered usable. The validated corpus total is therefore reset to **0 GB** until files pass checksum, format, licence, provenance, and quality checks.

The recovery target is up to **50 GB of raw source data**. This is a ceiling rather than a success metric; document quality, coverage, licensing, reproducibility, and retrieval performance take priority over byte volume.

The recovered collection may include:

- school-level books,
- undergraduate textbooks,
- open educational resources,
- biology reference material,
- research papers,
- encyclopedic sources,
- technical documentation,
- open-access biological resources,
- and domain-specific text.

Data collection will be considered complete only after the selected official-source files have been inventoried, validated, and recorded in the corpus manifest.

The next phase is:

- inventory creation,
- licence review,
- cleaning,
- deduplication,
- classification,
- and preparation.

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

The results of BM25 and dense retrieval should be combined.

Possible fusion approaches:

- Reciprocal Rank Fusion,
- weighted score fusion,
- normalised score fusion,
- and rank-based aggregation.

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

### Status: RECOVERY / IN PROGRESS

The earlier approximately 20 GB collection was corrupted and is no longer counted as a project deliverable. Collection is being rebuilt from official bulk datasets and APIs with a raw-data ceiling of approximately 50 GB.

Completed recovery-foundation activities:

- identification and licence review of initial official biology sources,
- implementation of resumable official-source acquisition,
- implementation of checksum and archive validation,
- implementation of manifests and quarantine handling,
- implementation of local Qwen curation with optional GLM fallback,
- and successful small-source and PMC XML smoke tests.

Remaining collection activities:

- execute the approved bulk-download plan,
- filter the Wikipedia and Wikibooks dumps to biology,
- normalize downloaded XML and structured data,
- review quarantined or ambiguous documents,
- and report the final validated corpus size.

Deliverables:

- validated raw biology corpus up to the approximately 50 GB ceiling,
- reproducible source registry,
- checksum and file manifest,
- licence and provenance records,
- and source-aware corpus folders.

Cleaning, deduplication, chunking, and retrieval preparation remain separate data-preparation work after acquisition.

---

## Phase 2: Corpus Inventory and Licence Review

### Status: PENDING

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

### Status: PENDING

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

### Status: PENDING

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

### Status: PENDING

Tasks:

1. Select BGE embedding model.
2. Generate embeddings for a controlled corpus subset.
3. Create FAISS index.
4. Implement query embedding.
5. Retrieve top-k chunks.
6. Display source metadata.
7. Evaluate Recall@k.

Deliverables:

- dense retrieval module,
- FAISS index,
- retrieval evaluation results.

---

## Phase 7: BM25 and Hybrid Retrieval

### Status: PENDING

Tasks:

1. Build BM25 index.
2. Implement sparse retrieval.
3. Combine dense and sparse results.
4. Test fusion methods.
5. Compare dense, sparse, and hybrid retrieval.
6. Analyse exact-term retrieval.

Deliverables:

- BM25 module,
- hybrid search module,
- retrieval comparison report.

---

## Phase 8: Reranking

### Status: PENDING

Tasks:

1. Select reranker.
2. Retrieve top 30 candidates.
3. Rerank candidates.
4. Select final top chunks.
5. Measure retrieval improvement.
6. Measure latency cost.

Deliverables:

- reranker module,
- reranking benchmark,
- latency analysis.

---

## Phase 9: Biology Router

### Status: PENDING

Tasks:

1. Define task labels.
2. Define biology subdomain labels.
3. Create rule-based router.
4. Add LLM JSON router.
5. Create routing evaluation dataset.
6. Evaluate routing accuracy.
7. Add confidence thresholds.

Deliverables:

- task router,
- biology subdomain router,
- routing benchmark.

---

## Phase 10: Teaching and Learner-Level Router

### Status: PENDING

Tasks:

1. Define learner levels.
2. Define teaching styles.
3. Create pedagogy policy.
4. Create teaching templates.
5. Add explicit user controls.
6. Add automatic level inference.
7. Evaluate teaching appropriateness.

Deliverables:

- learner router,
- pedagogy router,
- teaching templates,
- teaching evaluation set.

---

## Phase 11: Adaptive Context Manager

### Status: PENDING

Tasks:

1. Implement context levels 0–4.
2. Define policies for each task.
3. Add hierarchical retrieval.
4. Add evidence compression.
5. Add deep-mode planning.
6. Measure quality versus latency.

Deliverables:

- context manager,
- policy files,
- context-level benchmark.

---

## Phase 12: Biology Answer Generator

### Status: PENDING

Tasks:

1. Create biology system prompts.
2. Create teaching-mode prompts.
3. Create citation format.
4. Add context discipline.
5. Add insufficient-evidence response.
6. Add answer-format selection.

Deliverables:

- biology answer generator,
- prompt library,
- initial RAG chatbot prototype.

---

## Phase 13: Biology Verification Framework

### Status: PENDING

Tasks:

1. Implement claim extraction.
2. Implement claim-context matching.
3. Implement terminology checker.
4. Implement process-order checker.
5. Implement numerical checker.
6. Implement uncertainty labelling.
7. Generate structured verification output.

Deliverables:

- claim checker,
- terminology checker,
- process checker,
- numerical verifier,
- verification report.

---

## Phase 14: External Critic Integration

### Status: PENDING

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

### Status: PENDING

Tasks:

1. Connect verifier to critic.
2. Define accept/revise/reject decisions.
3. Implement one-loop revision.
4. Implement deep-mode two-loop revision.
5. Reverify revised answers.
6. Measure accuracy improvement.
7. Measure latency increase.

Deliverables:

- revision pipeline,
- before-and-after evaluation,
- revision success report.

---

## Phase 16: Pipeline Transparency and Logging

### Status: PENDING

Tasks:

1. Define trace schema.
2. Log router output.
3. Log retrieval results.
4. Log reranking.
5. Log final evidence.
6. Log draft and revised answers.
7. Log verifier output.
8. Log critic output.
9. Log latency and token usage.
10. Add developer trace viewer.

Deliverables:

- trace logger,
- query database,
- developer inspection interface.

---

## Phase 17: Dashboard Development

### Status: PENDING

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

### Status: PENDING

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

### Status: PENDING

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

### Status: OPTIONAL / FUTURE ADVANCED PHASE

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

## Milestone 1

Corpus recovered and inventoried.

Status:

- collection recovery in progress,
- inventory pending.

## Milestone 2

Cleaned and chunked biology corpus.

## Milestone 3

Baseline model and dense RAG working.

## Milestone 4

Hybrid retrieval and reranking evaluated.

## Milestone 5

Biology router and teaching router working.

## Milestone 6

Biology verification framework implemented.

## Milestone 7

Critic and revision loop integrated.

## Milestone 8

Transparent dashboard completed.

## Milestone 9

Full benchmark and ablation completed.

## Milestone 10

Optional LoRA and user study completed.

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
