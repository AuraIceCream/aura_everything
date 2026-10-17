"""Label-key mismatch is not evidence that visible text was hallucinated."""
import unittest
from copy import deepcopy

from aura_bio.study.visual.evaluation import evaluate_figure_run


class FigureLabelAccountingTests(unittest.TestCase):
    def setUp(self):
        self.bank = [
            {'id': 'q1', 'figure_id': 'f1', 'split': 'dev',
             'category': 'label', 'key': 'NodeA',
             'visible_labels': ['NodeA', 'NodeB']},
            {'id': 'q2', 'figure_id': 'f1', 'split': 'dev',
             'category': 'relationship', 'key': 'left to right',
             'visible_labels': ['NodeA', 'NodeB']},
        ]
        self.labels = ['Teaching figure', 'NodeA', 'NodeB', 'Value: 7 units']

    def records(self, review=None):
        return [
            {'id': q['id'], 'state': 'completed', 'labels': list(self.labels),
             **({'review': deepcopy(review)} if review is not None else {})}
            for q in self.bank
        ]

    def test_extra_text_is_unmatched_not_automatically_hallucinated(self):
        result = evaluate_figure_run(self.records(), self.bank)
        self.assertEqual(result['label_recall'], 1.0)
        self.assertEqual(result['unmatched_label_rate'], 0.5)
        self.assertIsNone(result['hallucinated_label_rate'])
        self.assertEqual(result['label_review_pending_figures'], 1)
        self.assertEqual(result['unmatched_labels'], [
            {'figure_id': 'f1', 'labels': ['Teaching figure', 'Value: 7 units']}])

    def test_review_can_confirm_extra_text_is_visible(self):
        result = evaluate_figure_run(self.records({
            'label_review_complete': True, 'hallucinated_labels': []}), self.bank)
        self.assertEqual(result['hallucinated_label_rate'], 0.0)
        self.assertEqual(result['label_reviewed_figures'], 1)
        self.assertEqual(result['label_review_pending_figures'], 0)

    def test_review_counts_actual_invention_once_per_figure(self):
        result = evaluate_figure_run(self.records({
            'label_review_complete': True,
            'hallucinated_labels': ['Value: 7 units']}), self.bank)
        self.assertEqual(result['hallucinated_label_rate'], 0.25)
        self.assertEqual(result['observed_labels'], 4)

    def test_unrelated_answer_review_does_not_review_labels(self):
        result = evaluate_figure_run(self.records({'answer_correct': True}), self.bank)
        self.assertIsNone(result['hallucinated_label_rate'])

    def test_review_cannot_name_text_not_in_model_output(self):
        with self.assertRaises(ValueError):
            evaluate_figure_run(self.records({
                'label_review_complete': True,
                'hallucinated_labels': ['Not reported']}), self.bank)

    def test_duplicate_question_reviews_must_agree(self):
        rows = self.records({'label_review_complete': True,
                             'hallucinated_labels': []})
        rows[1]['review']['hallucinated_labels'] = ['Teaching figure']
        with self.assertRaises(ValueError):
            evaluate_figure_run(rows, self.bank)


if __name__ == '__main__':
    unittest.main()
