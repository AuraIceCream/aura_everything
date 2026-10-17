"""Compare evidence policies without a generator; keys are used only to score output."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from aura_bio.env import load_env
from aura_bio.evaluation import all_questions
from aura_bio.evaluation.scorer import _present, normalise_orthography
from aura_bio.retrieval.reranker import CrossEncoderReranker, select_evidence, select_diverse_evidence
from aura_bio.retrieval.strategies import compress_evidence, retrieve_for_level, query_variants
from aura_bio.routing import QueryRouter
from aura_bio.routing.encoder_router import load_default_classifier
from aura_bio_pipeline.retrieval import HybridSearcher


def main():
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-root", type=Path, default=Path(r"G:\aura_data\AURA-Bio-Index"))
    parser.add_argument("--ids-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    ids = args.ids_file.read_text(encoding="utf-8-sig").split()
    questions = {question.id: question for question in all_questions()}
    router = QueryRouter(classifier=load_default_classifier())
    searcher = HybridSearcher(args.index_root, dense_enabled=True, device="cpu")
    reranker = CrossEncoderReranker(device="cpu")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    totals = {mode: 0 for mode in ("standard", "robust")}
    terms_total = 0
    try:
        # Exclusive creation prevents replacing an existing experiment.
        with args.out.open("x", encoding="utf-8") as handle:
            for index, qid in enumerate(ids, 1):
                question = questions[qid]
                route = router.route(question.question)
                # Answer keys never reach either retrieval/selection function.
                terms = [term for term in question.answer_key.must_include
                         if not _present(normalise_orthography(question.question.lower()), term)]
                terms_total += len(terms)
                row = {"id": qid, "question": question.question, "novel_terms": terms,
                       "context_level": route.context_level, "policies": {}}
                for mode in totals:
                    started = time.perf_counter()
                    searcher.phrase_enabled = mode == "robust"
                    candidates = retrieve_for_level(searcher, searcher.core, question.question,
                                                    route.context_level, route.retrieve_k,
                                                    expand_queries=mode == "robust")
                    ranked, report = reranker.rerank(question.question, candidates, len(candidates))
                    if mode == "robust":
                        selected = select_diverse_evidence(question.question, ranked, min(route.rerank_k, 6))
                    else:
                        selected = select_evidence(ranked[:route.rerank_k], route.rerank_k)
                    if route.context_level >= 3:
                        selected = compress_evidence(question.question, selected)
                    text = normalise_orthography(" ".join(item.text for item in selected).lower())
                    hits = [term for term in terms if _present(text, term)]
                    totals[mode] += len(hits)
                    row["policies"][mode] = {
                        "hits": hits, "passages": len(selected), "chars": sum(len(item.text) for item in selected),
                        "queries": query_variants(question.question) if mode == "robust" else [question.question],
                        "evidence": [item.as_dict() for item in selected], "rerank": report.as_dict(),
                        "seconds": round(time.perf_counter() - started, 2),
                    }
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                print(f"[{index}/{len(ids)}] {qid} standard={len(row['policies']['standard']['hits'])} "
                      f"robust={len(row['policies']['robust']['hits'])}/{len(terms)}", flush=True)
    finally:
        searcher.close()
    summary = {"questions": len(ids), "novel_terms": terms_total, "hits": totals,
               "note": "Exact phrase coverage; does not establish answer correctness or citation faithfulness."}
    args.out.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
