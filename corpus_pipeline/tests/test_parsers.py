from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aura_bio_pipeline.config import SourceConfig
from aura_bio_pipeline.parsers import parse_file


class ParserTests(unittest.TestCase):
    def test_wikipedia_page(self) -> None:
        source = SourceConfig("wikipedia_biology", "reference", "wikipedia_json", ("*.json",), "CC")
        payload = {
            "query": {
                "pages": [
                    {
                        "pageid": 42,
                        "title": "Cell",
                        "canonicalurl": "https://example/cell",
                        "revisions": [
                            {
                                "revid": 7,
                                "timestamp": "2026-01-01T00:00:00Z",
                                "slots": {
                                    "main": {
                                        "content": "'''Cell''' is biological.\n\n==Structure==\nA membrane.\n\n==References==\n* citation"
                                    }
                                },
                            }
                        ],
                    }
                ]
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "page.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            rows = list(parse_file(path, source))
        self.assertEqual(len(rows), 1)
        self.assertIn("A membrane", rows[0].text)
        self.assertNotIn("citation", rows[0].text)

    def test_jats_article_set(self) -> None:
        source = SourceConfig("pmc", "literature", "jats_xml", ("*.xml",), "CC")
        xml = """<pmc-articleset><article><front><article-meta>
        <article-id pub-id-type="pmc">PMC1</article-id>
        <title-group><article-title>Test article</article-title></title-group>
        <abstract><p>Abstract text.</p></abstract></article-meta></front>
        <body><sec><title>Results</title><p>Biological result text.</p></sec></body>
        </article></pmc-articleset>"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "article.xml"
            path.write_text(xml, encoding="utf-8")
            rows = list(parse_file(path, source))
        self.assertEqual(rows[0].external_id, "PMC1")
        self.assertIn("Biological result", rows[0].text)

    def test_obo_term(self) -> None:
        source = SourceConfig("go", "knowledge_base", "obo", ("*.obo",), "CC")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "go.obo"
            path.write_text("[Term]\nid: GO:1\nname: test process\ndef: \"A process.\" []\n", encoding="utf-8")
            rows = list(parse_file(path, source))
        self.assertEqual(rows[0].external_id, "GO:1")
        self.assertIn("test process", rows[0].text)


if __name__ == "__main__":
    unittest.main()

