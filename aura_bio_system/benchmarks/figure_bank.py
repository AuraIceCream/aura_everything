"""Frozen evaluator-only fixture validation. Never import in serving code."""
import hashlib
import json
from collections import Counter
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_figure_bank(bank_path: Path, manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if sha(bank_path) != manifest['bank_sha256']:
        raise ValueError('Frozen figure bank changed.')
    bank = [json.loads(line) for line in bank_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if len(bank) != 40 or len({q['id'] for q in bank}) != 40:
        raise ValueError('Expected 40 unique questions.')
    sources = manifest['sources']
    if len(sources) != 20 or len({s['figure_id'] for s in sources}) != 20:
        raise ValueError('Expected 20 unique figures.')
    root = manifest_path.parent.resolve()
    for source in sources:
        path = (root / source['path']).resolve()
        if not path.is_relative_to(root) or sha(path) != source['sha256']:
            raise ValueError('Frozen figure source changed.')
    groups = {}
    for q in bank:
        source = next(s for s in sources if s['figure_id'] == q['figure_id'])
        if q['split'] != source['split'] or q['split'] not in {'dev', 'holdout'}:
            raise ValueError('Figure-level split mismatch.')
        groups.setdefault(source['source_group'], set()).add(q['split'])
    if any(len(v) != 1 for v in groups.values()):
        raise ValueError('Source group leaks between splits.')
    splits = [(s['figure_id'], s['split'], s['source_group']) for s in sources]
    split_hash = hashlib.sha256(json.dumps(splits, separators=(',', ':')).encode()).hexdigest()
    if split_hash != manifest['split_sha256']:
        raise ValueError('Frozen split changed.')
    result = {'figures': len(sources), 'questions': len(bank), 'splits': dict(Counter(q['split'] for q in bank)),
              'categories': dict(Counter(q['category'] for q in bank)), 'manifest_sha256': sha(manifest_path)}
    if result['splits'] != {'dev': 24, 'holdout': 16} or result['categories'] != {'label': 16, 'relationship': 12, 'value': 6, 'absent': 6}:
        raise ValueError('Frozen bank balance changed.')
    return result
