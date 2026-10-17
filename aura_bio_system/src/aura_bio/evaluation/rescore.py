"""Regrade saved answers without inference; preserve original runs and traces."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .scorer import STRICT_NUMBER_AGREEMENT, score_answer
from .schema import BenchmarkQuestion


def rescore_file(source: Path, questions: dict[str, BenchmarkQuestion],
                 suffix: str) -> tuple[Path, dict]:
    if not suffix or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in suffix):
        raise ValueError("Suffix must contain only letters, digits, underscores or hyphens")
    out = source.with_name(f"{source.stem}.{suffix}.jsonl")
    summary_path = out.with_suffix(".summary.json")
    if out.exists() or summary_path.exists():
        raise FileExistsError(out)
    original = source.read_bytes()
    latest = {}
    for line in original.decode("utf-8-sig").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        previous = latest.get(row["id"])
        if previous is None or not row.get("error") or previous.get("error"):
            latest[row["id"]] = row
    updated = []
    changed = 0
    for qid, row in latest.items():
        if qid not in questions:
            raise ValueError(f"Unknown question id: {qid}")
        score = score_answer(questions[qid], row.get("answer", "")).as_dict()
        if row.get("error"):
            # A failed request is not an answer. Empty keys otherwise award
            # concept recall by default and can turn infrastructure errors
            # into positive scores.
            score.update(overall=0.0, concept_recall=0.0)
            if score["numeric_correct"] is not None:
                score["numeric_correct"] = False
            if score["order_correct"] is not None:
                score["order_correct"] = False
            if score["hallucinated"] is not None:
                score["hallucinated"] = True
            score["detail"]["request_error"] = True
        previous_score = row.get("score")
        changed += previous_score != score
        updated.append({**row, "score": score, "rescoring": {
            "policy": "numeric-conclusion-20261004", "previous_score": previous_score,
            "trace_not_rerun": True,
        }})
    summary = {
        "questions": len(updated), "errors": sum(bool(r.get("error")) for r in updated),
        "overall_mean": round(sum(r["score"]["overall"] for r in updated) / len(updated), 4) if updated else None,
        "changed_scores": changed, "source": str(source),
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "scorer_sha256": hashlib.sha256(Path(__file__).with_name("scorer.py").read_bytes()).hexdigest(),
        "question_bank_sha256": hashlib.sha256(json.dumps(
            [questions[qid].as_dict() for qid in sorted(latest)], sort_keys=True
        ).encode("utf-8")).hexdigest(),
        "strict_scorer": STRICT_NUMBER_AGREEMENT, "trace_not_rerun": True,
    }
    with out.open("x", encoding="utf-8") as handle:
        for row in updated:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with summary_path.open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    return out, summary
