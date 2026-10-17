"""Pipeline trace and failure logging (SRS 19, 21).

Every stage writes into one trace record so the dashboard can show why an
answer looks the way it does, and so a failure can be replayed later. Traces go
to SQLite because the dashboard needs to filter and aggregate them, and a JSONL
mirror because SRS 21.2 wants an exportable failure dataset.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

#: SRS 21.1 failure taxonomy.
FAILURE_CATEGORIES = (
    "retrieval_miss",
    "incorrect_reranking",
    "unsupported_claim",
    "terminology_error",
    "process_order_error",
    "numerical_error",
    "incomplete_answer",
    "wrong_learner_level",
    "poor_teaching_style",
    "wrong_routing",
    "excessive_context",
    "insufficient_context",
    "critic_error",
    "model_hallucination",
)


@dataclass(slots=True)
class Trace:
    """One end-to-end query, stage by stage."""

    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    query: str = ""
    route: dict[str, Any] = field(default_factory=dict)
    retrieval: dict[str, Any] = field(default_factory=dict)
    rerank: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    revisions: list[dict[str, Any]] = field(default_factory=list)
    selected_revision: int = -1
    final_answer: str = ""
    decision: str = ""
    confidence: float = 0.0
    #: Traceability of the final answer — what fraction of its claims carry a
    #: citation, and whether those citations point anywhere relevant. See
    #: :mod:`aura_bio.verification.provenance`.
    provenance: dict[str, Any] = field(default_factory=dict)
    #: Entities the question names that no corpus naming authority lists.
    unknown_entities: list[str] = field(default_factory=list)
    failure_category: str | None = None
    model: str = ""
    stage_ms: dict[str, float] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @property
    def latency_ms(self) -> float:
        return round(sum(self.stage_ms.values()), 1)

    @property
    def final_record(self) -> dict[str, Any]:
        if not self.revisions:
            return {}
        index = self.selected_revision if 0 <= self.selected_revision < len(self.revisions) else -1
        return self.revisions[index]

    @property
    def final_verification(self) -> dict[str, Any]:
        return self.final_record.get("verification", {})

    @property
    def revision_count(self) -> int:
        if any("phase" in record for record in self.revisions):
            return sum(record.get("phase") == "revision" for record in self.revisions)
        return max(0, len(self.revisions) - 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "trace_id": self.trace_id,
            "query": self.query,
            "route": self.route,
            "retrieval": self.retrieval,
            "rerank": self.rerank,
            "evidence": self.evidence,
            "revisions": self.revisions,
            "selected_revision": self.selected_revision,
            "final_verification": self.final_verification,
            "final_answer": self.final_answer,
            "decision": self.decision,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "unknown_entities": self.unknown_entities,
            "failure_category": self.failure_category,
            "model": self.model,
            "stage_ms": {name: round(value, 1) for name, value in self.stage_ms.items()},
            "latency_ms": self.latency_ms,
            "created_at": self.created_at,
        }

    def user_view(self) -> dict[str, Any]:
        """SRS 19.2: what a learner sees, without the developer internals."""

        return {
            "sources": [
                {
                    "n": index,
                    "title": item.get("title"),
                    "section": item.get("section"),
                    "source": item.get("source_id"),
                    "url": item.get("url"),
                    "why": item.get("channel"),
                }
                for index, item in enumerate(self.evidence, 1)
            ],
            "confidence": self.confidence,
            "verification": self.decision,
            "traceability": {
                "claims_with_a_source": self.provenance.get("claim_citation_rate"),
                "claims_without_a_source": self.provenance.get("unsupported_assertion_rate"),
                "distinct_sources": self.provenance.get("distinct_sources"),
            },
            "revised": self.revision_count > 0,
            "learner_level": self.route.get("learner_level", {}).get("label"),
            "teaching_mode": self.route.get("teaching_mode", {}).get("label"),
        }


class Stopwatch:
    """Times one stage and records it on the trace."""

    def __init__(self, trace: Trace, stage: str) -> None:
        self.trace = trace
        self.stage = stage

    def __enter__(self) -> Stopwatch:
        self._started = time.perf_counter()
        return self

    def __exit__(self, *exception: object) -> None:
        elapsed = (time.perf_counter() - self._started) * 1000
        self.trace.stage_ms[self.stage] = self.trace.stage_ms.get(self.stage, 0.0) + elapsed


_TABLES = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    query TEXT NOT NULL,
    task_type TEXT,
    subdomain TEXT,
    learner_level TEXT,
    teaching_mode TEXT,
    context_level INTEGER,
    decision TEXT,
    confidence REAL,
    revisions INTEGER NOT NULL DEFAULT 0,
    latency_ms REAL,
    failure_category TEXT,
    model TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS traces_created_at ON traces(created_at);
CREATE INDEX IF NOT EXISTS traces_failure ON traces(failure_category);

CREATE TABLE IF NOT EXISTS failures (
    trace_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    query TEXT NOT NULL,
    learner_level TEXT,
    bad_answer TEXT NOT NULL,
    failure_type TEXT NOT NULL,
    verifier_feedback TEXT,
    critic_feedback TEXT,
    corrected_answer TEXT,
    approved_for_training INTEGER NOT NULL DEFAULT 0
);
"""


class TraceStore:
    """SQLite trace store with a JSONL mirror for export."""

    def __init__(self, path: Path, jsonl_path: Path | None = None) -> None:
        self.path = path
        self.jsonl_path = jsonl_path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(_TABLES)
        self.connection.commit()

    def record(self, trace: Trace) -> None:
        payload = trace.as_dict()
        route = trace.route
        self.connection.execute(
            """
            INSERT OR REPLACE INTO traces (
                trace_id, created_at, query, task_type, subdomain, learner_level,
                teaching_mode, context_level, decision, confidence, revisions,
                latency_ms, failure_category, model, payload
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                trace.trace_id,
                trace.created_at,
                trace.query,
                _label(route, "task_type"),
                _label(route, "subdomain"),
                _label(route, "learner_level"),
                _label(route, "teaching_mode"),
                route.get("context_level"),
                trace.decision,
                trace.confidence,
                len(trace.revisions),
                trace.latency_ms,
                trace.failure_category,
                trace.model,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        self.connection.commit()
        if self.jsonl_path is not None:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with self.jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def record_failure(
        self,
        trace: Trace,
        failure_type: str,
        corrected_answer: str | None = None,
        approved: bool = False,
    ) -> None:
        """Store an SRS 21.2 failure record for later curation.

        ``approved_for_training`` defaults to false: SRS 21.3 requires human
        approval before a failure becomes training data.
        """

        if failure_type not in FAILURE_CATEGORIES:
            raise ValueError(f"Unknown failure category: {failure_type}")
        first = trace.revisions[0] if trace.revisions else {}
        self.connection.execute(
            """
            INSERT OR REPLACE INTO failures (
                trace_id, created_at, query, learner_level, bad_answer, failure_type,
                verifier_feedback, critic_feedback, corrected_answer, approved_for_training
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                trace.trace_id,
                trace.created_at,
                trace.query,
                _label(trace.route, "learner_level"),
                first.get("answer", trace.final_answer),
                failure_type,
                json.dumps(first.get("verification"), ensure_ascii=False),
                json.dumps(first.get("critique"), ensure_ascii=False),
                corrected_answer,
                int(approved),
            ),
        )
        self.connection.commit()

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT payload FROM traces ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def export_failures(self, path: Path, approved_only: bool = True) -> int:
        """Write failures.jsonl (SRS 20.6 deliverable)."""

        query = "SELECT * FROM failures"
        if approved_only:
            query += " WHERE approved_for_training = 1"
        rows = self.connection.execute(query).fetchall()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".part")
        with temporary.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
        os.replace(temporary, path)
        return len(rows)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> TraceStore:
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()


def _label(route: dict[str, Any], key: str) -> str | None:
    value = route.get(key)
    if isinstance(value, dict):
        return value.get("label")
    return value if isinstance(value, str) else None


def classify_failure(trace: Trace) -> str | None:
    """Best-effort automatic failure category from what the stages reported."""

    if not trace.revisions:
        return None
    last = trace.final_record
    verification = last.get("verification") or {}
    issues = verification.get("issues") or []
    kinds = {issue.get("kind") for issue in issues}
    if "step_order" in kinds or "wrong_location" in kinds:
        return "process_order_error"
    if "wrong_value" in kinds:
        return "numerical_error"
    if any(kind in kinds for kind in ("misspelling", "invalid_species")):
        return "terminology_error"
    if not trace.evidence and trace.route.get("needs_retrieval"):
        return "retrieval_miss"
    if verification.get("decision") == "insufficient_evidence":
        return "insufficient_context"
    if verification.get("unsupported_claim_count"):
        return "unsupported_claim"
    return None
