import unittest

from aura_bio.study.reranking import StudyReranker
from test_study_pipeline import hit


class LiteralScorer:
    def __init__(self):
        self.pairs = []
    def predict(self, pairs):
        self.pairs = pairs
        return [0.02, 0.9]


class StudyRerankingTests(unittest.TestCase):
    def test_compound_question_retains_support_for_each_requested_fact(self):
        class Scorer:
            def predict(self, pairs, batch_size):
                return [(.9 if ('Which' in query and 'records' in text) or
                         ('Which' not in query and 'colour' in query and 'amber' in text)
                         else .02) for query, text in pairs]
        ranked, report = StudyReranker(scorer=Scorer()).rerank(
            'Which fields does LOG record, and what colour is the readable SENSOR state?',
            [hit(1, 'LOG records the tag and indicator.'),
             hit(2, 'The SENSOR shows amber when readable.')], 2)
        self.assertEqual({item.chunk_id for item in ranked}, {f'{1:032x}', f'{2:032x}'})
        self.assertGreater(len(report.query_parts), 1)

    def test_explicit_sequence_keeps_each_named_step_as_a_scored_query(self):
        class Scorer:
            def predict(self, pairs, batch_size):
                return [(.9 if query in {'ALPHA', 'BETA', 'GAMMA'} and query in text
                         else .02) for query, text in pairs]
        ranked, report = StudyReranker(scorer=Scorer()).rerank(
            'What is written first and what follows sealing in the ALPHA–BETA–GAMMA sequence?',
            [hit(1, 'ALPHA is written first.'), hit(2, 'BETA seals the vessel.'),
             hit(3, 'GAMMA is checked after sealing.')], 3)
        self.assertEqual(len(ranked), 3)
        self.assertTrue({'ALPHA', 'BETA', 'GAMMA'} <= set(report.query_parts))

    def test_small_cpu_batch_preserves_all_candidate_scores_and_ranking(self):
        class Scorer:
            def predict(self, pairs, batch_size):
                self.batch = batch_size
                return [0.2, 0.9, 0.5]
        scorer = Scorer()
        ranked, report = StudyReranker(scorer=scorer, batch_size=2).rerank(
            'ORION', [hit(1, 'one'), hit(2, 'two'), hit(3, 'three')], 3)
        self.assertEqual(scorer.batch, 2)
        self.assertEqual([item.chunk_id for item in ranked], [f'{2:032x}', f'{3:032x}', f'{1:032x}'])
        self.assertEqual(report.candidates, 3)

    def test_invalid_cpu_batch_is_rejected_before_inference(self):
        for value in (0, -1, True, 2.5):
            with self.assertRaises(ValueError):
                StudyReranker(scorer=LiteralScorer(), batch_size=value)

    def test_weak_secondary_support_is_not_cut_by_a_binary_confidence_threshold(self):
        class SecondaryScorer:
            def predict(self, pairs):
                return [0.95, 0.3]
        ranked, _ = StudyReranker(scorer=SecondaryScorer()).rerank('ORION',
            [hit(1, 'ORION overview.'), hit(2, 'ORION secondary supporting detail.')], 2)
        self.assertEqual(len(ranked), 2)

    def test_comparison_with_reserves_support_for_both_requested_subjects(self):
        class SubjectScorer:
            def predict(self, pairs):
                scores = []
                for query, passage in pairs:
                    if 'Compare' in query:
                        scores.append(0.96 if 'details' in passage else (0.95 if 'ORION' in passage else 0.15))
                    elif 'VEGA' in query:
                        scores.append(0.93 if 'VEGA' in passage else 0.02)
                    else:
                        scores.append(0.99 if 'pathway' in passage else (0.9 if 'ORION' in passage else 0.02))
                return scores
        candidates = [hit(1, 'ORION calibration pathway.'), hit(2, 'ORION calibration details.'),
                      hit(3, 'VEGA assessment method.')]
        ranked, report = StudyReranker(scorer=SubjectScorer()).rerank(
            'Compare ORION calibration pathway with VEGA assessment method', candidates, 2)
        self.assertEqual({item.chunk_id for item in ranked}, {f'{1:032x}', f'{3:032x}'})
        self.assertEqual(len(report.as_dict()['query_parts']), 3)

    def test_reranker_normalizes_scientific_text_and_filters_unrelated_candidates(self):
        scorer = LiteralScorer()
        candidates = [hit(1, 'Bibliography: cancer reference.'), hit(2, 'γδT cells show cyto-\ntoxic activity.')]
        ranked, report = StudyReranker(scorer=scorer).rerank('gamma delta cytotoxic', candidates, 10)
        self.assertEqual([item.chunk_id for item in ranked], [f'{2:032x}'])
        self.assertIn('gamma delta', scorer.pairs[1][1])
        self.assertIn('cytotoxic', scorer.pairs[1][1])
        self.assertEqual(ranked[0].text, 'γδT cells show cyto-\ntoxic activity.')
        self.assertEqual(ranked[0].rerank_score, 0.9)
        self.assertEqual(report.selected, 1)

    def test_all_unrelated_candidates_leave_no_evidence(self):
        class NegativeScorer:
            def predict(self, pairs):
                return [0.02] * len(pairs)
        ranked, report = StudyReranker(scorer=NegativeScorer()).rerank('capital France', [hit(1, 'Cancer cells divide.')], 5)
        self.assertEqual(ranked, [])
        self.assertEqual(report.selected, 0)
