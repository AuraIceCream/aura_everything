import json
import unittest
from dataclasses import replace
from unittest.mock import patch
import test_visual_storage as fixtures
from test_visual_jobs import FakeDescriber
from aura_bio.study.visual.jobs import VisualJobs
from aura_bio.study.visual.schema import VisualJobConfig,NormalizedBox
from aura_bio.study.schema import StudyError


class VisualRegressionTests(fixtures.VisualStorageTests):
    def test_crash_resumes_completed_figures_only(self):
        fake=FakeDescriber(); jobs=VisualJobs(self.store,describer=fake)
        extra=self.visual.add_crop(self.figure.figure_id,NormalizedBox(.2,.2,.8,.8))
        job=jobs.start(self.pack.pack_id,[self.figure.figure_id,extra.figure_id],VisualJobConfig())
        original=fake.describe
        def first(input,**kwargs):
            result=original(input,**kwargs)
            if fake.calls==1: jobs.stopping.set()
            return result
        fake.describe=first; jobs.run_once(); jobs.recover()
        raw,_,_=self.visual.job_data(job.job_id)
        jobs.stopping.clear(); fake.describe=original
        jobs.resume(job.job_id,VisualJobConfig(**raw)); jobs.run_once()
        self.assertEqual(fake.calls,2)
        self.assertEqual(self.store.job(job.job_id).state,'completed')

    def test_prompt_change_requires_new_job(self):
        jobs=VisualJobs(self.store,describer=FakeDescriber()); job=jobs.start(self.pack.pack_id,[self.figure.figure_id],VisualJobConfig())
        jobs.pause(job.job_id); raw,_,_=self.visual.job_data(job.job_id)
        with patch('aura_bio.study.visual.description.PROMPT_HASH','new-prompt'):
            with self.assertRaises(StudyError): jobs.resume(job.job_id,VisualJobConfig(**raw))

    def test_cancel_during_inference_rejects_late_publication(self):
        fake=FakeDescriber(); jobs=VisualJobs(self.store,describer=fake); job=jobs.start(self.pack.pack_id,[self.figure.figure_id],VisualJobConfig())
        original=fake.describe
        def cancelled(input,**kwargs):
            result=original(input,**kwargs); jobs.cancel(job.job_id); return result
        fake.describe=cancelled; jobs.run_once()
        self.assertEqual(self.visual.revisions(self.figure.figure_id),[])
        self.assertEqual(self.store.job(job.job_id).state,'cancelled')

    def test_rate_limit_pauses_and_retains_attempts(self):
        class Limited:
            def describe(self,*args,**kwargs):
                error=StudyError('rate_limited','Paused for rate limit.'); error.resume_at=10**12; raise error
        jobs=VisualJobs(self.store,describer=Limited()); job=jobs.start(self.pack.pack_id,[self.figure.figure_id],VisualJobConfig())
        jobs.run_once(); raw,_,_=self.visual.job_data(job.job_id)
        self.assertEqual(self.store.job(job.job_id).state,'paused')
        with self.assertRaises(StudyError): jobs.resume(job.job_id,VisualJobConfig(**raw))

    def test_identical_pixels_and_hints_reuse_call_keep_occurrences(self):
        figures=[self.visual.add_crop(self.figure.figure_id,NormalizedBox(n/4,0,(n+1)/4,1)) for n in range(4)]
        fake=FakeDescriber(); jobs=VisualJobs(self.store,describer=fake)
        job=jobs.start(self.pack.pack_id,[f.figure_id for f in figures],VisualJobConfig())
        jobs.run_once()
        self.assertEqual(fake.calls,1)
        self.assertEqual(len({cp.revision_id for cp in self.visual.checkpoints(job.job_id)}),4)

    def test_deactivation_keeps_historical_revision_readable(self):
        revision=self.visual.publish_revision(self.revision(),expected_source_hash=self.figure.checksum)
        self.store.deactivate(self.pack.pack_id,self.doc.document_id)
        self.assertEqual(self.visual.revision(revision).text,'A activates B')

    def test_unreadable_asset_selection_reports_visible_warning(self):
        with patch.object(self.visual,'rendered_asset',side_effect=StudyError('source_changed','Checksum mismatch')):
            self.visual.figures(self.doc.document_id)
        self.assertTrue(self.visual.discovery_warnings)
        self.assertIn('source_changed',self.visual.discovery_warnings[0])

    def test_revision_uses_exact_figure_locator_and_only_its_asset(self):
        from aura_bio.study.schema import Locator
        draft=replace(self.revision(),locators=(Locator('pptx',slide=99),),asset_ids=('e'*32,self.figure.asset_id))
        revision=self.visual.publish_revision(draft,expected_source_hash=self.figure.checksum)
        saved=self.visual.revision(revision)
        self.assertEqual([loc.as_dict() for loc in saved.locators],[self.figure.locator])
        self.assertEqual(saved.asset_ids,(self.figure.asset_id,))

    def test_unreadable_asset_selection_reports_visible_warning(self):
        with patch.object(self.visual,'rendered_asset',side_effect=StudyError('source_changed','Checksum mismatch')):
            self.visual.figures(self.doc.document_id)
        self.assertTrue(self.visual.discovery_warnings)
        self.assertIn('source_changed',self.visual.discovery_warnings[0])
