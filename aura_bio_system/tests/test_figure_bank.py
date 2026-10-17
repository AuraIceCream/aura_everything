import json
import shutil
import tempfile
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks'))
from figure_bank import validate_figure_bank


class FigureBankTests(unittest.TestCase):
    def test_gold_bank_never_imported_by_serving_or_providers(self):
        import ast
        root=Path(__file__).resolve().parents[1]/'src/aura_bio'
        for folder in ('study','api','generation'):
            for source in (root/folder).rglob('*.py'):
                if source.name=='evaluation.py': continue
                for node in ast.walk(ast.parse(source.read_text(encoding='utf-8'))):
                    if isinstance(node,ast.ImportFrom): self.assertNotIn('figure_bank',node.module or '')
                    if isinstance(node,ast.Import): self.assertFalse(any('figure_bank' in n.name for n in node.names))
    def test_figure_bank_frozen_before_prompt_tuning(self):
        root = Path(__file__).resolve().parents[1] / 'benchmarks'
        result = validate_figure_bank(root / 'figure_bank.jsonl', root / 'figure_sources.json')
        self.assertEqual(result['figures'], 20)
        self.assertEqual(result['questions'], 40)
        self.assertEqual(result['splits'], {'dev': 24, 'holdout': 16})
        self.assertEqual(result['categories'], {'label': 16, 'relationship': 12, 'value': 6, 'absent': 6})
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            shutil.copytree(root / 'figure_fixtures', target / 'figure_fixtures')
            shutil.copy(root / 'figure_bank.jsonl', target)
            shutil.copy(root / 'figure_sources.json', target)
            bank = target / 'figure_bank.jsonl'
            bank.write_text(bank.read_text() + '\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                validate_figure_bank(bank, target / 'figure_sources.json')
            shutil.copy(root / 'figure_bank.jsonl', target)
            manifest = json.loads((target / 'figure_sources.json').read_text())
            source = target / manifest['sources'][0]['path']
            source.write_bytes(source.read_bytes() + b'changed')
            with self.assertRaises(ValueError):
                validate_figure_bank(bank, target / 'figure_sources.json')
