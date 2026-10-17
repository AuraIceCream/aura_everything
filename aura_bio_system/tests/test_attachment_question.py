import unittest
from dataclasses import replace
from unittest.mock import patch
from test_figure_description import figure_input
from test_visual_jobs import VisualJobsTests, FakeDescriber
from aura_bio.study.schema import StudyError
from aura_bio.study.visual.schema import VisualJobConfig
from aura_bio.study.visual.description import messages


class QuestionTests(unittest.TestCase):
    def test_question_is_untrusted_focus_and_part_of_configuration(self):
        original = figure_input()
        focused = replace(original, config=VisualJobConfig(question='What does the A to B arrow mean?'))
        self.assertIn('UNTRUSTED QUESTION', messages(focused))
        self.assertIn('A to B arrow', messages(focused))
        self.assertNotEqual(original.config.checksum, focused.config.checksum)
        self.assertNotIn('UNTRUSTED QUESTION', messages(original))
        with self.assertRaises(StudyError):
            VisualJobConfig(question='x' * 4001)

    def test_strict_answer_generator_never_retries_on_cpu(self):
        from aura_bio.api.generation import OllamaGenerator
        from aura_bio.study.routing import StudyRouter
        generator = OllamaGenerator(model='exact:1b', retries=2)
        generator.strict_no_fallback = True
        with patch('urllib.request.urlopen', side_effect=OSError('unavailable')) as transport, patch('time.sleep'):
            with self.assertRaises(RuntimeError):
                generator.generate(StudyRouter().route('What is ORION?'), [], ())
        self.assertEqual(transport.call_count, 1)
        import json
        self.assertIsNotNone(json.loads(transport.call_args.args[0].data)['options']['num_gpu'])


class QuestionJobsTests(VisualJobsTests):
    def test_different_questions_do_not_reuse_interpretation(self):
        from aura_bio.study.visual.jobs import VisualJobs
        from aura_bio.study.attachments import question_hash
        fake = FakeDescriber()
        jobs = VisualJobs(self.store, describer=fake)
        for question in ['What is A?', 'What is B?']:
            jobs.start(self.pack.pack_id, [self.figure.figure_id], VisualJobConfig(question=question))
            jobs.run_once()
        self.assertEqual(fake.calls, 2)
        active = [u for u in self.store.units(self.pack.pack_id, self.doc.document_id) if u.provenance == 'vlm']
        self.assertEqual(active[0].provenance_details['question_hash'], question_hash('What is B?'))
