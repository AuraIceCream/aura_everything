"""Build a corpus-verified gold answer set from a benchmark run.

The baseline scores answers against hand-authored answer keys. That says the
answer contains the right concepts; it does not say the corpus agrees. This
script adds the second, independent check: for every candidate answer it
retrieves real evidence from the built index and runs the deterministic
verifier over it.

An answer reaches the gold set only if it passes **both** gates:

1. it scored a perfect ``overall`` against its answer key, and
2. the verifier grounds it in retrieved corpus evidence above ``--min-grounded``
   with no error-severity issues.

The result is a set of question/answer pairs that are simultaneously
key-correct and corpus-supported, which is exactly the shape SRS 15.4/21.3 want
for supervised fine-tuning seed data — and, unlike the raw run, every record
carries the chunk ids that support it.

    python aura_bio_system/benchmarks/build_gold_set.py \
        --results aura_bio_system/benchmarks/results/baseline_aura-bio_v0.jsonl \
        --index-root D:\\aura_data\\AURA-Bio-Index
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from aura_bio.evaluation import all_questions
from aura_bio.verification import BiologyVerifier, EvidencePassage
from aura_bio.routing import QueryRouter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a corpus-verified gold answer set")
    here = Path(__file__).resolve().parent
    parser.add_argument("--results", type=Path,
                        default=here / "results" / "baseline_aura-bio_v0.jsonl")
    parser.add_argument("--index-root", type=Path, default=Path(r"G:\aura_data\AURA-Bio-Index"))
    parser.add_argument("--out", type=Path, default=here / "gold")
    parser.add_argument("--min-score", type=float, default=1.0,
                        help="answer-key score required to be considered (default: perfect)")
    parser.add_argument("--min-grounded", type=float, default=0.5,
                        help="minimum verifier grounded_fraction against retrieved evidence")
    parser.add_argument("--top-k", type=int, default=6, help="evidence passages per question")
    parser.add_argument("--dense", action="store_true", help="also use the dense channel (more RAM)")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)

    rows = [json.loads(line) for line in args.results.read_text(encoding="utf-8").splitlines() if line.strip()]
    candidates = [r for r in rows if r["score"]["overall"] >= args.min_score and not r.get("error")]
    if args.limit:
        candidates = candidates[: args.limit]
    print(f"{len(rows)} answers, {len(candidates)} at score >= {args.min_score}", flush=True)

    questions = {q.id: q for q in all_questions()}
    from aura_bio_pipeline.retrieval import HybridSearcher
    from aura_bio.device import resolve_device

    searcher = HybridSearcher(
        args.index_root, device=resolve_device(), dense_enabled=args.dense
    )
    verifier = BiologyVerifier()
    router = QueryRouter()

    args.out.mkdir(parents=True, exist_ok=True)
    gold_path = args.out / "gold_answers.jsonl"
    rejected_path = args.out / "rejected_ungrounded.jsonl"
    started = time.perf_counter()
    kept = rejected = 0
    try:
        with gold_path.open("w", encoding="utf-8") as gold, \
             rejected_path.open("w", encoding="utf-8") as rejects:
            for index, row in enumerate(candidates, 1):
                question = questions.get(row["id"])
                if question is None:
                    continue
                hits = searcher.search(question.question, top_k=args.top_k, candidate_k=50)
                passages = [
                    EvidencePassage(
                        chunk_id=h.chunk_id, text=h.text, title=h.title, source_id=h.source_id
                    )
                    for h in hits
                ]
                route = router.route(question.question)
                report = verifier.verify(row["answer"], passages, route, question.question)
                grounded = report.grounded_fraction
                blocking = [i.as_dict() for i in report.issues if i.severity == "error"]
                record = {
                    "id": row["id"],
                    "question": question.question,
                    "answer": row["answer"],
                    "subdomain": question.subdomain,
                    "task_type": question.task_type,
                    "level": question.level,
                    "answer_key_score": row["score"]["overall"],
                    "grounded_fraction": round(grounded, 3),
                    "supporting_chunk_ids": sorted(
                        {cid for c in report.claims for cid in c.evidence_chunk_ids}
                    ),
                    "sources": sorted({h.source_id for h in hits}),
                    "verifier_issues": blocking,
                }
                if grounded >= args.min_grounded and not blocking:
                    gold.write(json.dumps(record, ensure_ascii=False) + "\n")
                    gold.flush()
                    kept += 1
                else:
                    rejects.write(json.dumps(record, ensure_ascii=False) + "\n")
                    rejects.flush()
                    rejected += 1
                if index % 10 == 0 or index == len(candidates):
                    elapsed = time.perf_counter() - started
                    rate = index / elapsed if elapsed else 0
                    print(
                        f"[{index}/{len(candidates)}] kept={kept} rejected={rejected} "
                        f"eta={(len(candidates) - index) / rate / 60 if rate else 0:.1f}min",
                        flush=True,
                    )
    finally:
        searcher.close()

    summary = {
        "source_results": str(args.results),
        "candidates": len(candidates),
        "gold": kept,
        "rejected_ungrounded": rejected,
        "min_answer_key_score": args.min_score,
        "min_grounded_fraction": args.min_grounded,
        "dense_used": args.dense,
        "gold_path": str(gold_path),
    }
    (args.out / "gold_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
