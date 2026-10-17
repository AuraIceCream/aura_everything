import unittest
from dataclasses import replace
import test_visual_storage as fixtures
from aura_bio.study.visual.jobs import VisualJobs
from aura_bio.study.visual.schema import VisualJobConfig,FigureDescription,ProviderResponse
from aura_bio.study.schema import StudyError


class FakeDescriber:
    def __init__(self): self.calls=0
    def describe(self,input,**kwargs):
        self.calls+=1
        return FigureDescription({'kind':'pathway','labels':['A','B'],'axes':[],'relations':[], 'summary':'A activates B','uncertainties':[]},
                                 (ProviderResponse('{}','ollama',input.config.model),),'hash',input.config.checksum)


class VisualJobsTests(fixtures.VisualStorageTests):
    def test_upload_does_not_start_vlm(self):
        fake=FakeDescriber(); jobs=VisualJobs(self.store,describer=fake)
        self.assertFalse(jobs.run_once()); self.assertEqual(fake.calls,0)

    def test_explicit_job_checkpoint_and_restart(self):
        fake=FakeDescriber(); jobs=VisualJobs(self.store,describer=fake)
        job=jobs.start(self.pack.pack_id,[self.figure.figure_id],VisualJobConfig())
        self.assertTrue(jobs.run_once()); self.assertEqual(fake.calls,1)
        self.assertEqual(self.store.job(job.job_id).state,'completed')
        self.assertEqual(self.visual.checkpoints(job.job_id)[0].state,'completed')
        jobs.recover(); self.assertFalse(jobs.run_once()); self.assertEqual(fake.calls,1)

    def test_changed_digest_requires_new_job(self):
        jobs=VisualJobs(self.store,describer=FakeDescriber()); config=VisualJobConfig(model_digest='original')
        job=jobs.start(self.pack.pack_id,[self.figure.figure_id],config); jobs.pause(job.job_id)
        with self.assertRaises(StudyError): jobs.resume(job.job_id,replace(config,model_digest='changed'))

    def test_deactivate_cancels_queued_work(self):
        fake=FakeDescriber(); jobs=VisualJobs(self.store,describer=fake)
        job=jobs.start(self.pack.pack_id,[self.figure.figure_id],VisualJobConfig())
        self.store.deactivate(self.pack.pack_id,self.doc.document_id)
        self.assertFalse(jobs.run_once()); self.assertEqual(fake.calls,0)

    def test_purge_rejects_late_checkpoint(self):
        jobs=VisualJobs(self.store,describer=FakeDescriber()); job=jobs.start(self.pack.pack_id,[self.figure.figure_id],VisualJobConfig())
        checkpoint=self.visual.checkpoints(job.job_id)[0]
        self.store.purge(self.pack.pack_id,self.doc.document_id,confirmation=self.doc.document_id)
        with self.assertRaises(StudyError): self.visual.upsert_checkpoint(checkpoint)

    def test_ocr_job_can_exceed_180_seconds_total(self):
        from aura_bio.study.visual.schema import NormalizedBox,OcrResult
        elapsed=[0]
        class FakeOcr:
            def read(self,asset,**kwargs):
                elapsed[0]+=50
                return OcrResult('Value 7',(),'fake','eng','1',asset.transform)
        figures=[self.visual.add_crop(self.figure.figure_id,NormalizedBox(n/4,0,(n+1)/4,1)) for n in range(4)]
        jobs=VisualJobs(self.store,ocr=FakeOcr(),clock=lambda:elapsed[0])
        job=jobs.start(self.pack.pack_id,[f.figure_id for f in figures],VisualJobConfig(provider='ocr',model='eng'))
        jobs.run_once()
        self.assertEqual(elapsed[0],200)
        self.assertEqual(self.store.job(job.job_id).state,'completed')
        self.assertEqual(len(self.visual.checkpoints(job.job_id)),4)
