from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from aura_bio_pipeline.training_data import (
    PROSE_SOURCES,
    STRUCTURED_SOURCES,
    build_training_corpus,
    quality_score,
)

BIOLOGY = (
    "The mitochondrion is the organelle where cellular respiration occurs. Glucose is "
    "oxidised through glycolysis in the cytoplasm, and the resulting pyruvate enters the "
    "mitochondrial matrix. There the Krebs cycle transfers electrons to NADH, and the "
    "electron transport chain uses that energy to pump protons and synthesise ATP. This "
    "process supplies the cell with the energy it needs for metabolism and growth."
)


class QualityScoreTests(unittest.TestCase):
    def test_good_biology_prose_scores_well(self) -> None:
        score, reason = quality_score(BIOLOGY, 320)
        self.assertIsNone(reason)
        self.assertGreater(score, 0.45)

    def test_biography_is_rejected_even_though_it_is_good_prose(self) -> None:
        """Being filed under 'biology' does not make a life story teachable."""

        text = (
            "Biography\nHasnain spent several years at Texas A&M University and returned "
            "to India in 1987 to work as a staff scientist. He later served as director of "
            "a national institute and was elected to several academies. He has received "
            "numerous national honours for his service to science and education."
        )
        self.assertEqual(quality_score(text, 300)[1], "biographical")

    def test_clinical_review_scaffolding_is_rejected(self) -> None:
        text = (
            "This comparative effectiveness review followed a documented search strategy. "
            "Two reviewers independently applied the inclusion and exclusion criteria and "
            "assessed risk of bias for each randomised controlled trial. We graded the "
            "strength of evidence for every outcome and resolved disagreements by consensus."
        )
        self.assertEqual(quality_score(text, 300)[1], "clinical_review")

    def test_off_topic_prose_is_rejected(self) -> None:
        text = (
            "The committee met on Tuesday to review the annual budget allocations. Members "
            "discussed the schedule for the coming year and agreed to reconvene in spring. "
            "The chair thanked everyone for their continued participation and support in "
            "what has been a demanding and unusually busy administrative period."
        )
        self.assertEqual(quality_score(text, 300)[1], "off_topic")

    def test_short_and_non_prose_inputs_are_rejected(self) -> None:
        self.assertEqual(quality_score("Too short.", 400)[1], "too_short")
        self.assertEqual(quality_score("ATCG " * 200, 400)[1], "not_prose")

    def test_repetitive_text_is_rejected(self) -> None:
        text = ("The cell membrane is a cell membrane of the cell membrane. " * 12)
        self.assertIn(quality_score(text, 300)[1], {"repetitive", "abnormal_sentence_length"})


class BuildCorpusTests(unittest.TestCase):
    def _corpus(self, root: Path) -> Path:
        chunks = root / "chunks"
        for source in ("wikipedia_biology", "uniprot_sprot"):
            path = chunks / source / f"{source}-a.jsonl.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                for i in range(30):
                    handle.write(
                        json.dumps(
                            {
                                "chunk_id": f"{source}:{i}",
                                "document_id": f"{source}-doc-{i // 3}",
                                "source_id": source,
                                "title": f"{source} title {i}",
                                "text": f"{BIOLOGY} Variation {i} keeps each passage distinct.",
                                "token_count": 320,
                            }
                        )
                        + "\n"
                    )
        return chunks

    def test_selects_prose_and_writes_a_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunks = self._corpus(root)
            out = root / "train.jsonl"
            summary = build_training_corpus(
                chunks, out, target_bytes=20_000, sources=("wikipedia_biology",)
            )
            self.assertGreater(summary["kept"], 0)
            self.assertTrue(out.with_suffix(".manifest.json").is_file())
            shard = out.with_name("train-000.jsonl.gz")
            self.assertTrue(shard.is_file())
            with gzip.open(shard, "rt", encoding="utf-8") as handle:
                first = json.loads(handle.readline())
            self.assertIn("text", first)
            self.assertIn("quality", first)

    def test_structured_record_sources_are_excluded_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunks = self._corpus(root)
            out = root / "train.jsonl"
            summary = build_training_corpus(
                chunks, out, target_bytes=20_000,
                sources=("wikipedia_biology", "uniprot_sprot"),
            )
            self.assertNotIn("uniprot_sprot", summary["by_source"])
            self.assertIn("uniprot_sprot", STRUCTURED_SOURCES)

    def test_per_document_cap_limits_one_document(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chunks = self._corpus(root)
            out = root / "train.jsonl"
            build_training_corpus(
                chunks, out, target_bytes=200_000, sources=("wikipedia_biology",),
                max_per_document=2,
            )
            counts: dict[str, int] = {}
            for path in sorted(out.parent.glob("train-*.jsonl.gz")):
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    for line in handle:
                        row = json.loads(line)
                        key = row["chunk_id"].rsplit(":", 1)[0]
                        counts[key] = counts.get(key, 0) + 1
            self.assertTrue(counts)
            self.assertLessEqual(max(counts.values()), 2 * 10)

    def test_prose_sources_exclude_structured_ones(self) -> None:
        self.assertFalse(set(PROSE_SOURCES) & STRUCTURED_SOURCES)


class TemplateQuestionTests(unittest.TestCase):
    """Template questions come from headings, so bad headings must be rejected."""

    def test_concept_titles_produce_natural_questions(self) -> None:
        from aura_bio_pipeline.qa_data import _question_for

        self.assertIn("photosynthesis", _question_for("Photosynthesis", "Light-dependent reactions").lower())
        self.assertEqual(
            _question_for("Cell membrane", "Structure"), "Describe the structure of the cell membrane."
        )

    def test_publication_type_titles_are_rejected(self) -> None:
        """'Systematic Reviews' is a real title and a useless question."""

        from aura_bio_pipeline.qa_data import _question_for

        for title in ("Systematic Reviews", "Comparative Effectiveness Review", "Table of Contents"):
            self.assertIsNone(_question_for(title, "Background"), title)

    def test_book_titles_are_rejected_but_acronyms_are_kept(self) -> None:
        """'Botany (Ha, Morrow, and Algiers)' names a book; '(ATP)' names a concept."""

        from aura_bio_pipeline.qa_data import _question_for

        for title in ("Botany (Ha, Morrow, and Algiers)", "Cells - Molecules and Mechanisms (Wong)",
                      "Biology 2e, 3rd Edition"):
            self.assertIsNone(_question_for(title, None), title)
        for title in ("Adenosine triphosphate (ATP)", "Deoxyribonucleic acid (DNA)"):
            self.assertIsNotNone(_question_for(title, None), title)

    def test_clinical_reference_sections_are_treated_as_generic(self) -> None:
        """GeneReviews repeats these headings across ~1,000 rare diseases."""

        from aura_bio_pipeline.qa_data import _question_for

        for section in ("Molecular genetic testing", "Risk to family members",
                        "Related genetic counseling issues"):
            question = _question_for("Rett syndrome", section)
            self.assertNotIn(section.lower(), (question or "").lower())

    def test_missing_gold_file_is_an_error_not_silence(self) -> None:
        """A corpus built without its best data must not look like success."""

        from aura_bio_pipeline.qa_data import gold_pairs

        with self.assertRaises(FileNotFoundError):
            list(gold_pairs(Path("does/not/exist/gold_answers.jsonl")))

    def test_chemical_identifiers_are_rejected(self) -> None:
        from aura_bio_pipeline.qa_data import _question_for

        self.assertIsNone(
            _question_for("1(trans-[123I]Iodopropen-2-yl)-4-[(4-cyanophenoxy)methyl]piperidine", "Background")
        )


if __name__ == "__main__":
    unittest.main()
