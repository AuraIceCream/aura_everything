from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aura_bio_pipeline.models import Document
from aura_bio_pipeline.provenance import AcquisitionManifest


class ProvenanceTests(unittest.TestCase):
    def test_item_license_and_checksum_are_inherited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "book.pdf"
            manifest = root / "05_Metadata" / "manifests" / "files.jsonl"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    {
                        "local_path": str(source),
                        "status": "complete",
                        "sha256": "abc",
                        "url": "https://provider/pdf",
                        "metadata": {
                            "license_ids": ["CC BY-NC-SA"],
                            "license_state": "allowed_noncommercial",
                            "license_evidence_url": "https://provider/license",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            document = Document(
                document_id="doc:1",
                source_id="books",
                category="textbook",
                title="Book",
                text="text",
                source_path=str(source),
            )
            AcquisitionManifest(root).enrich(document, source)
        self.assertEqual(document.license_id, "CC BY-NC-SA")
        self.assertEqual(document.metadata["acquisition"]["sha256"], "abc")


if __name__ == "__main__":
    unittest.main()

