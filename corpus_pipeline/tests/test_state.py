from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from aura_bio_pipeline.dedup import StateStore, compact_state


class StateTests(unittest.TestCase):
    def test_compaction_preserves_resume_rows_and_clears_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "pipeline.sqlite3"
            output = root / "document.jsonl.gz"
            output.write_bytes(b"complete")
            state = StateStore(database)
            state.begin()
            state.accept("document:test", "digest", "record:1")
            state.commit_input("ingest", "input", "signature", output, 1)
            state.close()

            report = compact_state(database)

            connection = sqlite3.connect(database)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM seen").fetchone()[0], 0)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM processed_inputs").fetchone()[0], 1
                )
            finally:
                connection.close()
            self.assertEqual(report["processed_inputs"], 1)


if __name__ == "__main__":
    unittest.main()
