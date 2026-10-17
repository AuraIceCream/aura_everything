import json
import unittest
from dataclasses import replace
from test_visual_storage import VisualStorageTests
from test_figure_description import Backend, FIELDS
from aura_bio.study.visual.description import FigureDescriber
from aura_bio.study.visual.jobs import VisualJobs
from aura_bio.study.visual.schema import VisualJobConfig
from aura_bio.study.schema import StudyError


class FocusIntegrationTests(VisualStorageTests):
    def test_explicit_focus_keeps_question_caption_and_owned_region(self):
        figure=replace(self.figure,caption='Fig. 5 | A source caption.')
        with self.store.db(self.pack.pack_id) as db:
            from dataclasses import asdict
            db.execute('UPDATE visual_figures SET payload=? WHERE figure_id=?',
                       (json.dumps(asdict(figure)),figure.figure_id))
        value={**FIELDS,'version':2,'panels':[],'tables':[]}
        backend=Backend([json.dumps(value)])
        jobs=VisualJobs(self.store,describer=FigureDescriber(backend))
        question='Explain this image without inventing invisible labels'
        job=jobs.start(self.pack.pack_id,[figure.figure_id],VisualJobConfig(
            description_version=2,focus=True,question=question))
        self.assertEqual(backend.calls,0)
        jobs.run_once()
        self.assertEqual(self.store.job(job.job_id).state,'completed')
        revision=self.visual.revision(self.visual.checkpoints(job.job_id)[0].revision_id)
        self.assertIn('focus_reads',revision.metadata)
        self.assertEqual(revision.metadata['focus_reads'][0]['region']['figure_id'],figure.figure_id)
        self.assertIn('whole_figure',revision.metadata['focus_warnings'][0])
        self.assertEqual(revision.provenance,'vlm')
        self.assertFalse(revision.provenance_details['numbers_verified'])

    def test_focus_revision_not_usable_before_indexing(self):
        import sqlite3
        value={**FIELDS,'version':2,'panels':[],'tables':[]}
        jobs=VisualJobs(self.store,describer=FigureDescriber(Backend([json.dumps(value)])))
        job=jobs.start(self.pack.pack_id,[self.figure.figure_id],VisualJobConfig(
            description_version=2,focus=True,question='What is this image?'))
        jobs.run_once()
        connection=sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.execute('CREATE TABLE chunks(payload TEXT)')
        with self.assertRaises(StudyError):
            self.visual.indexed_units([self.figure.figure_id],question='What is this image?',connection=connection)

    def test_focus_cache_does_not_reuse_another_crop_identity(self):
        from aura_bio.study.visual.schema import NormalizedBox
        first=self.visual.add_crop(self.figure.figure_id,NormalizedBox(0,0,.5,1))
        second=self.visual.add_crop(self.figure.figure_id,NormalizedBox(.5,0,1,1))
        value={**FIELDS,'version':2,'panels':[],'tables':[]}
        backend=Backend([json.dumps(value),json.dumps(value)])
        jobs=VisualJobs(self.store,describer=FigureDescriber(backend))
        config=VisualJobConfig(description_version=2,focus=True,question='What is this image?')
        for figure in (first,second):
            job=jobs.start(self.pack.pack_id,[figure.figure_id],config);jobs.run_once()
            revision=self.visual.revision(self.visual.checkpoints(job.job_id)[0].revision_id)
            self.assertEqual(revision.metadata['focus_reads'][0]['region']['figure_id'],figure.figure_id)

    def test_purge_during_focused_read_never_publishes_revision(self):
        value={**FIELDS,'version':2,'panels':[],'tables':[]}
        store,pack,doc=self.store,self.pack.pack_id,self.doc.document_id
        class PurgingBackend(Backend):
            def complete(inner,*args,**kwargs):
                response=super().complete(*args,**kwargs)
                store.purge(pack,doc,confirmation=doc)
                return response
        jobs=VisualJobs(self.store,describer=FigureDescriber(PurgingBackend([json.dumps(value)])))
        jobs.start(pack,[self.figure.figure_id],VisualJobConfig(description_version=2,focus=True,question='What is this image?'))
        jobs.run_once()
        with self.assertRaises(StudyError): self.visual.figure(self.figure.figure_id)


if __name__=='__main__': unittest.main()
