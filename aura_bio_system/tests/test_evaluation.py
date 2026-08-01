from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aura_bio.evaluation import (
    CallableRunner,
    all_questions,
    format_markdown_table,
    read_jsonl,
    run_benchmark,
    score_answer,
    write_jsonl,
)
from aura_bio.evaluation.questions import GROUPS


class QuestionSetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.questions = all_questions()

    def test_size_is_in_target_range(self) -> None:
        self.assertGreaterEqual(len(self.questions), 400)
        self.assertLessEqual(len(self.questions), 520)

    def test_ids_are_unique_and_sequential(self) -> None:
        ids = [q.id for q in self.questions]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[0], "bio-0001")

    def test_all_eighteen_subdomains_are_covered(self) -> None:
        subdomains = {q.subdomain for q in self.questions}
        expected = {
            "general_biology", "cell_biology", "molecular_biology", "genetics",
            "microbiology", "botany", "zoology", "ecology", "evolution",
            "physiology", "anatomy", "immunology", "biochemistry", "biotechnology",
            "neuroscience", "developmental_biology", "bioinformatics", "interdisciplinary",
        }
        self.assertTrue(expected.issubset(subdomains))

    def test_has_numeric_process_and_adversarial_items(self) -> None:
        self.assertGreaterEqual(sum(1 for q in self.questions if q.answer_key.numeric is not None), 5)
        self.assertGreaterEqual(sum(1 for q in self.questions if q.answer_key.ordered_steps), 5)
        self.assertGreaterEqual(sum(1 for q in self.questions if q.adversarial), 5)

    def test_adversarial_items_declare_refusal_markers(self) -> None:
        for q in self.questions:
            if q.adversarial:
                self.assertTrue(q.answer_key.must_include, q.id)

    def test_jsonl_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "b.jsonl"
            write_jsonl(self.questions, path)
            back = list(read_jsonl(path))
            self.assertEqual(len(back), len(self.questions))
            self.assertEqual(back[0].id, self.questions[0].id)
            self.assertEqual(back[10].answer_key.must_include, self.questions[10].answer_key.must_include)


class ScorerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.by_id = {q.id: q for q in all_questions()}

    def _q(self, needle: str):
        return next(q for q in self.by_id.values() if needle.lower() in q.question.lower())

    def test_concept_recall(self) -> None:
        q = self._q("central dogma")
        full = score_answer(
            q, "The central dogma: DNA undergoes transcription to RNA and translation to protein."
        )
        self.assertGreaterEqual(full.concept_recall, 0.8)
        empty = score_answer(q, "I am not sure.")
        self.assertEqual(empty.concept_recall, 0.0)

    def test_markup_inside_a_key_phrase_does_not_hide_it(self) -> None:
        """"**allele** frequency" makes the claim "allele frequency" does.

        The key compiles to ``allele\\s+frequenc...``, which cannot match across
        the emphasis markers. This penalised the pipeline specifically, since it
        is instructed to structure its answers and the bare model is not.
        """

        q = self._q("genetic drift")
        plain = score_answer(q, "Genetic drift is a change in allele frequency by random sampling.")
        marked = score_answer(q, "Genetic drift is a change in **allele** frequency by random sampling.")
        self.assertEqual(marked.concept_recall, plain.concept_recall)
        self.assertGreater(marked.concept_recall, 0.0)

    def test_latex_commands_keep_their_names(self) -> None:
        """Stripping a command wholesale would delete content, not formatting."""

        from aura_bio.evaluation.scorer import strip_markup

        self.assertEqual(strip_markup(r"the $\alpha$-carbon"), "the alpha-carbon")
        self.assertEqual(strip_markup("thermo**regulation**"), "thermoregulation")

    def test_markup_cannot_hide_a_forbidden_phrase(self) -> None:
        """Normalising must make the scorer stricter here, not more lenient."""

        q = next(q for q in self.by_id.values() if q.answer_key.must_avoid)
        banned = q.answer_key.must_avoid[0]
        marked = "".join(f"**{ch}**" if ch.isalpha() else ch for ch in banned)
        self.assertFalse(score_answer(q, f"Some text {marked} more text.").avoided_forbidden)

    def test_british_and_american_spellings_agree(self) -> None:
        """The keys were written "-ise"; the model answers "-ize"."""

        from aura_bio.evaluation.scorer import normalise_orthography

        self.assertEqual(
            normalise_orthography("depolarise"), normalise_orthography("depolarize")
        )
        self.assertEqual(
            normalise_orthography("opsonisation"), normalise_orthography("opsonization")
        )

    def test_hyphen_and_space_agree(self) -> None:
        """The key says "R group"; essentially every answer writes "R-group"."""

        from aura_bio.evaluation.scorer import normalise_orthography

        self.assertEqual(normalise_orthography("r group"), normalise_orthography("r-group"))
        self.assertEqual(
            normalise_orthography("alpha helix"), normalise_orthography("alpha-helix")
        )

    def test_stemming_is_still_refused(self) -> None:
        """Folding orthography must not slide into guessing at word senses.

        "divergent" for the key "diverge" stays a miss. It is a real limitation,
        kept deliberately: the scorer's value is that it is reproducible.
        """

        q = self._q("homologous structures")
        scored = score_answer(q, "Homologous structures demonstrate divergent evolution.")
        self.assertIn("diverge", [c.lower() for c in scored.detail.get("missing_concepts", [])])

    def test_hardy_weinberg_numeric_correct(self) -> None:
        q = self._q("16% of a population shows a recessive trait")
        good = score_answer(q, "q^2 = 0.16 so q = 0.4, p = 0.6, and the heterozygote frequency 2pq = 0.48.")
        self.assertTrue(good.numeric_correct)
        self.assertEqual(good.overall, 1.0 * 0.8 + good.concept_recall * 0.2)
        bad = score_answer(q, "The heterozygote frequency is 0.32.")
        self.assertFalse(bad.numeric_correct)

    def test_fraction_and_percent_answers_are_understood(self) -> None:
        q = self._q("two carriers of cystic fibrosis")  # expected 0.25
        for phrasing in ("There is a 1/4 chance.", "There is a 25% chance.", "The probability is 0.25."):
            with self.subTest(phrasing=phrasing):
                self.assertTrue(score_answer(q, phrasing).numeric_correct)

    def test_forbidden_phrase_penalised(self) -> None:
        q = self._q("10% of their brains")
        wrong = score_answer(q, "Yes, it is true, we only use 10% of our brain.")
        self.assertFalse(wrong.avoided_forbidden)

    def test_process_order_detected(self) -> None:
        q = next(x for x in self.by_id.values()
                 if x.answer_key.ordered_steps and "mitosis" in x.question.lower())
        good = score_answer(q, "Mitosis goes prophase, then metaphase, then anaphase, then telophase.")
        self.assertTrue(good.order_correct)
        bad = score_answer(q, "Mitosis goes telophase, then anaphase, then metaphase, then prophase.")
        self.assertFalse(bad.order_correct)

    def test_adversarial_refusal_scores_full_fabrication_scores_zero(self) -> None:
        q = next(x for x in self.by_id.values() if x.adversarial)
        refuse = score_answer(q, "There is no such structure; it does not exist in biology.")
        self.assertFalse(refuse.hallucinated)
        self.assertEqual(refuse.overall, 1.0)
        fabricate = score_answer(q, q.answer_key.must_avoid[0] + " it transfers lipids between compartments.")
        self.assertTrue(fabricate.hallucinated)
        self.assertEqual(fabricate.overall, 0.0)


class HarnessTests(unittest.TestCase):
    def test_four_way_run_produces_a_table(self) -> None:
        questions = all_questions()[:20]

        def oracle(q) -> str:
            # Answers with every required concept and the right number.
            parts = list(q.answer_key.must_include)
            if q.answer_key.numeric is not None:
                parts.append(str(q.answer_key.numeric))
            return " ".join(parts)

        def clueless(q) -> str:
            return "I don't know."

        runners = [
            CallableRunner("baseline", clueless),
            CallableRunner("basic_rag", oracle),
            CallableRunner("full_rag", oracle),
        ]
        report = run_benchmark(runners, questions)
        self.assertEqual(report.questions, 20)
        table = report.table()
        self.assertEqual(len(table), 3)
        baseline = next(r for r in table if r["System"] == "baseline")
        full = next(r for r in table if r["System"] == "full_rag")
        self.assertLess(baseline["Overall"], full["Overall"])
        markdown = format_markdown_table(report)
        self.assertIn("| System |", markdown)
        self.assertIn("baseline", markdown)

    def test_discriminative_mean_excludes_saturated_questions(self) -> None:
        """The overall mean is diluted by questions every system already aces."""

        from aura_bio.evaluation.harness import SystemResult
        from aura_bio.evaluation.scorer import QuestionScore

        def score(qid: str, value: float) -> QuestionScore:
            return QuestionScore(qid, "genetics", "definition", value, True, None, None, None, value)

        result = SystemResult(
            system="s",
            scores=[score("a", 1.0), score("b", 1.0), score("c", 0.4)],
            latencies_ms=[1.0, 1.0, 1.0],
            saturated_ids=frozenset({"a", "b"}),
        )
        self.assertAlmostEqual(result.aggregate()["overall_mean"], 0.8)
        # Only the question that is not already saturated counts here.
        self.assertAlmostEqual(result.discriminative_mean(), 0.4)
        self.assertEqual(result.aggregate()["discriminative_n"], 1)

    def test_runner_error_is_counted_not_fatal(self) -> None:
        def broken(q) -> str:
            raise RuntimeError("model down")

        report = run_benchmark([CallableRunner("broken", broken)], all_questions()[:5])
        self.assertEqual(report.results[0].errors, 5)


if __name__ == "__main__":
    unittest.main()
