"""CPU-only label-accounting correction; never changes saved model outputs.

Example: python aura_bio_system/benchmarks/rescore_figure_labels.py PATH/records.jsonl --split dev
No model, image upload, embedding or provider call is made.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / 'src'))

from figure_bank import validate_figure_bank
from aura_bio.study.visual.evaluation import evaluate_figure_run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('records', type=Path)
    parser.add_argument('--split', choices=['dev', 'holdout'], required=True)
    parser.add_argument('--out', type=Path, help='New summary file; existing files are never overwritten.')
    args = parser.parse_args(argv)
    checked = validate_figure_bank(ROOT / 'figure_bank.jsonl', ROOT / 'figure_sources.json')
    manifest = json.loads((ROOT / 'figure_sources.json').read_text(encoding='utf-8'))
    sources = {source['figure_id']: source for source in manifest['sources']}
    bank = []
    for line in (ROOT / 'figure_bank.jsonl').read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        question = json.loads(line)
        if question['split'] == args.split:
            bank.append({**question,
                         'visible_labels': sources[question['figure_id']]['visible_labels']})
    raw = args.records.read_bytes()
    records = [json.loads(line) for line in raw.decode('utf-8-sig').splitlines() if line.strip()]
    metadata = args.records.with_name('manifest.json')
    if metadata.exists():
        previous = json.loads(metadata.read_text(encoding='utf-8'))
        expected = {'manifest_hash': checked['manifest_sha256'],
                    'bank_hash': manifest['bank_sha256'],
                    'split_hash': manifest['split_sha256'], 'split': args.split}
        if any(previous.get(key) != value for key, value in expected.items()):
            raise ValueError('Run manifest does not match the frozen bank and requested split.')
    summary = evaluate_figure_run(records, bank)
    summary.update({
        'source_records': str(args.records.resolve()),
        'source_records_sha256': hashlib.sha256(raw).hexdigest(),
        'scorer_sha256': hashlib.sha256(
            (ROOT.parent / 'src/aura_bio/study/visual/evaluation.py').read_bytes()).hexdigest(),
        'figure_manifest_sha256': checked['manifest_sha256'],
        'figure_bank_sha256': manifest['bank_sha256'],
        'run_manifest_sha256': hashlib.sha256(metadata.read_bytes()).hexdigest() if metadata.exists() else None,
        'inference_rerun': False,
    })
    output = args.out or args.records.with_name('summary.label_accounting_v2.json')
    with output.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'output': str(output), **summary}, ensure_ascii=False))


if __name__ == '__main__':
    main()
