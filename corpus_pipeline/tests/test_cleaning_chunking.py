from __future__ import annotations

import unittest

from aura_bio_pipeline.chunking import chunk_document
from aura_bio_pipeline.cleaning import clean_structured_text, clean_text, normalize_text
from aura_bio_pipeline.models import Document


class WordTokenizer:
    """Tiny reversible tokenizer used to test boundaries without model files."""

    def __init__(self) -> None:
        self.tokens: list[str] = []

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        result = []
        for token in text.split():
            self.tokens.append(token)
            result.append(len(self.tokens) - 1)
        return result

    def decode(self, token_ids: list[int], skip_special_tokens: bool = True) -> str:
        return " ".join(self.tokens[item] for item in token_ids)


class CleaningChunkingTests(unittest.TestCase):
    def test_repairs_mojibake_and_layout(self) -> None:
        value = normalize_text("FranÃ§ois\r\n\r\n  biology   text")
        self.assertEqual(value, "François\n\nbiology text")

    def test_removes_reference_tail(self) -> None:
        value = clean_text("Useful biology.\n\n## References\n\nCitation")
        self.assertEqual(value, "Useful biology.")

    def test_structured_cleaner_normalizes_without_rewriting_fields(self) -> None:
        value = clean_structured_text("## Protein\r\n\r\n  p53   kinase\x00")
        self.assertEqual(value, "## Protein\n\np53 kinase")

    def test_chunks_stay_within_model_limit(self) -> None:
        document = Document(
            document_id="doc:1",
            source_id="test",
            category="literature",
            title="Cell biology",
            text="## Mechanism\n\n" + " ".join(f"word{i}" for i in range(1200)),
            source_path="test.txt",
        )
        chunks = list(chunk_document(document, WordTokenizer(), 100, 200, 220, 20))
        self.assertGreater(len(chunks), 4)
        self.assertTrue(all(item.token_count <= 220 for item in chunks))
        self.assertEqual(chunks[0].section, "Mechanism")

    def test_short_source_text_is_not_rewritten(self) -> None:
        text = "## DNA Repair\n\np53-mediated repair retains CASE and punctuation!"
        document = Document(
            document_id="doc:2",
            source_id="test",
            category="literature",
            title="Genome",
            text=text,
            source_path="test.txt",
        )
        result = list(chunk_document(document, WordTokenizer(), 10, 50, 60, 5))[0]
        self.assertIn("p53-mediated repair retains CASE and punctuation!", result.text)


if __name__ == "__main__":
    unittest.main()
