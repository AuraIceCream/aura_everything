"""Prepare exact frozen fixtures and optionally run both study benchmarks.

Use a real, guarded script: Windows extraction workers cannot spawn from stdin.
This creates a new benchmark-owned pack; existing user packs are never changed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]


def prepare_pack(root):
    from aura_bio.study.storage import StudyStore
    from aura_bio.study.jobs import StudyJobs

    manifest = json.loads((HERE / 'study_pack_sources.json').read_text(encoding='utf-8'))
    fixtures = []
    for source in manifest['sources']:
        path = HERE / 'study_fixtures' / source['filename']
        if hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
            raise ValueError(f'Frozen fixture checksum mismatch: {path.name}')
        fixtures.append(path)
    store = StudyStore(root)
    pack = store.create_pack('Frozen document benchmark', domain='general')
    print(f'Benchmark pack: {pack.pack_id}', flush=True)
    for path in fixtures:
        with path.open('rb') as stream:
            store.add_document(pack.pack_id, path.name, stream)
    print('Extracting and building the hybrid index (CPU)...', flush=True)
    jobs = StudyJobs(store)
    while jobs.run_once():
        pass
    ready = store.get_pack(pack.pack_id)
    if ready.state != 'hybrid-ready':
        failures = [(j.state, j.error) for j in store.jobs(pack.pack_id)]
        raise RuntimeError(f'Expected hybrid-ready, got {ready.state}; jobs={failures!r}. Benchmarks not started.')
    print('Pack is hybrid-ready.', flush=True)
    return pack.pack_id


def run_benchmarks(root, pack_id, model, tag_prefix):
    runner = HERE / 'run_study_pack.py'
    common = [sys.executable, '-u', str(runner), '--pack-id', pack_id]
    retrieval_tag = tag_prefix + '_retrieval'
    subprocess.run(common + ['--retrieval-only', '--tag', retrieval_tag],
                   cwd=PROJECT, check=True)
    # The harness preserves per-question errors but may still exit zero.
    # Do not launch the longer model run after failed/incomplete retrieval.
    results = root / pack_id / 'traces' / 'evaluation'
    rows = [json.loads(line) for line in
            (results / f'{retrieval_tag}.jsonl').read_text(encoding='utf-8').splitlines()
            if line.strip()]
    expected = {json.loads(line)['id'] for line in
                (HERE / 'study_pack_bank.jsonl').read_text(encoding='utf-8').splitlines()
                if line.strip()}
    if len(rows) != len(expected) or {r['id'] for r in rows} != expected or any(r.get('error') for r in rows):
        raise RuntimeError('Retrieval has errors or incomplete records; model benchmark not started.')
    metadata = json.loads((results / f'{retrieval_tag}.metadata.json').read_text(encoding='utf-8'))
    if not metadata['config']['reranker_enabled']:
        raise RuntimeError('Expected reranking was not enabled; model benchmark not started.')
    subprocess.run(common + ['--model', model, '--tag', tag_prefix + '_qwen'],
                   cwd=PROJECT, check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=PROJECT / '.local/study-benchmark-20261011')
    parser.add_argument('--run', action='store_true', help='Explicitly start retrieval and then local model inference.')
    parser.add_argument('--model', default='qwen3.5:4b')
    parser.add_argument('--tag-prefix', default='pack_20261011')
    args = parser.parse_args(argv)
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,85}', args.tag_prefix):
        parser.error('Use a short filename-safe tag prefix.')
    root = args.root.resolve()
    os.environ.update(AURA_STUDY_ROOT=str(root), AURA_STUDY_INDEX_MODE='hybrid',
                      AURA_STUDY_RERANK='1', AURA_GENERATOR='ollama',
                      AURA_OLLAMA_MODEL=args.model, AURA_ACCURACY_MODE='robust',
                      AURA_DRAFT_CANDIDATES='2', AURA_CRITIC='off')
    os.environ.setdefault('USE_TF', '0')
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
    for path in (PROJECT / 'aura_bio_system/src', PROJECT / 'corpus_pipeline/src'):
        sys.path.insert(0, str(path))
    pack_id = prepare_pack(root)
    if args.run:
        run_benchmarks(root, pack_id, args.model, args.tag_prefix)
    return 0


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
