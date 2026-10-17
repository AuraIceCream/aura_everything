from test_study_api import StudyApiTests
from test_attachments import png
from test_visual_jobs import FakeDescriber


class AttachmentEndToEndTests(StudyApiTests):
    def test_new_question_on_manual_crop_is_indexed_without_old_question_leakage(self):
        from aura_bio.api.study_packs import study_services,attachment_services
        from aura_bio.study.visual.storage import VisualStore
        from aura_bio.study.visual.jobs import VisualJobs
        from aura_bio.study.visual.schema import VisualJobConfig,NormalizedBox
        from aura_bio.study.indexing import StudyIndexer
        from aura_bio.study.searcher import StudySearcher
        item=self.prepared('What is A?');pack=item['attachment_id'];store,_=study_services()
        visual=VisualStore(store,pack);original=visual.figures(item['document']['document_id'])[0]
        crop=visual.add_crop(original.figure_id,NormalizedBox(.1,.1,.9,.9))
        jobs=VisualJobs(store,describer=FakeDescriber(),indexer=lambda id:StudyIndexer(store).build(id))
        jobs.start(pack,[crop.figure_id],VisualJobConfig(question='What is B?'));jobs.run_once()
        self.assertTrue(attachment_services().indexed_for(pack,'What is B?'))
        with StudySearcher(store,pack) as searcher:
            hits=searcher.search('A B',8,30)
            self.assertTrue(hits)
            self.assertTrue(all(len(h.unit_ids)==1 for h in hits if h.provenance=='vlm'))
    def test_visual_pass_cannot_start_inside_an_image_answer(self):
        from unittest.mock import patch
        from aura_bio.api.study_packs import study_services
        from aura_bio.study.visual.jobs import VisualJobs
        from aura_bio.study.visual.storage import VisualStore
        from aura_bio.study.visual.schema import VisualJobConfig
        from aura_bio.study.schema import StudyError
        item=self.prepared();id=item['attachment_id'];store,_=study_services()
        figure=VisualStore(store,id).figures(item['document']['document_id'])[0]
        jobs=VisualJobs(store,describer=FakeDescriber())
        paused=jobs.start(id,[figure.figure_id],VisualJobConfig());jobs.pause(paused.job_id)
        def answer(request):
            with self.assertRaises(StudyError) as error:
                VisualJobs(store,describer=FakeDescriber()).start(id,[figure.figure_id],VisualJobConfig())
            self.assertEqual(error.exception.code,'busy_gpu')
            with self.assertRaises(StudyError) as error:
                jobs.resume(paused.job_id,VisualJobConfig())
            self.assertEqual(error.exception.code,'busy_gpu')
            return {'decision':'degraded','events':[],'answer_payload':{'markdown':'Interpreted'},'created_at':'now','summary':{}}
        with patch('aura_bio.api.app._execute',side_effect=answer):
            result=self.client.post('/api/v1/runs',json={'query':'What is ORION?','evidence_scope':'pack_only','pack_id':id,'attachment_id':id})
        self.assertEqual(result.status_code,202,result.text)

    def prepared(self, question='What is ORION?'):
        from aura_bio.api.study_packs import study_services
        from aura_bio.study.visual.jobs import VisualJobs
        from aura_bio.study.visual.storage import VisualStore
        from aura_bio.study.visual.schema import VisualJobConfig
        from aura_bio.study.indexing import StudyIndexer
        item=self.client.post('/api/v1/study-attachments',files={'file':('diagram.png',png().getvalue(),'image/png')}).json()
        store,worker=study_services();worker.run_once()
        visual=VisualStore(store,item['attachment_id'])
        figure=visual.figures(item['document']['document_id'])[0]
        jobs=VisualJobs(store,describer=FakeDescriber(),indexer=lambda id:StudyIndexer(store).build(id))
        jobs.start(item['attachment_id'],[figure.figure_id],VisualJobConfig(question=question));jobs.run_once()
        return item

    def test_real_image_intake_fake_vision_context_citations_and_save(self):
        item=self.prepared();id=item['attachment_id'];context=self.pack();self.ready(context)
        response=self.client.post('/api/v1/runs',json={'query':'What is ORION?','evidence_scope':'pack_only','pack_id':id,'attachment_id':id,'context_pack_id':context})
        self.assertEqual(response.status_code,202,response.text)
        run=self.client.get('/api/v1/runs/'+response.json()['run_id']).json()
        self.assertEqual(set(run['source_pack_ids']),{id,context})
        citations=run['answer']['citations'];self.assertEqual({c['pack_id'] for c in citations},{id,context})
        self.assertTrue(any(c['provenance']=='vlm' for c in citations))
        self.assertNotEqual(run['answer'].get('decision'),'verified')
        saved=self.client.post(f'/api/v1/study-attachments/{id}/save',json={'name':'Retained diagram'})
        self.assertEqual(saved.json()['pack_id'],id)
        self.assertEqual(self.client.get('/api/v1/runs/'+response.json()['run_id']).status_code,200)
        self.assertEqual(self.client.request('DELETE',f'/api/v1/study-attachments/{id}',json={'confirmation':id}).status_code,409)

    def test_different_question_cannot_reuse_focused_description(self):
        item=self.prepared('What is A?');id=item['attachment_id']
        result=self.client.post('/api/v1/runs',json={'query':'What is B?','evidence_scope':'pack_only','pack_id':id,'attachment_id':id})
        self.assertEqual(result.status_code,409,result.text)

    def test_pending_reindex_cannot_claim_new_interpretations_are_ready(self):
        from aura_bio.api.study_packs import study_services
        item=self.prepared();id=item['attachment_id'];store,_=study_services()
        store.enqueue(id,kind='index')
        self.assertFalse(self.client.get('/api/v1/study-attachments/'+id).json()['usable'])
        result=self.client.post('/api/v1/runs',json={'query':'What is ORION?','evidence_scope':'pack_only','pack_id':id,'attachment_id':id})
        self.assertEqual(result.status_code,409)

    def test_stream_expiry_stops_deltas_and_releases_source_leases(self):
        import asyncio,json
        from fastapi import Request
        from aura_bio.api.app import run_events,_RUNS
        from aura_bio.api.study_packs import study_services
        item=self.prepared();id=item['attachment_id'];context=self.pack();self.ready(context)
        run=self.client.post('/api/v1/runs',json={'query':'What is ORION?','evidence_scope':'pack_only','pack_id':id,'attachment_id':id,'context_pack_id':context}).json()['run_id']
        store,_=study_services()
        async def replay():
            response=await run_events(run,Request({'type':'http','headers':[]}))
            await anext(response.body_iterator)
            store.clock=lambda:item['pack']['expires_at']
            stopped=await anext(response.body_iterator)
            self.assertEqual(json.loads(stopped[6:])['type'],'run.invalidated')
            await response.body_iterator.aclose()
        asyncio.run(replay());self.assertNotIn(run,_RUNS)
        self.assertTrue(store.purge(id,confirmation=id,wait_seconds=0).deleted)
        self.assertEqual(self.client.get('/api/v1/study-packs/'+context).status_code,200)
