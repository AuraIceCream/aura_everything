import hashlib
import json
from pathlib import Path
import unittest

from aura_bio.study.evaluation import evaluate_pack_run, load_bank, validate_resume

ROOT = Path(__file__).resolve().parents[1] / 'benchmarks'


class StudyEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.bank = load_bank(ROOT / 'study_pack_bank.jsonl')

    def test_frozen_bank_counts_and_complete_locators(self):
        self.assertEqual(len(self.bank), 30)
        self.assertEqual(len({q['id'] for q in self.bank}), 30)
        self.assertEqual(sum(q['answerable'] for q in self.bank), 20)
        self.assertEqual(sum(not q['answerable'] for q in self.bank), 10)
        self.assertGreaterEqual(sum(q['multi_unit'] for q in self.bank), 8)
        manifest = json.loads((ROOT / 'study_pack_sources.json').read_text())
        self.assertEqual(hashlib.sha256((ROOT / 'study_pack_bank.jsonl').read_bytes()).hexdigest(), manifest['bank_sha256'])
        for q in self.bank:
            self.assertEqual(bool(q['expected_units']), q['answerable'])
            for key in q['expected_units']:
                filename, heading = key.split('::')
                source = ROOT / 'study_fixtures' / filename
                self.assertIn('# ' + heading, source.read_text(encoding='utf-8'))

    def test_retrieval_coverage_is_not_answer_correctness(self):
        q = self.bank[0]; expected = q['expected_units']
        record = {'id': q['id'], 'retrieved_units': expected[:1], 'retrieved_locators_valid': [True],
                  'decision': 'degraded', 'manual_review': None}
        metrics = evaluate_pack_run([record], [q])
        self.assertEqual(metrics['retrieval_recall_at_k'], 1 / len(expected))
        self.assertEqual(metrics['all_unit_coverage'], float(len(expected) == 1))
        self.assertIsNone(metrics['citation_correctness'])
        self.assertIsNone(metrics['reviewed_grounded_answer_rate'])
        self.assertIsNone(metrics['absent_abstention_rate'])

    def test_wrong_locations_do_not_count_as_support(self):
        q = self.bank[0]
        metrics = evaluate_pack_run([{'id': q['id'], 'retrieved_units': q['expected_units'],
            'retrieved_locators_valid': [False] * len(q['expected_units'])}], [q])
        self.assertEqual(metrics['retrieval_recall_at_k'], 0)
        self.assertEqual(metrics['locator_accuracy'], 0)

    def test_resume_rejects_changed_model_source_code_bank_and_duplicate_ids(self):
        config = {'model': 'm', 'code_sha256': 'a', 'bank_sha256': 'b', 'source_sha256': 'c'}
        validate_resume({'config': config}, config, [])
        for key in config:
            with self.assertRaises(ValueError):
                validate_resume({'config': config}, {**config, key: 'changed'}, [])
        with self.assertRaises(ValueError):
            validate_resume({'config': config}, config, [{'id': 'a'}, {'id': 'a'}])

    def test_zero_denominator_and_unreviewed_are_null(self):
        metrics = evaluate_pack_run([], self.bank)
        self.assertIsNone(metrics['retrieval_recall_at_k'])
        self.assertIsNone(metrics['locator_accuracy'])
        self.assertIsNone(metrics['citation_correctness'])

    def test_retrieval_only_harness_is_resumable_and_keeps_results_private(self):
        import contextlib
        import importlib.util
        import io
        import os
        import tempfile
        from unittest.mock import patch
        from aura_bio.study.storage import StudyStore
        from aura_bio.study.jobs import StudyJobs
        spec = importlib.util.spec_from_file_location('study_benchmark', ROOT / 'run_study_pack.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'AURA_STUDY_ROOT': tmp, 'AURA_STUDY_INDEX_MODE': 'sparse', 'AURA_STUDY_RERANK': '0'}):
            store = StudyStore(Path(tmp)); pack = store.create_pack('Frozen fixtures')
            for source in (ROOT / 'study_fixtures').glob('*.md'):
                store.add_document(pack.pack_id, source.name, io.BytesIO(source.read_bytes()))
            jobs = StudyJobs(store)
            while jobs.run_once():
                pass
            argv = ['--pack-id', pack.pack_id, '--retrieval-only', '--tag', 'fixture-test']
            with contextlib.redirect_stdout(io.StringIO()):
                module.main(argv); module.main(argv)
            output = Path(tmp) / pack.pack_id / 'traces/evaluation/fixture-test.jsonl'
            rows = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual(len(rows), 30)
            self.assertTrue(all('expected_answer' not in row and 'expected_units' not in row for row in rows))
            summary = json.loads(output.with_suffix('.summary.json').read_text())
            self.assertIsNone(summary['reviewed_grounded_answer_rate'])
            self.assertIsNone(summary['absent_abstention_rate'])
            # The real FAISS/SQLite path must be used for a hybrid-ready pack;
            # only expensive model inference is substituted in this test.
            from test_study_retrieval import FakeEncoder
            from aura_bio.study.indexing import StudyIndexer
            from aura_bio.study.reranking import StudyReranker
            class FixtureScorer:
                def predict(self, pairs):
                    return [0.9] * len(pairs)
            encoder = FakeEncoder()
            StudyIndexer(store).build(pack.pack_id, dense_encoder=encoder)
            hybrid_argv = ['--pack-id', pack.pack_id, '--retrieval-only', '--tag', 'fixture-hybrid']
            with patch('aura_bio.study.jobs.cached_encoder', return_value=encoder), \
                    patch('aura_bio.study.reranking.configured_reranker', return_value=StudyReranker(scorer=FixtureScorer())), \
                    contextlib.redirect_stdout(io.StringIO()):
                module.main(hybrid_argv)
            hybrid_meta = json.loads((output.parent / 'fixture-hybrid.metadata.json').read_text())['config']
            self.assertEqual(hybrid_meta['retrieval_mode'], 'hybrid')
            self.assertEqual(hybrid_meta['embedding_model'], 'fake-v1')
            self.assertTrue(hybrid_meta['reranker_enabled'])
            hybrid_rows = [json.loads(line) for line in (output.parent / 'fixture-hybrid.jsonl').read_text().splitlines()]
            self.assertTrue(all(row['rerank']['candidates'] >= row['rerank']['selected'] for row in hybrid_rows))
