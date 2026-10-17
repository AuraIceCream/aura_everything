import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from aura_bio.evaluation.manifest import ensure_run_manifest


class RunManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "pipeline.py"
        self.source.write_text("version = 1\n", encoding="utf-8")
        self.bank = self.root / "questions.jsonl"
        self.bank.write_text('{"id": "q1"}\n', encoding="utf-8")
        self.manifest = self.root / "run.settings.json"
        self.results = self.root / "run.jsonl"
        self.settings = {"model": "llama3.2:1b", "seed": 42}

    def save(self):
        ensure_run_manifest(self.manifest, self.results, self.settings,
                            [self.source], [self.bank])

    def test_unchanged_run_can_resume_without_rewriting_manifest(self):
        self.save()
        before = self.manifest.read_bytes()
        self.results.write_text('{"id": "q1"}\n', encoding="utf-8")
        self.save()
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_code_edit_rejects_resume_and_preserves_results(self):
        self.save()
        self.results.write_text("saved answer\n", encoding="utf-8")
        self.source.write_text("version = 2\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.save()
        self.assertEqual(self.results.read_text(encoding="utf-8"), "saved answer\n")

    def test_question_bank_edit_rejects_resume(self):
        self.save()
        self.bank.write_text('{"id": "q2"}\n', encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.save()

    def test_changed_settings_reject_resume_without_overwriting_manifest(self):
        self.save()
        before = self.manifest.read_bytes()
        self.settings["seed"] = 7
        with self.assertRaises(SystemExit):
            self.save()
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_untracked_existing_results_are_not_relabelled_as_new_run(self):
        self.results.write_text("legacy answer\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.save()
        self.assertFalse(self.manifest.exists())

    def test_legacy_settings_without_hashes_cannot_resume(self):
        self.manifest.write_text(json.dumps(self.settings), encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.save()

    def test_new_python_source_file_rejects_resume(self):
        source_root = self.root / "src"
        source_root.mkdir()
        (source_root / "a.py").write_text("a = 1\n", encoding="utf-8")
        ensure_run_manifest(self.manifest, self.results, self.settings, [source_root])
        (source_root / "b.py").write_text("b = 1\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            ensure_run_manifest(self.manifest, self.results, self.settings, [source_root])

    def test_missing_input_does_not_create_a_manifest(self):
        self.bank.unlink()
        with self.assertRaises(FileNotFoundError):
            self.save()
        self.assertFalse(self.manifest.exists())
