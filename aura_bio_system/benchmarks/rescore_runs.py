"""Rescore saved benchmark answers without any model, retrieval or critic calls."""

import argparse
import json
from pathlib import Path

from aura_bio.evaluation import all_questions
from aura_bio.evaluation.rescore import rescore_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--suffix", default="rescored_20261004")
    args = parser.parse_args()
    questions = {q.id: q for q in all_questions()}
    for path in args.runs:
        out, summary = rescore_file(path, questions, args.suffix)
        print(json.dumps({"output": str(out), **summary}), flush=True)


if __name__ == "__main__":
    main()
