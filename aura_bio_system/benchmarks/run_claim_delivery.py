"""Frozen before/after production-Ask evaluation. Gold keys never reach runtime."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_checkpoint(path, config):
    if path.exists() and json.loads(path.read_text(encoding='utf-8'))['config'] != config:
        raise ValueError('Frozen manifest, source, model, configuration or code changed; use a new output directory.')


def completed_ids(rows):
    return {row['id'] for row in rows if 'error' not in row and 'decision' in row}


def summarize(rows, bank):
    latest = {row['id']: row for row in rows}
    completed = {key: row for key, row in latest.items() if key in completed_ids([row])}
    positive = [completed[q['id']] for q in bank if q['answerable'] and q['id'] in completed]
    negative = [completed[q['id']] for q in bank if not q['answerable'] and q['id'] in completed]
    refused = lambda row: row['decision'] == 'insufficient_evidence'
    return {'total': len(bank), 'completed': len(completed), 'missing': len(bank) - len(completed),
            'errors': sum('error' in row for row in latest.values()),
            'answerable_completed': len(positive), 'unsupported_controls_completed': len(negative),
            'answerable_refusal_rate': sum(map(refused, positive)) / len(positive) if positive else None,
            'unsupported_control_abstention': sum(map(refused, negative)) / len(negative) if negative else None,
            'mean_latency_ms': sum(row['latency_ms'] for row in completed.values()) / len(completed) if completed else None,
            'semantic_accuracy': None, 'manual_review_required': True,
            'note': 'Expected-concept matches are diagnostics, not semantic accuracy. Never extrapolate incomplete runs.'}


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.exists() else []


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def preflight_after_release(backend, config):
    """Allow Ollama a short window to release our prior answer's VRAM."""
    from aura_bio.study.schema import StudyError
    from aura_bio.study.visual.ollama import gpu_free_mb
    for attempt in range(6):
        try:
            return backend.preflight(config)
        except StudyError as exc:
            if exc.code != 'busy_gpu' or 'Another model is loaded' in str(exc) or attempt == 5:
                raise
            loaded = backend._request('get', '/api/ps', timeout=5).get('models', [])
            if len(loaded) == 1 and (loaded[0].get('name') == config.model or loaded[0].get('model') == config.model):
                _, _, utilization = gpu_free_mb()
                if utilization <= 15:
                    backend._request('post', '/api/generate', json={'model': config.model, 'keep_alive': 0}, timeout=5)
            time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack-root', required=True, type=Path)
    parser.add_argument('--pack-id', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--phase', required=True, choices=('before', 'after'))
    parser.add_argument('--bank', type=Path, default=Path(__file__).with_name('claim_delivery_bank.jsonl'))
    parser.add_argument('--model', default='qwen3.5:4b')
    parser.add_argument('--host', default='http://127.0.0.1:11435')
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    for folder in ('.cache/study-deps', '.cache/verification-deps', 'aura_bio_system/src', 'corpus_pipeline/src'):
        sys.path.insert(0, str(project / folder))
    os.environ.update(AURA_STUDY_ROOT=str(args.pack_root.resolve()), AURA_OLLAMA_HOST=args.host,
                      AURA_OLLAMA_MODEL=args.model, AURA_GENERATOR='ollama', AURA_STUDY_INDEX_MODE='hybrid',
                      AURA_STUDY_RERANK='1', AURA_ACCURACY_MODE='robust', AURA_DRAFT_CANDIDATES='2',
                      AURA_STUDY_SEED='42', AURA_CRITIC='off', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      USE_TF='0', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    from aura_bio.api.study_packs import study_services
    from aura_bio.api.study_visual import resolve_question, VisualQuestionRequest
    from aura_bio.api.app import _execute, RunRequestModel
    from aura_bio.study.visual.ollama import OllamaVisionBackend
    from aura_bio.study.visual.schema import VisualJobConfig
    from aura_bio.study.schema import StudyError
    store, _ = study_services()
    bank = read_rows(args.bank)
    ids = [q['id'] for q in bank]
    if not bank or len(ids) != len(set(ids)):
        raise ValueError('Bank must have unique frozen question IDs.')
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = args.output / f'{args.phase}.metadata.json'
    output = args.output / f'{args.phase}.records.jsonl'
    with store.lease(args.pack_id):
        pack = store.get_pack(args.pack_id)
        if pack.state != 'hybrid-ready':
            raise ValueError('The frozen comparison requires a hybrid-ready pack, not sparse fallback.')
        documents = [{'id': d.document_id, 'filename': d.filename, 'sha256': sha(store.original_path(args.pack_id, d.document_id))}
                     for d in store.documents(args.pack_id) if d.active]
        config = {'bank_sha256': sha(args.bank), 'pack_id': args.pack_id,
                  'pack_root': str(args.pack_root.resolve()), 'sources': documents,
                  'model': args.model, 'host': args.host, 'seed': 42, 'drafts': 2, 'critic': False, 'think': False,
                  'context_depth': 'standard', 'generation': pack.generation,
                  'code_sha256': hashlib.sha256(''.join(f'{p.relative_to(project).as_posix()}:{sha(p)}\n'
                      for folder in ('aura_bio_system/src', 'corpus_pipeline/src')
                      for p in sorted((project / folder).rglob('*.py'))).encode()).hexdigest()}
        validate_checkpoint(metadata, config)
        if args.phase == 'after':
            previous_path = args.output / 'before.metadata.json'
            if not previous_path.exists():
                raise ValueError('Fresh before baseline is required before the after comparison.')
            previous = json.loads(previous_path.read_text(encoding='utf-8'))['config']
            for key in ('bank_sha256', 'sources', 'model', 'host', 'seed', 'drafts', 'critic', 'think', 'context_depth'):
                if previous[key] != config[key]:
                    raise ValueError(f'Before/after comparison changed {key}.')
            if completed_ids(read_rows(args.output / 'before.records.jsonl')) != set(ids):
                raise ValueError('Before baseline is incomplete; do not extrapolate it.')
        if not metadata.exists():
            write_json(metadata, {'config': config, 'created_at': time.time()})
        rows = read_rows(output)
        done = completed_ids(rows)
        if len(done) < len(bank):
            # Warm CPU-only search before the GPU check, not between two
            # checks that may be separated by slow local weight loading.
            print('Preparing cached CPU embedding and reranking; no model inference started.', flush=True)
            from aura_bio.study.jobs import cached_encoder
            from aura_bio.study.reranking import configured_reranker
            cached_encoder()
            if configured_reranker() is None:
                raise ValueError('The frozen comparison requires the configured CPU reranker.')
        for q in bank:
            if q['id'] in done:
                continue
            # Never start inference on an occupied GPU or unload another model.
            # A failed preflight produces no fake completed question/accuracy.
            try:
                preflight_after_release(OllamaVisionBackend(url=args.host), VisualJobConfig(model=args.model))
            except StudyError as exc:
                write_json(args.output / f'{args.phase}.blocked.json',
                           {'code': exc.code, 'message': str(exc), 'next_id': q['id'], 'completed': len(done)})
                write_json(args.output / f'{args.phase}.summary.json', summarize(rows, bank))
                print(json.dumps({'state': 'blocked', 'code': exc.code, 'message': str(exc),
                                  'completed': len(done), 'total': len(bank)}), flush=True)
                return 3
            figures = []
            if q['figure']:
                figures = [f['figure_id'] for f in resolve_question(args.pack_id, VisualQuestionRequest(question=q['question']))['figures']]
            request = RunRequestModel(query=q['question'], evidence_scope='pack_only', pack_id=args.pack_id, figure_ids=figures)
            started = time.monotonic()
            try:
                with store.inference(args.pack_id, 'answer', wait_for_visual=True):
                    result = _execute(request)
            except StudyError as exc:
                write_json(args.output / f'{args.phase}.blocked.json',
                           {'code': exc.code, 'message': str(exc), 'next_id': q['id'], 'completed': len(done)})
                write_json(args.output / f'{args.phase}.summary.json', summarize(rows, bank))
                print(json.dumps({'state': 'blocked', 'code': exc.code, 'message': str(exc),
                                  'completed': len(done), 'total': len(bank)}), flush=True)
                return 3
            answer = result['answer_payload']['markdown']
            row = {'id': q['id'], 'decision': result['decision'], 'answer_payload': result['answer_payload'],
                   'events': result['events'], 'latency_ms': round((time.monotonic() - started) * 1000, 1),
                   'expected_concept_matches': [term for term in q['expected_concepts'] if term.casefold() in answer.casefold()],
                   'manual_review': None}
            with output.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
                handle.flush()
                os.fsync(handle.fileno())
            rows.append(row)
            done.add(q['id'])
            write_json(args.output / f'{args.phase}.summary.json', summarize(rows, bank))
            print(f"[{len(done)}/{len(bank)}] {q['id']} {result['decision']} {row['latency_ms']/1000:.1f}s", flush=True)
        print(json.dumps(summarize(rows, bank)), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
