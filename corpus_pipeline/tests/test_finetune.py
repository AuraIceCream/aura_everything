from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from aura_bio_pipeline.finetune import make_finetune_pack


class FineTunePackTests(unittest.TestCase):
    def test_pack_keeps_core_pubmed_and_qa(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunks = root / "chunks"
            for source in ("wikipedia_biology", "pubmed_filtered", "pubmedqa_labeled"):
                path = chunks / source / "sample.jsonl.gz"
                path.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(path, "wt", encoding="utf-8") as handle:
                    handle.write(json.dumps({"text": source}) + "\n")
            report = make_finetune_pack(chunks, root / "pack", pubmed_gib=0.000001)
            self.assertTrue((root / "pack" / "chunks" / "wikipedia_biology" / "sample.jsonl.gz").is_file())
            self.assertTrue((root / "pack" / "chunks" / "pubmed_filtered" / "sample.jsonl.gz").is_file())
            self.assertTrue((root / "pack" / "chunks" / "pubmedqa_labeled" / "sample.jsonl.gz").is_file())
            self.assertTrue((root / "pack" / "manifest.json").is_file())
            self.assertGreaterEqual(report["files"], 3)


if __name__ == "__main__":
    unittest.main()
