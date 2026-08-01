"""Run the biology benchmark on the raw local model — no pipeline (SRS 25 config 1).

This is the ``baseline`` system: each question goes straight to the persona model
(``aura-bio:v0``) with no retrieval, no reranking, no verification, no critique.
Generation runs fully on the device GPU through Ollama.

The run is resumable: every answer is appended to the results JSONL as it is
produced, and a restart skips questions already present. It writes a summary at
the end. Launch it detached and let it run; it does not need supervision.

    python aura_bio_system/benchmarks/run_baseline.py \
        --model aura-bio:v0 \
        --out aura_bio_system/benchmarks/results

Options mirror the defaults, so no arguments are needed for the standard run.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

from aura_bio.env import load_env
from aura_bio.evaluation import all_questions, score_answer
from aura_bio.evaluation.harness import SystemResult
from aura_bio.evaluation.scorer import QuestionScore

HOST = "http://127.0.0.1:11434"


def generate(model: str, question: str, num_predict: int, timeout: int) -> tuple[str, float, str | None]:
    """One raw model call, forced fully onto the GPU. No context, no pipeline."""

    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": question}],
            "stream": False,
            "think": False,
            # num_gpu 99 asks Ollama to offload every layer it can; the 4B model
            # fits the GTX 1650 at 100% GPU.
            "options": {"temperature": 0.2, "num_predict": num_predict, "num_gpu": 99},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{HOST}/api/chat", data=payload, headers={"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return "", (time.perf_counter() - started) * 1000, str(exc)
    return body.get("message", {}).get("content", "").strip(), (time.perf_counter() - started) * 1000, None


def _done_ids(results_path: Path) -> set[str]:
    if not results_path.is_file():
        return set()
    done: set[str] = set()
    for line in results_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                done.add(json.loads(line)["id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return done


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(description="Baseline (raw model) benchmark run")
    parser.add_argument("--model", default="aura-bio:v0")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "results")
    parser.add_argument("--num-predict", type=int, default=800)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--limit", type=int, help="cap the number of questions (for a quick check)")
    parser.add_argument("--ids-file", type=Path,
                        help="file of question ids, one per line; the way to run the "
                             "identical subset across systems")
    parser.add_argument("--tag", help="override the output filename stem")
    parser.add_argument("--questions", type=Path,
                        help="a benchmark JSONL to use instead of the built-in 441")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.tag or f"baseline_{args.model.replace(':', '_')}"
    results_path = args.out / f"{stem}.jsonl"
    summary_path = args.out / f"{stem}.summary.json"

    if args.questions:
        from aura_bio.evaluation.schema import read_jsonl

        questions = list(read_jsonl(args.questions))
    else:
        questions = all_questions()
    if args.ids_file:
        keep = {
            line.strip()
            # utf-8-sig: PowerShell 5.1 writes a BOM that would otherwise arrive
            # glued to the first id.
            for line in args.ids_file.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        }
        questions = [q for q in questions if q.id in keep]
        missing = keep - {q.id for q in questions}
        if missing:
            raise SystemExit(f"unknown question ids: {sorted(missing)}")
    if args.limit:
        questions = questions[: args.limit]
    done = _done_ids(results_path)
    todo = [q for q in questions if q.id not in done]
    print(f"model={args.model} total={len(questions)} done={len(done)} remaining={len(todo)}", flush=True)

    started = time.perf_counter()
    with results_path.open("a", encoding="utf-8") as handle:
        for index, question in enumerate(todo, 1):
            answer, latency_ms, error = generate(
                args.model, question.question, args.num_predict, args.timeout
            )
            score = score_answer(question, answer)
            handle.write(
                json.dumps(
                    {
                        "id": question.id,
                        "subdomain": question.subdomain,
                        "task_type": question.task_type,
                        "level": question.level,
                        "adversarial": question.adversarial,
                        "question": question.question,
                        "answer": answer,
                        "latency_ms": round(latency_ms, 1),
                        "error": error,
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
                eta = (len(todo) - index) / rate if rate else 0
                print(
                    f"[{index}/{len(todo)}] {question.id} {question.subdomain} "
                    f"score={score.overall:.2f} {latency_ms:.0f}ms  eta={eta/60:.1f}min",
                    flush=True,
                )

    _write_summary(args.model, results_path, summary_path)
    print(f"done. summary -> {summary_path}", flush=True)
    return 0


def _write_summary(model: str, results_path: Path, summary_path: Path) -> None:
    """Aggregate the JSONL into the SystemResult summary the harness produces."""

    scores: list[QuestionScore] = []
    latencies: list[float] = []
    errors = 0
    for line in results_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        s = row["score"]
        scores.append(
            QuestionScore(
                question_id=row["id"],
                subdomain=row["subdomain"],
                task_type=row["task_type"],
                concept_recall=s["concept_recall"],
                avoided_forbidden=s["avoided_forbidden"],
                numeric_correct=s["numeric_correct"],
                order_correct=s["order_correct"],
                hallucinated=s["hallucinated"],
                overall=s["overall"],
            )
        )
        latencies.append(row.get("latency_ms", 0.0))
        if row.get("error"):
            errors += 1
    result = SystemResult(system=f"baseline:{model}", scores=scores, latencies_ms=latencies, errors=errors)
    summary_path.write_text(json.dumps(result.aggregate(), indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
