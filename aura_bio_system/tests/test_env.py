from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from aura_bio.env import CACHE_VARIABLES, ensure_cache_location, find_env_file, load_env


class CacheLocationTests(unittest.TestCase):
    """Model caches must land on the drive with room for them.

    ``.env`` sets ``HF_HOME`` to a data drive because the system drive cannot
    hold these models. A script that forgets ``load_env`` does not merely miss
    the setting: HuggingFace falls back to the system drive and re-downloads
    gigabytes there, which fills it, which stops Windows growing its paging
    file, which makes Ollama return HTTP 500 for every request. The cause looks
    like anything except a full disk, and it has cost this project hours twice.
    """

    def setUp(self) -> None:
        self._saved = {name: os.environ.get(name) for name in CACHE_VARIABLES}

    def tearDown(self) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_importing_the_package_sets_the_cache_path(self) -> None:
        """The whole point is that no explicit call is required."""

        import subprocess
        import sys

        source = Path(__file__).resolve().parents[1] / "src"
        result = subprocess.run(
            [sys.executable, "-c",
             "import os, sys; sys.path.insert(0, sys.argv[1]);"
             " import aura_bio; print(os.environ.get('HF_HOME', ''))",
             str(source)],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        self.assertTrue(
            result.stdout.strip(),
            "importing aura_bio left HF_HOME unset; caches will land on the system drive",
        )

    def test_an_existing_value_is_never_overridden(self) -> None:
        os.environ["HF_HOME"] = "/explicitly/chosen"
        ensure_cache_location()
        self.assertEqual(os.environ["HF_HOME"], "/explicitly/chosen")

    def test_only_cache_variables_are_applied(self) -> None:
        """Credentials stay explicit; this must not become a back door for them."""

        env_file = find_env_file()
        if env_file is None:
            self.skipTest("no .env in this checkout")
        for name in CACHE_VARIABLES:
            os.environ.pop(name, None)
        before = set(os.environ)
        applied = ensure_cache_location()
        new = set(os.environ) - before
        self.assertTrue(new <= set(CACHE_VARIABLES), f"leaked non-cache variables: {new}")
        self.assertTrue(set(applied) <= set(CACHE_VARIABLES))


class LoadEnvTests(unittest.TestCase):
    def test_values_already_set_win(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("AURA_TEST_KEY=from_file\n", encoding="utf-8")
            os.environ["AURA_TEST_KEY"] = "from_shell"
            try:
                load_env(path)
                self.assertEqual(os.environ["AURA_TEST_KEY"], "from_shell")
                load_env(path, override=True)
                self.assertEqual(os.environ["AURA_TEST_KEY"], "from_file")
            finally:
                os.environ.pop("AURA_TEST_KEY", None)

    def test_load_env_reports_names_not_values(self) -> None:
        """A log line about loading secrets must not print the secrets."""

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("AURA_TEST_SECRET=hunter2\n", encoding="utf-8")
            try:
                loaded = load_env(path)
                self.assertIn("AURA_TEST_SECRET", loaded)
                self.assertNotIn("hunter2", loaded.values())
            finally:
                os.environ.pop("AURA_TEST_SECRET", None)


if __name__ == "__main__":
    unittest.main()
