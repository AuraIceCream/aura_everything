"""Frozen private-pack retrieval/answer harness; no gold keys reach the pipeline."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import time

from aura_bio.study.evaluation import evaluate_pack_run, load_bank, validate_resume
from aura_bio.study.storage import StudyStore
from aura_bio.study.searcher import StudySearcher


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_digest():
    root = Path(__file__).resolve().parents[2]
    files = sorted((root / 'aura_bio_system/src').rglob('*.py')) + sorted((root / 'corpus_pipeline/src').rglob('*.py'))
    files += [Path(__file__).resolve()]
    return hashlib.sha256(''.join(f'{p.relative_to(root).as_posix()}:{digest(p)}\n' for p in files).encode()).hexdigest()


def source_units(store, pack_id, bank):
    """Resolve stable evaluator references only; runtime gets no keys/mappings."""
    units, keys, valid = {}, {}, {}
    for doc in store.documents(pack_id):
        if not doc.active:
            continue
        if digest(store.original_path(pack_id, doc.document_id)) != doc.checksum:
            raise ValueError('Original bytes no longer match upload checksum.')
        for unit in store.units(pack_id, doc.document_id):
            units[unit.unit_id] = unit
            keys[unit.unit_id] = f'{doc.filename}::{unit.title}'
            valid[unit.unit_id] = [loc.as_dict() for loc in unit.locators]
    needed = {key for q in bank for key in q['expected_units']}
    if not needed <= set(keys.values()):
        raise ValueError('Upload both exact authored fixture files before running this bank.')
    manifest = Path(__file__).with_name('study_pack_sources.json')
    expected = {source['filename']: source['sha256'] for source in json.loads(manifest.read_text())['sources']}
    docs = store.documents(pack_id)
    if any(doc.active and doc.filename in expected and doc.checksum != expected[doc.filename] for doc in docs):
        raise ValueError('Frozen fixture bytes changed; use a separate bank/source manifest.')
    return keys, valid


def record_hits(hits, unit_keys, valid_locators):
    actual, correctness = [], []
    for hit in hits:
        value = hit.as_dict() if hasattr(hit, 'as_dict') else hit
        cited = value.get('locators', [])
        for uid in value.get('unit_ids', []):
            if uid in unit_keys:
                actual.append(unit_keys[uid])
                correctness.append(bool(valid_locators[uid]) and all(loc in cited for loc in valid_locators[uid]))
    return actual, correctness


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack-id', required=True)
    parser.add_argument('--model', default='llama3.2:1b')
    parser.add_argument('--bank', type=Path, default=Path(__file__).with_name('study_pack_bank.jsonl'))
    parser.add_argument('--retrieval-only', action='store_true')
    parser.add_argument('--sparse-only', action='store_true', help='Explicit BM25-only retrieval diagnostic; requires --retrieval-only.')
    parser.add_argument('--critic', action='store_true', help='Explicit permission to send private excerpts to the configured external critic.')
    parser.add_argument('--tag', required=True)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args(argv)
    if args.sparse_only and not args.retrieval_only:
        parser.error('--sparse-only requires --retrieval-only.')
    if not __import__('re').fullmatch(r'[A-Za-z0-9_-]{1,100}', args.tag):
        parser.error('Tag must be a short filename-safe label.')
    bank = load_bank(args.bank)
    store = StudyStore(Path(os.environ.get('AURA_STUDY_ROOT', '.local/study-packs')))
    with ExitStack() as stack:
        stack.enter_context(store.lease(args.pack_id))
        unit_keys, valid_locators = source_units(store, args.pack_id, bank)
        pack = store.get_pack(args.pack_id)
        generation = store.root / args.pack_id / 'generations' / f'{pack.generation:08d}'
        source_hash = hashlib.sha256((digest(generation / 'search.sqlite3') + digest(generation / 'manifest.json')).encode()).hexdigest()
        pipeline = None
        reranker = None
        if args.retrieval_only:
            from aura_bio.study.jobs import cached_encoder
            from aura_bio.study.reranking import configured_reranker
            encoder = cached_encoder() if pack.state == 'hybrid-ready' and not args.sparse_only else None
            searcher = stack.enter_context(StudySearcher(store, args.pack_id, dense_encoder=encoder))
            # Unlike an interactive fallback, a configured benchmark stage must
            # fail visibly rather than silently measure a different pipeline.
            reranker = configured_reranker() if not args.sparse_only else None
        else:
            os.environ['AURA_OLLAMA_MODEL'] = args.model
            os.environ['AURA_STUDY_SEED'] = str(args.seed)
            from aura_bio.study.runtime import build_pack_pipeline
            pipeline = build_pack_pipeline(store, args.pack_id, use_critic=args.critic)
            stack.callback(pipeline.searcher.close); stack.callback(pipeline.store.close)
            if pipeline.model_name != args.model:
                raise ValueError('Requested model unavailable; benchmark will not silently substitute extractive output.')
            searcher = pipeline.searcher
            reranker = pipeline.reranker
        config = {'pack_id': args.pack_id, 'generation': pack.generation, 'model': args.model if pipeline else None,
            'retrieval_only': args.retrieval_only, 'retrieval_mode': searcher.mode, 'top_k': 10,
            'context_level': 3, 'bank_sha256': digest(args.bank), 'source_sha256': source_hash,
            'code_sha256': code_digest(), 'seed': args.seed, 'domain': pack.domain,
            'critic_requested': args.critic, 'critic_enabled': bool(pipeline and pipeline.critic),
            'embedding_model': getattr(searcher.encoder, 'model_name', None),
            'reranker_enabled': bool(reranker), 'reranker_model': getattr(reranker, 'model_name', None),
            'reranker_min_score': getattr(reranker, 'min_score', None),
            'accuracy_mode': pipeline.accuracy_mode if pipeline else None,
            'draft_candidates': pipeline.draft_candidates if pipeline else None,
            'num_predict': getattr(pipeline.generator, 'num_predict', None) if pipeline else None,
            'nli_policy': os.environ.get('AURA_NLI', 'auto'), 'prompt': 'pack-only-v1'}
        output_root = store.root / args.pack_id / 'traces' / 'evaluation'
        output_root.mkdir(parents=True, exist_ok=True)
        output = output_root / f'{args.tag}.jsonl'
        metadata = output_root / f'{args.tag}.metadata.json'
        rows = load_bank_rows(output)
        if metadata.exists():
            validate_resume(json.loads(metadata.read_text()), config, rows)
        elif rows:
            raise ValueError('Output has no metadata; refuse unverifiable resume.')
        else:
            metadata.write_text(json.dumps({'config': config, 'created_at': time.time()}, indent=2), encoding='utf-8')
        completed = {row['id'] for row in rows}
        for q in bank:
            if q['id'] in completed:
                continue
            started = time.perf_counter()
            try:
                if pipeline:
                    # This is the complete scoped orchestration; only the question crosses this boundary.
                    answer = pipeline.answer(q['question'], context_level=3, use_critic=args.critic)
                    hits, decision = answer.trace.evidence, answer.decision
                    detail = {'answer': answer.text, 'trace_id': answer.trace.trace_id,
                              'verification': answer.trace.final_verification}
                else:
                    hits, decision = searcher.search(q['question'], top_k=100 if reranker else 10, candidate_k=100), None
                    detail = {}
                    if reranker:
                        hits, report = reranker.rerank(q['question'], hits, 10)
                        detail['rerank'] = report.as_dict()
                actual, correct = record_hits(hits, unit_keys, valid_locators)
                row = {'id': q['id'], 'decision': decision, 'retrieved_units': actual,
                       'retrieved_locators_valid': correct, 'manual_review': None, **detail}
            except Exception as exc:
                row = {'id': q['id'], 'error': type(exc).__name__}
            row['latency_ms'] = round((time.perf_counter() - started) * 1000, 1)
            with output.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
                handle.flush(); os.fsync(handle.fileno())
            rows.append(row)
            print(f"[{len(rows)}/{len(bank)}] {q['id']} {row['latency_ms']}ms", flush=True)
        summary = evaluate_pack_run(rows, bank)
        (output_root / f'{args.tag}.summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        print(json.dumps({'output': str(output), **summary}), flush=True)


def load_bank_rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


if __name__ == '__main__':
    main()
