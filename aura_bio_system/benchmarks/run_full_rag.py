"""Run the benchmark through the complete AURA-Bio pipeline (SRS 25 config 10).

Mirrors ``run_baseline.py`` exactly — same questions, same scorer, same output
shape — so the two runs are directly comparable. The difference is what
produces the answer: here it is the full pipeline (routing, hybrid retrieval,
optional reranking, evidence selection, verification, optional external
critique, and the bounded revision loop) rather than a bare model call.

``--system`` selects which configuration is being measured:

* ``basic_rag`` — retrieval stuffed into the prompt, no rerank/verify/critique
  (SRS 25 config 4). Isolates what retrieval alone buys.
* ``full_rag``  — everything (config 10).
* ``finetuned_rag`` — same as ``full_rag``; pass the adapted model with
  ``--model`` (config 11).

Resumable: answers append as they are produced and a restart skips finished
questions, so a long run survives interruption.

    python aura_bio_system/benchmarks/run_full_rag.py --system full_rag
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from aura_bio.api.generation import ExtractiveGenerator, OllamaGenerator
from aura_bio.device import resolve_device
from aura_bio.env import load_env
from aura_bio.evaluation import all_questions, score_answer
from aura_bio.evaluation.harness import SystemResult
from aura_bio.evaluation.manifest import ensure_run_manifest
from aura_bio.evaluation.scorer import QuestionScore
from aura_bio.pipeline import AuraBioPipeline
from aura_bio.routing import QueryRouter
from aura_bio.verification import BiologyVerifier


def _done_ids(path: Path) -> set[str]:
    """Question ids that completed *successfully* and need not be re-run.

    A row carrying an ``error`` deliberately does not count as done. Those rows
    hold no answer and score 0.00, and they are almost always infrastructure
    rather than model behaviour -- a local server that ran out of VRAM, a
    machine that ran out of disk. Treating them as finished bakes a transient
    failure into the results file permanently: the resume skips them, the
    summary averages the zeros in, and the only way to retry is to notice and
    delete the file by hand. A six-question smoke run failed exactly this way,
    reporting ``done=6 remaining=0`` against six HTTP 500s.
    """

    if not path.is_file():
        return set()
    done: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                row = json.loads(line)
                if not row.get("error"):
                    done.add(row["id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return done


def main(argv: list[str] | None = None) -> int:
    # Before argparse: --critic resolves its provider from the environment, and
    # the key lives in the repository .env rather than the shell.
    load_env()
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Full-pipeline benchmark run")
    parser.add_argument("--system", choices=("basic_rag", "full_rag", "finetuned_rag"),
                        default="full_rag")
    parser.add_argument("--model", default="aura-bio:v0", help="Ollama model tag")
    parser.add_argument("--index-root", type=Path, default=Path(r"G:\aura_data\AURA-Bio-Index"))
    parser.add_argument("--out", type=Path, default=here / "results")
    parser.add_argument("--dense", action="store_true",
                        help="enable the dense channel (needs several GiB free RAM)")
    parser.add_argument("--phrase-search", action="store_true",
                        help="add exact adjacent content-word matches from the core index")
    parser.add_argument("--accuracy-mode", choices=("standard", "robust"), default="standard",
                        help="robust: query expansion, diverse evidence, verified candidate selection")
    parser.add_argument("--draft-candidates", type=int, default=2,
                        help="independent drafts in robust mode (1-5), followed by bounded revisions")
    parser.add_argument("--rerank", action="store_true", help="enable the cross-encoder reranker")
    parser.add_argument("--no-compress-evidence", action="store_true",
                        help="keep full selected passages at deep context levels; "
                             "diagnostic ablation of question-overlap compression")
    parser.add_argument("--revision-context", action="store_true",
                        help="include the prior draft in standard-mode repairs; "
                             "robust mode always includes it")
    parser.add_argument("--rerank-device", default="cpu",
                        help="device for the cross-encoder. Defaults to cpu: this card has "
                             "4 GiB and the LLM needs all of it, so putting the reranker on "
                             "cuda pushes the model partly onto CPU and slows generation, "
                             "which costs far more than reranking saves")
    parser.add_argument("--critic", action="store_true",
                        help="enable the external GLM critic (uses API quota)")
    parser.add_argument("--limit", type=int, help="cap questions, for a quick check")
    parser.add_argument("--ids", help="comma-separated question ids to run, for a targeted check")
    parser.add_argument("--ids-file", type=Path,
                        help="file of question ids, one per line; the way to run the "
                             "identical subset across systems")
    parser.add_argument("--tag", help="override the output filename stem")
    parser.add_argument("--questions", type=Path,
                        help="a benchmark JSONL to use instead of the built-in 441")
    parser.add_argument("--rules-router", action="store_true",
                        help="force the rule router even when a trained one exists, "
                             "so the ablation can attribute the difference")
    parser.add_argument("--teaching-mode", choices=(
        "direct_answer", "guided_explanation", "socratic", "exam",
        "homework_support", "revision", "misconception_repair", "research", "teach_back",
    ), help="override answer format while keeping all pipeline stages enabled")
    parser.add_argument("--prompt-profile", choices=("standard", "compact"),
                        default="standard", help="select generation prompt profile; "
                                                 "compact is experimental for small models")
    parser.add_argument("--num-predict", type=int, default=1024,
                        help="generation token budget; must match run_baseline.py "
                             "for the two runs to be comparable")
    parser.add_argument("--seed", type=int, help="Ollama sampling seed for matched experiments")
    parser.add_argument("--num-gpu-layers", type=int, default=99,
                        help="Ollama layer offload; lower values preserve VRAM when dense "
                             "retrieval and the model share a small GPU")
    parser.add_argument("--num-ctx", type=int, default=8192,
                        help="context window. Larger is not free: if the model plus its "
                             "KV cache exceeds free VRAM, Ollama silently splits it onto "
                             "the CPU and generation slows several-fold. Check with "
                             "'ollama ps' that PROCESSOR reads 100%% GPU")
    parser.add_argument("--unload-model-between-requests", action="store_true",
                        help="ask Ollama to release model memory after each generation "
                             "on memory-constrained hosts (slower, same pipeline stages)")
    parser.add_argument("--no-warm", action="store_true",
                        help="skip pulling the indexes into page cache first "
                             "(see warm_index.py for why that is expensive here)")
    parser.add_argument("--extractive", action="store_true",
                        help="answer from evidence without a model, to isolate retrieval")
    args = parser.parse_args(argv)

    # Check provenance before warming indexes or loading any models.
    tag = args.tag or f"{args.system}_{args.model.replace(':', '_')}"
    results_path = args.out / f"{tag}.jsonl"
    summary_path = args.out / f"{tag}.summary.json"
    settings_path = args.out / f"{tag}.settings.json"
    settings = {key: str(value) if isinstance(value, Path) else value
                for key, value in vars(args).items()}
    ensure_run_manifest(
        settings_path, results_path, settings,
        [here.parent / "src", here.parent.parent / "corpus_pipeline" / "src",
         Path(__file__), here.parent / "pyproject.toml",
         here.parent.parent / "corpus_pipeline" / "pyproject.toml"],
        [path for path in (args.questions, args.ids_file) if path is not None],
    )

    if not args.no_warm:
        from warm_index import warm_index

        warm_index(args.index_root, dense=args.dense)

    from aura_bio_pipeline.retrieval import HybridSearcher

    searcher = HybridSearcher(
        args.index_root, device=resolve_device(), dense_enabled=args.dense,
        phrase_enabled=args.phrase_search or args.accuracy_mode == "robust",
    )

    if args.extractive:
        generator, model_name = ExtractiveGenerator(), "extractive-no-model"
    else:
        ollama = OllamaGenerator(
            model=args.model, num_predict=args.num_predict, num_ctx=args.num_ctx,
            keep_alive=0 if args.unload_model_between_requests else None,
            num_gpu=args.num_gpu_layers,
            prompt_profile=args.prompt_profile,
            seed=args.seed,
        )
        if not ollama.available():
            raise SystemExit(
                f"Ollama model {args.model!r} is not reachable. Start Ollama, or pass --extractive."
            )
        generator, model_name = ollama, ollama.model_name

    reranker = None
    if args.rerank:
        from aura_bio.retrieval import CrossEncoderReranker

        reranker = CrossEncoderReranker(device=args.rerank_device)

    critic = None
    if args.critic:
        from aura_bio.critique import critic_from_env

        critic = critic_from_env()
        if critic is None:
            raise SystemExit("--critic requested but no provider key is set (ZAI_API_KEY)")

    # basic_rag is retrieval only: no verification-driven revision, no critic.
    is_basic = args.system == "basic_rag"
    classifier = None
    if not args.rules_router:
        from aura_bio.routing.encoder_router import load_default_classifier

        classifier = load_default_classifier()
    print(f"router: {'learned (' + classifier.name + ')' if classifier else 'rules only'}",
          flush=True)

    pipeline = AuraBioPipeline(
        generator=generator,
        searcher=searcher,
        router=QueryRouter(classifier=classifier),
        verifier=BiologyVerifier(
            check_claims=not is_basic,
            check_terms=not is_basic,
            check_processes=not is_basic,
            check_numbers=not is_basic,
            check_hedging=not is_basic,
        ),
        reranker=None if is_basic else reranker,
        critic=None if is_basic else critic,
        model_name=model_name,
        compress_deep_evidence=not args.no_compress_evidence,
        revision_context=args.revision_context,
        accuracy_mode="standard" if is_basic else args.accuracy_mode,
        draft_candidates=args.draft_candidates,
    )

    if args.questions:
        from aura_bio.evaluation.schema import read_jsonl

        questions = list(read_jsonl(args.questions))
    else:
        questions = all_questions()
    wanted: list[str] = []
    if args.ids_file:
        # utf-8-sig, not utf-8: PowerShell 5.1's Set-Content -Encoding utf8
        # writes a BOM, which otherwise arrives glued to the first id.
        wanted += [line.strip() for line in args.ids_file.read_text(encoding="utf-8-sig").splitlines()]
    if args.ids:
        wanted += [part.strip() for part in args.ids.split(",")]
    if wanted:
        keep = {qid for qid in wanted if qid}
        # Preserve the caller's order so a smoke run reads in the order asked.
        order = {qid: index for index, qid in enumerate(wanted)}
        questions = sorted((q for q in questions if q.id in keep), key=lambda q: order[q.id])
        missing = keep - {q.id for q in questions}
        if missing:
            raise SystemExit(f"unknown question ids: {sorted(missing)}")
    if args.limit:
        questions = questions[: args.limit]
    done = _done_ids(results_path)
    todo = [q for q in questions if q.id not in done]
    print(
        f"system={args.system} model={model_name} dense={args.dense} rerank={args.rerank} "
        f"critic={bool(critic)} accuracy_mode={pipeline.accuracy_mode} drafts={args.draft_candidates} "
        f"| total={len(questions)} done={len(done)} remaining={len(todo)}",
        flush=True,
    )

    started = time.perf_counter()
    try:
        with results_path.open("a", encoding="utf-8") as handle:
            for index, question in enumerate(todo, 1):
                error = None
                call_started = time.perf_counter()
                try:
                    # basic_rag must not revise: cap the loop at a single draft.
                    answer = pipeline.answer(
                        question.question,
                        teaching_mode=args.teaching_mode,
                        use_critic=bool(critic) and not is_basic,
                    )
                    text = answer.text
                    trace = {
                        "decision": answer.decision,
                        "confidence": answer.confidence,
                        "evidence": len(answer.trace.evidence),
                        "revisions": len(answer.trace.revisions),
                        "strategy": answer.trace.retrieval.get("strategy"),
                        # What the router actually decided, and from which
                        # source. Omitting this is how a trained router that
                        # was never consulted stayed invisible: the model
                        # loaded, reported healthy, and end-to-end accuracy was
                        # byte-identical with and without it. It is also needed
                        # to attribute an answer's length and register, since
                        # learner level selects the prompt's guidance.
                        "route": {
                            dimension: {
                                "label": str(entry.get("label")),
                                "source": entry.get("source"),
                                "confidence": entry.get("confidence"),
                            }
                            for dimension, entry in answer.trace.route.items()
                            if isinstance(entry, dict)
                        },
                        "stage_ms": answer.trace.stage_ms,
                        "provenance": answer.trace.provenance,
                        "accuracy_mode": pipeline.accuracy_mode,
                        "selected_revision": answer.trace.selected_revision,
                        "final_verification": answer.trace.final_verification,
                        "queries": answer.trace.retrieval.get("queries", []),
                        "calculations": answer.trace.retrieval.get("calculations", []),
                        "calculation_rendered": answer.trace.retrieval.get("calculation_rendered", False),
                        "revision_context": pipeline.revision_context,
                        "candidate_records": answer.trace.revisions,
                        # Which checkers fired, so a regression can be
                        # attributed without re-deriving the evidence. Working
                        # out that NLI drove 18 of 50 revisions needed a full
                        # retrieval replay because this was not recorded.
                        "issues": [
                            {"checker": i["checker"], "kind": i["kind"],
                             "severity": i["severity"]}
                            for record in answer.trace.revisions
                            for i in record.get("verification", {}).get("issues", [])
                        ],
                    }
                except Exception as exc:
                    text, trace, error = "", {}, str(exc)
                latency_ms = (time.perf_counter() - call_started) * 1000
                score = score_answer(question, text)
                handle.write(
                    json.dumps(
                        {
                            "id": question.id,
                            "subdomain": question.subdomain,
                            "task_type": question.task_type,
                            "level": question.level,
                            "adversarial": question.adversarial,
                            "question": question.question,
                            "answer": text,
                            "latency_ms": round(latency_ms, 1),
                            "error": error,
                            "trace": trace,
                            "score": score.as_dict(),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                handle.flush()
                if index % 10 == 0 or index == len(todo):
                    elapsed = time.perf_counter() - started
                    rate = index / elapsed if elapsed else 0
                    print(
                        f"[{index}/{len(todo)}] {question.id} score={score.overall:.2f} "
                        f"{latency_ms:.0f}ms eta={(len(todo) - index) / rate / 60 if rate else 0:.1f}min",
                        flush=True,
                    )
    finally:
        searcher.close()

    _write_summary(args.system, model_name, results_path, summary_path)
    degraded = getattr(generator, "degraded_calls", 0)
    if degraded:
        # Not a failure, but these answers ran without full GPU offload, so
        # their latency cannot be compared against a run where none did.
        print(
            f"WARNING: {degraded} answer(s) succeeded only after dropping full GPU "
            f"offload. Their scores are valid; their latencies are not comparable.",
            flush=True,
        )
    print(f"done. summary -> {summary_path}", flush=True)
    return 0


def _write_summary(system: str, model: str, results_path: Path, summary_path: Path) -> None:
    """Aggregate, including the discriminative subset the baseline saturates."""

    baseline = results_path.parent / "baseline_aura-bio_v0.jsonl"
    saturated: set[str] = set()
    if baseline.is_file():
        for line in baseline.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row["score"]["overall"] >= 1.0 and not row.get("adversarial"):
                    saturated.add(row["id"])

    # One row per question, even though the file is append-only and a question
    # that failed on an earlier pass is retried on the next one. A later
    # successful row supersedes an earlier errored one; without this the
    # retried question is counted twice and its recovered score is averaged
    # against the 0.00 it is meant to replace.
    latest: dict[str, dict[str, Any]] = {}
    for line in results_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        previous = latest.get(row["id"])
        if previous is None or not row.get("error") or previous.get("error"):
            latest[row["id"]] = row

    scores: list[QuestionScore] = []
    latencies: list[float] = []
    errors = 0
    for row in latest.values():
        s = row["score"]
        scores.append(
            QuestionScore(
                question_id=row["id"], subdomain=row["subdomain"], task_type=row["task_type"],
                concept_recall=s["concept_recall"], avoided_forbidden=s["avoided_forbidden"],
                numeric_correct=s["numeric_correct"], order_correct=s["order_correct"],
                hallucinated=s["hallucinated"], overall=s["overall"],
            )
        )
        latencies.append(row.get("latency_ms", 0.0))
        if row.get("error"):
            errors += 1
    result = SystemResult(
        system=f"{system}:{model}", scores=scores, latencies_ms=latencies, errors=errors,
        saturated_ids=frozenset(saturated),
    )
    summary = result.aggregate()
    candidates = [record for row in latest.values()
                  for record in row.get("trace", {}).get("candidate_records", [])]
    summary["reliability"] = {
        "candidate_reviews": len(candidates),
        "trusted_critic_reviews": sum(bool(record.get("critique", {}).get("trusted"))
                                      for record in candidates if record.get("critique")),
        "untrusted_critic_reviews": sum(not record["critique"].get("trusted", False)
                                        for record in candidates if record.get("critique")),
        "degraded_answers": sum(row.get("trace", {}).get("decision") == "degraded"
                                for row in latest.values()),
        "uncited_answers": sum(row.get("trace", {}).get("provenance", {}).get("claim_citation_rate", 0) == 0
                               for row in latest.values()),
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
