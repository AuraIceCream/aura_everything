"""Launcher control-flow tests: no provider/model/index work is performed."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'benchmarks/start_study_benchmark.py'
spec = importlib.util.spec_from_file_location('study_benchmark_launcher', SCRIPT)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class StudyBenchmarkLauncherTests(unittest.TestCase):
    def test_prepare_only_does_not_start_benchmarks(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(launcher.os.environ), \
                patch.object(launcher, 'prepare_pack', return_value='a' * 32) as prepare, \
                patch.object(launcher, 'run_benchmarks') as run:
            self.assertEqual(launcher.main(['--root', folder]), 0)
            prepare.assert_called_once_with(Path(folder).resolve())
            run.assert_not_called()

    def test_explicit_run_uses_generated_id_not_shell_placeholder(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(launcher.os.environ), \
                patch.object(launcher, 'prepare_pack', return_value='b' * 32), \
                patch.object(launcher, 'run_benchmarks') as run:
            launcher.main(['--root', folder, '--run'])
            run.assert_called_once_with(Path(folder).resolve(), 'b' * 32,
                                        'qwen3.5:4b', 'pack_20261011')

    def test_preparation_failure_never_starts_benchmarks(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(launcher.os.environ), \
                patch.object(launcher, 'prepare_pack', side_effect=RuntimeError('failed')), \
                patch.object(launcher, 'run_benchmarks') as run:
            with self.assertRaises(RuntimeError):
                launcher.main(['--root', folder, '--run'])
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
