"""Rescoring is an append-only CPU operation, not another inference run."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


BENCHMARKS = Path(__file__).resolve().parents[1] / 'benchmarks'
spec = importlib.util.spec_from_file_location(
    'rescore_figure_labels', BENCHMARKS / 'rescore_figure_labels.py')
rescore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rescore)


class FigureLabelRescoreTests(unittest.TestCase):
    def test_writes_new_summary_preserving_originals_and_refuses_overwrite(self):
        bank = [json.loads(line) for line in
                (BENCHMARKS / 'figure_bank.jsonl').read_text(encoding='utf-8').splitlines()
                if line.strip()]
        question = next(q for q in bank if q['split'] == 'dev')
        with tempfile.TemporaryDirectory() as folder:
            records = Path(folder) / 'records.jsonl'
            original = json.dumps({'id': question['id'], 'state': 'completed',
                                   'labels': ['Extra visible title']}).encode('utf-8') + b'\n'
            records.write_bytes(original)
            old_summary = Path(folder) / 'summary.json'
            old_summary.write_bytes(b'{"historical": true}\n')
            with redirect_stdout(io.StringIO()):
                rescore.main([str(records), '--split', 'dev'])
            summary = json.loads((Path(folder) / 'summary.label_accounting_v2.json').read_text())
            self.assertFalse(summary['inference_rerun'])
            self.assertEqual(summary['source_records_sha256'], hashlib.sha256(original).hexdigest())
            self.assertIsNone(summary['hallucinated_label_rate'])
            self.assertEqual(records.read_bytes(), original)
            self.assertEqual(old_summary.read_bytes(), b'{"historical": true}\n')
            with self.assertRaises(FileExistsError):
                rescore.main([str(records), '--split', 'dev'])

    def test_wrong_split_is_rejected_before_writing_summary(self):
        bank = [json.loads(line) for line in
                (BENCHMARKS / 'figure_bank.jsonl').read_text(encoding='utf-8').splitlines()
                if line.strip()]
        question = next(q for q in bank if q['split'] == 'dev')
        with tempfile.TemporaryDirectory() as folder:
            records = Path(folder) / 'records.jsonl'
            records.write_text(json.dumps({'id': question['id'], 'state': 'completed',
                                          'labels': []}) + '\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                rescore.main([str(records), '--split', 'holdout'])
            self.assertFalse((Path(folder) / 'summary.label_accounting_v2.json').exists())


if __name__ == '__main__':
    unittest.main()
