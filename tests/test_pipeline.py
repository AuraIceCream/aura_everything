from __future__ import annotations

import bz2
import gzip
import json
import tempfile
import unittest
import os
from pathlib import Path

from aura_corpus.catalogs import parse_catalog_links
from aura_corpus.cli import _byte_count
from aura_corpus.curation import CascadeCurator, deterministic_gate
from aura_corpus.download import DownloadBudget, DownloadLimitExceeded, _sidecar_checksum
from aura_corpus.env import load_dotenv
from aura_corpus.discovery import _parse_checksum_manifest
from aura_corpus.models import RemoteFile
from aura_corpus.registry import load_registry
from aura_corpus.store import ManifestStore
from aura_corpus.validation import digest, validate


class FakeJudge:
    def __init__(self, decision: str, confidence: float, name: str) -> None:
        self.decision = decision
        self.confidence = confidence
        self.name = name

    def classify(self, record):
        return {
            "decision": self.decision,
            "confidence": self.confidence,
            "reason": "fixture",
            "judge": self.name,
            "subdomains": [],
            "quality_flags": [],
            "academic_level": "unknown",
            "document_type": "unknown",
        }


class PipelineTests(unittest.TestCase):
    def test_registry_contains_expected_sources(self):
        _, sources = load_registry()
        ids = {source.id for source in sources}
        self.assertIn("pubmed_baseline", ids)
        self.assertIn("pmc_oa_comm_xml", ids)
        self.assertIn("gene_ontology", ids)
        self.assertIn("pubmedqa_labeled", ids)
        self.assertIn("biolibretexts_catalog", ids)
        self.assertIn("ebooksdirectory_biology_catalog", ids)
        self.assertIn("freebookcentre_biology_catalog", ids)
        self.assertIn("wikipedia_biology", ids)
        self.assertNotIn("wikipedia_en", ids)
        self.assertNotIn("openstax", ids)

    def test_checksum_manifest_parser(self):
        checksums = _parse_checksum_manifest(
            "d2b2a2d2e46522a4b937f2f4f8a7d9d0  sample.gz\n"
            "0123456789012345678901234567890123456789 *dump.bz2\n"
        )
        self.assertEqual(checksums["sample.gz"][0], "md5")
        self.assertEqual(checksums["dump.bz2"][0], "sha1")

    def test_pubmed_style_md5_sidecar(self):
        from unittest.mock import patch

        item = RemoteFile(
            source_id="pubmed",
            category="01_Literature",
            url="https://example.invalid/a.xml.gz",
            filename="a.xml.gz",
            checksum_url="https://example.invalid/a.xml.gz.md5",
        )
        response = type("Response", (), {"body": b"MD5(a.xml.gz)= fb7c05737f47f7e07245f0c064c6e00a\n"})()
        with patch("aura_corpus.download.request_bytes", return_value=response):
            self.assertEqual(
                _sidecar_checksum(item),
                ("md5", "fb7c05737f47f7e07245f0c064c6e00a"),
            )

    def test_validation_for_compressed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gz = root / "good.xml.gz"
            bz = root / "good.xml.bz2"
            with gzip.open(gz, "wb") as handle:
                handle.write(b"<root>biology</root>")
            with bz2.open(bz, "wb") as handle:
                handle.write(b"<root>biology</root>")
            self.assertEqual(validate(gz), (True, "ok"))
            self.assertEqual(validate(bz), (True, "ok"))
            gz.write_bytes(b"not gzip")
            self.assertFalse(validate(gz)[0])

    def test_manifest_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ManifestStore(root / "metadata" / "corpus.sqlite3")
            item = RemoteFile(
                source_id="fixture",
                category="01_Literature",
                url="https://example.invalid/sample.xml.gz",
                filename="sample.xml.gz",
                metadata={"title": "Example"},
            )
            store.plan(item, root / "sample.xml.gz")
            store.update("fixture", "sample.xml.gz", "complete", actual_bytes=12, sha256="abc")
            export = root / "files.jsonl"
            store.export_jsonl(export)
            store.close()
            record = json.loads(export.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "complete")
            self.assertEqual(record["metadata"]["title"], "Example")

    def test_deterministic_license_gate(self):
        result = deterministic_gate({"license_state": "unknown", "text": "x" * 500})
        self.assertEqual(result["decision"], "quarantine")
        self.assertEqual(result["judge"], "rules")

    def test_cascade_agreement_and_disagreement(self):
        record = {"license_state": "allowed", "text": "biology " * 100}
        curator = CascadeCurator(
            local=FakeJudge("accept", 0.5, "local"),
            external=FakeJudge("accept", 0.9, "external"),
        )
        self.assertEqual(curator.classify(record)["decision"], "accept")
        curator.external = FakeJudge("quarantine", 0.9, "external")
        self.assertEqual(curator.classify(record)["decision"], "quarantine")

    def test_byte_count(self):
        self.assertEqual(_byte_count("1GiB"), 1024**3)
        self.assertEqual(_byte_count("1.5GB"), 1_500_000_000)

    def test_shared_download_budget(self):
        budget = DownloadBudget(10, used=4)
        budget.consume(6)
        with self.assertRaises(DownloadLimitExceeded):
            budget.consume(1)

        source_budget = DownloadBudget(100, used=10, source_limit=8, source_used=6)
        source_budget.consume(2)
        with self.assertRaises(DownloadLimitExceeded):
            source_budget.consume(1)

    def test_catalog_link_parser_uses_text_and_image_alt(self):
        html = '<a href="book/1">Cell <img alt="Biology"> Basics</a>'
        self.assertEqual(
            parse_catalog_links(html, "https://example.org/catalog/")[0],
            ("https://example.org/catalog/book/1", "Cell Biology Basics"),
        )

    def test_dotenv_loader_does_not_override_process_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("AURA_TEST_VALUE=from-file\nEMPTY=\n", encoding="utf-8")
            prior = os.environ.get("AURA_TEST_VALUE")
            os.environ["AURA_TEST_VALUE"] = "from-process"
            try:
                self.assertTrue(load_dotenv(path))
                self.assertEqual(os.environ["AURA_TEST_VALUE"], "from-process")
                self.assertEqual(os.environ["EMPTY"], "")
            finally:
                if prior is None:
                    os.environ.pop("AURA_TEST_VALUE", None)
                else:
                    os.environ["AURA_TEST_VALUE"] = prior
                os.environ.pop("EMPTY", None)


if __name__ == "__main__":
    unittest.main()
