import io
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from aura_bio.api.app import app, _RUNS, _RUN_ORDER


class StudyApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'AURA_STUDY_ROOT': self.tmp.name,
            'AURA_GENERATOR': 'extractive', 'AURA_NLI': 'off', 'AURA_RERANK': '0',
            'AURA_STUDY_RERANK':'0','AURA_STUDY_INDEX_MODE': 'sparse'})
        self.env.start()
        self.core = patch('aura_bio.api.app.get_runtime', side_effect=AssertionError('core runtime opened'))
        self.core.start()
        self.client = TestClient(app)

    def tearDown(self):
        from aura_bio.api.study_packs import shutdown_study
        shutdown_study()
        _RUNS.clear(); _RUN_ORDER.clear()
        self.core.stop(); self.env.stop(); self.tmp.cleanup()

    def pack(self):
        response = self.client.post('/api/v1/study-packs', json={'name': 'Private course'})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['pack_id']

    def ready(self, pack):
        response = self.client.post(f'/api/v1/study-packs/{pack}/documents',
            files={'file': ('lesson.md', b'# ORION\nORION is the fictional calibration label.\n', 'text/markdown')})
        self.assertEqual(response.status_code, 202, response.text)
        from aura_bio.api.study_packs import study_services
        store, jobs = study_services()
        self.assertTrue(jobs.run_once())
        self.assertIn(store.get_pack(pack).state,{'sparse-ready','hybrid-ready'},
                      [(job.state,job.error) for job in store.jobs(pack)])
        return response.json()['document']['document_id']

    def test_upload_preview_and_private_answer_without_core_runtime(self):
        pack = self.pack(); doc = self.ready(pack)
        base = f'/api/v1/study-packs/{pack}/documents/{doc}'
        units = self.client.get(base + '/units').json()['units']
        self.assertIn('ORION', self.client.get(base + '/units/' + units[0]['unit_id']).json()['text'])
        self.assertEqual(self.client.get(base + '/original').content, b'# ORION\nORION is the fictional calibration label.\n')
        search = self.client.post(f'/api/v1/study-packs/{pack}/search', json={'query': 'ORION', 'mode': 'hybrid'})
        self.assertEqual(search.json()['mode'], 'sparse')
        run = self.client.post('/api/v1/runs', json={'query': 'What is ORION?', 'evidence_scope': 'pack_only', 'pack_id': pack})
        self.assertEqual(run.status_code, 202, run.text)
        data = self.client.get('/api/v1/runs/' + run.json()['run_id']).json()
        self.assertIn('ORION', data['answer']['markdown'])
        self.assertEqual(data['answer']['citations'][0]['pack_id'], pack)
        self.assertTrue((__import__('pathlib').Path(self.tmp.name) / pack / 'traces').is_dir())

    def test_contract_fixture_does_not_inherit_a_live_study_reranker(self):
        pack=self.pack();self.ready(pack)
        with patch('aura_bio.study.reranking._load_scorer',side_effect=AssertionError('Contract fixture loaded a live reranker')) as loader:
            response=self.client.post(f'/api/v1/study-packs/{pack}/search',json={'query':'ORION','mode':'hybrid'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(loader.call_count,0,'API contract fixtures must not load external model weights.')

    def test_empty_pack_invalid_scope_and_foreign_origin(self):
        pack = self.pack()
        self.assertEqual(self.client.post('/api/v1/runs', json={'query': 'ORION?', 'evidence_scope': 'pack_only', 'pack_id': pack}).status_code, 409)
        self.assertEqual(self.client.post('/api/v1/runs', json={'query': 'ORION?', 'evidence_scope': 'pack_only'}).status_code, 422)
        self.assertEqual(self.client.get('/api/v1/study-packs', headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/v1/study-packs', headers={'Origin': 'http://localhost:5173'}).status_code, 200)

    def test_thinking_is_request_scoped_and_preserved_in_generation_metadata(self):
        import json
        from aura_bio.api.study_packs import study_services
        from aura_bio.study.runtime import build_pack_pipeline
        pack = self.pack(); self.ready(pack)
        store,_ = study_services()
        class Reply:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self):
                draft={'version':1,'claims':[{'id':'c1','claim':'ORION is the fictional calibration label.',
                                             'cite_ids':[1],'depends_on':[]}],
                       'blocks':[{'type':'claim','ref':'c1'}]}
                return json.dumps({'message':{'content':json.dumps(draft)},'done_reason':'stop',
                                   'models':[]}).encode()
        with patch.dict(os.environ,{'AURA_GENERATOR':'ollama'}), \
                patch('aura_bio.api.generation.OllamaGenerator.available',return_value=True), \
                patch('urllib.request.urlopen',return_value=Reply()) as transport:
            pipeline = build_pack_pipeline(store,pack,think=True)
            try:
                pipeline.answer('What is ORION?',use_critic=False)
                chats = [call.args[0] for call in transport.call_args_list
                         if call.args[0].full_url.endswith('/api/chat')]
                payload = json.loads(chats[-1].data)
                self.assertTrue(payload['think'])
                self.assertGreaterEqual(payload['options']['num_predict'],4096)
                self.assertTrue(pipeline.generator.last_metadata['think'])
            finally:
                pipeline.searcher.close(); pipeline.store.close()
            normal = build_pack_pipeline(store,pack)
            try: self.assertFalse(normal.generator.think)
            finally: normal.searcher.close(); normal.store.close()

    def test_document_visual_answer_never_falls_back_when_selected_model_is_missing(self):
        from aura_bio.api.study_packs import study_services
        from aura_bio.study.runtime import build_pack_pipeline
        from aura_bio.study.schema import StudyError
        pack=self.pack();self.ready(pack);store,_=study_services()
        with patch.dict(os.environ,{'AURA_GENERATOR':'ollama'}), \
                patch('aura_bio.study.visual.ollama.OllamaVisionBackend._request',return_value={'models':[]}):
            with self.assertRaises(StudyError) as error:
                build_pack_pipeline(store,pack,require_model=True)
            self.assertEqual(error.exception.code,'model_unavailable')

    def test_pack_answer_mode_defaults_to_tutor_and_rejects_unknown_modes(self):
        from pydantic import ValidationError
        from aura_bio.api.app import RunRequestModel
        fields={'query':'What is ORION?','evidence_scope':'pack_only','pack_id':'a'*32}
        self.assertEqual(RunRequestModel(**fields).answer_mode,'tutor')
        self.assertEqual(RunRequestModel(**fields,answer_mode='strict').answer_mode,'strict')
        with self.assertRaises(ValidationError): RunRequestModel(**fields,answer_mode='unchecked')

    def test_visual_answer_releases_its_model_for_the_next_explicit_image_request(self):
        from aura_bio.api.study_packs import study_services
        from aura_bio.study.runtime import build_pack_pipeline
        pack=self.pack();self.ready(pack);store,_=study_services()
        with patch.dict(os.environ,{'AURA_GENERATOR':'ollama','AURA_OLLAMA_MODEL':'fixture-vision'}), \
                patch('aura_bio.study.visual.ollama.OllamaVisionBackend._request',return_value={'models':[{'name':'fixture-vision'}]}), \
                patch('aura_bio.study.visual.ollama.gpu_free_mb',return_value=(4000,4096,0)):
            pipeline=build_pack_pipeline(store,pack,require_model=True)
            try:
                self.assertEqual(pipeline.generator.keep_alive,0)
                self.assertTrue(pipeline.generator.strict_no_fallback)
            finally: pipeline.searcher.close();pipeline.store.close()

    def test_visual_answer_accepts_idle_selected_model_already_loaded(self):
        from aura_bio.api.study_packs import study_services
        from aura_bio.study.runtime import build_pack_pipeline
        pack=self.pack();self.ready(pack);store,_=study_services()
        def ollama_state(method,path,**kwargs):
            return {'models':[{'name':'fixture-vision'}]}
        with patch.dict(os.environ,{'AURA_GENERATOR':'ollama','AURA_OLLAMA_MODEL':'fixture-vision'}), \
                patch('aura_bio.study.visual.ollama.OllamaVisionBackend._request',side_effect=ollama_state), \
                patch('aura_bio.study.visual.ollama.gpu_free_mb',return_value=(170,4096,0)):
            pipeline=build_pack_pipeline(store,pack,require_model=True)
            try: self.assertEqual(pipeline.generator.model_name,'fixture-vision')
            finally: pipeline.searcher.close();pipeline.store.close()

    def test_visual_answer_survives_repeated_model_loads_on_small_gpu(self):
        import json
        from urllib.error import HTTPError
        from aura_bio.api.study_packs import study_services
        from aura_bio.study.runtime import build_pack_pipeline
        pack=self.pack();self.ready(pack);store,_=study_services()
        class Reply:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return b'{"message":{"content":"ORION is the calibration label. [1]"},"done_reason":"stop","models":[]}'
        def constrained_gpu(request, timeout=None):
            if request.full_url.endswith('/api/ps'):
                return Reply()
            options=json.loads(request.data)['options']
            if options.get('num_batch',512)>64:
                raise HTTPError(request.full_url,500,'model allocation failed',None,None)
            return Reply()
        with patch.dict(os.environ,{'AURA_GENERATOR':'ollama','AURA_OLLAMA_MODEL':'fixture-vision'}), \
                patch('aura_bio.study.visual.ollama.OllamaVisionBackend._request',return_value={'models':[{'name':'fixture-vision'}]}), \
                patch('aura_bio.study.visual.ollama.gpu_free_mb',return_value=(4000,4096,0)), \
                patch('urllib.request.urlopen',side_effect=constrained_gpu):
            pipeline=build_pack_pipeline(store,pack,require_model=True)
            try:
                route=pipeline.router.route('What is ORION?')
                for _ in range(2):
                    self.assertIn('ORION',pipeline.generator.generate(route,[],()))
            finally: pipeline.searcher.close();pipeline.store.close()

    def test_claim_first_text_answer_uses_same_bounded_batch_as_figure_answer(self):
        from aura_bio.api.study_packs import study_services
        from aura_bio.study.runtime import build_pack_pipeline
        pack=self.pack();self.ready(pack);store,_=study_services()
        with patch.dict(os.environ,{'AURA_GENERATOR':'ollama'}), \
                patch('aura_bio.api.generation.OllamaGenerator.available',return_value=True):
            pipeline=build_pack_pipeline(store,pack)
            try: self.assertEqual(pipeline.generator.num_batch,64)
            finally: pipeline.searcher.close();pipeline.store.close()

    def test_explicit_nli_off_is_a_factory_policy_not_a_cache_load_hint(self):
        from aura_bio.api.study_packs import study_services
        from aura_bio.study.runtime import build_pack_pipeline
        pack = self.pack(); self.ready(pack)
        store, _ = study_services()
        with store.lease(pack):
            pipeline = build_pack_pipeline(store, pack)
            try:
                self.assertFalse(pipeline.verifier.use_entailment)
            finally:
                pipeline.searcher.close(); pipeline.store.close()

    def test_default_reranker_failure_is_visible_in_search_and_answer_trace(self):
        from aura_bio.api.study_packs import study_services
        from aura_bio.study.runtime import build_pack_pipeline
        pack = self.pack(); self.ready(pack)
        store, _ = study_services()
        with patch.dict(os.environ, {'AURA_STUDY_RERANK': '1'}), \
                patch('aura_bio.study.reranking.cached_scorer', side_effect=OSError('not cached')):
            response = self.client.post(f'/api/v1/study-packs/{pack}/search', json={'query': 'ORION'})
            data = response.json()
            self.assertEqual(data['mode'], 'sparse')
            self.assertIsNone(data['rerank'])
            self.assertTrue(any('reranker unavailable' in warning for warning in data['warnings']))
            pipeline = build_pack_pipeline(store, pack)
            try:
                answer = pipeline.answer('What is ORION?', use_critic=False)
                self.assertTrue(any('reranker unavailable' in warning for warning in answer.trace.retrieval['warnings']))
                self.assertIsNone(answer.trace.retrieval['stages']['reranker_model'])
            finally:
                pipeline.searcher.close(); pipeline.store.close()

    def test_pending_cleanup_detail_survives_missing_metadata_and_retains_target(self):
        from pathlib import Path
        from aura_bio.api.study_packs import study_services, shutdown_study
        pack = self.pack(); self.ready(pack)
        folder = Path(self.tmp.name) / pack
        def partial_remove(path):
            (folder / 'metadata.sqlite3').unlink()
            raise PermissionError('open viewer')
        with patch('aura_bio.study.storage.shutil.rmtree', side_effect=partial_remove):
            response = self.client.request('DELETE', f'/api/v1/study-packs/{pack}', json={'confirmation': pack})
        self.assertEqual(response.status_code, 409)
        shutdown_study()
        with self.client:
            detail = self.client.get(f'/api/v1/study-packs/{pack}')
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertEqual(detail.json()['documents'], [])
            self.assertIsNone(detail.json()['pending_purge']['document_id'])
            self.assertFalse((folder / 'metadata.sqlite3').exists())
            response = self.client.request('DELETE', f'/api/v1/study-packs/{pack}', json={'confirmation': pack})
            self.assertTrue(response.json()['deleted'])

        # A deleted document row must not force permission to delete the entire pack.
        pack = self.pack(); doc = self.ready(pack)
        with patch('aura_bio.study.storage.shutil.rmtree', side_effect=PermissionError('open viewer')):
            response = self.client.request('DELETE', f'/api/v1/study-packs/{pack}/documents/{doc}', json={'confirmation': doc})
        self.assertEqual(response.status_code, 409)
        detail = self.client.get(f'/api/v1/study-packs/{pack}').json()
        self.assertEqual(detail['pending_purge']['document_id'], doc)
        response = self.client.request('DELETE', f'/api/v1/study-packs/{pack}/documents/{doc}', json={'confirmation': doc})
        self.assertTrue(response.json()['deleted'])

    def test_unknown_pack_limits_formats_and_http_errors_are_preserved(self):
        pack = self.pack()
        self.assertEqual(self.client.post('/api/v1/runs', json={'query': 'Lesson?', 'evidence_scope': 'pack_only', 'pack_id': 'f' * 32}).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/study-packs/bad').status_code, 422)
        url = f'/api/v1/study-packs/{pack}/documents'
        self.assertEqual(self.client.post(url, files={'file': ('x.docx', b'not supported')}).status_code, 415)
        self.assertEqual(self.client.post(url, files={'file': ('x.pdf', b'not pdf')}).status_code, 422)
        self.assertEqual(self.client.post(url, content=b'', headers={'Content-Length': str(52 * 1024 * 1024)}).status_code, 413)

    def test_sse_holds_a_purge_lease_until_closed(self):
        import asyncio
        import threading
        from fastapi import Request
        from aura_bio.api.app import run_events
        pack = self.pack(); self.ready(pack)
        run_id = self.client.post('/api/v1/runs', json={'query': 'What is ORION?', 'evidence_scope': 'pack_only', 'pack_id': pack}).json()['run_id']
        completed = threading.Event()
        def purge():
            self.client.request('DELETE', f'/api/v1/study-packs/{pack}', json={'confirmation': pack})
            completed.set()
        async def replay():
            response = await run_events(run_id, Request({'type': 'http', 'headers': []}))
            await anext(response.body_iterator)
            thread = threading.Thread(target=purge); thread.start()
            from aura_bio.api.study_packs import study_services
            store, _ = study_services()
            with store.condition:
                self.assertTrue(store.condition.wait_for(lambda: pack in store.blocked, timeout=2))
            self.assertFalse(completed.is_set())
            await response.body_iterator.aclose()
            thread.join(5)
            self.assertTrue(completed.is_set())
        asyncio.run(replay())
        self.assertEqual(self.client.get('/api/v1/runs/' + run_id).status_code, 404)

    def test_cross_site_navigation_without_origin_cannot_read_private_data(self):
        self.assertEqual(self.client.get('/api/v1/study-packs', headers={'Sec-Fetch-Site': 'cross-site'}).status_code, 403)

    def test_confirmed_purge_forgets_runs_and_blocks_cross_pack_preview(self):
        pack = self.pack(); doc = self.ready(pack); other = self.pack()
        self.assertEqual(self.client.get(f'/api/v1/study-packs/{other}/documents/{doc}/original').status_code, 404)
        run = self.client.post('/api/v1/runs', json={'query': 'What is ORION?', 'evidence_scope': 'pack_only', 'pack_id': pack}).json()['run_id']
        self.assertEqual(self.client.get('/api/v1/runs/' + run, headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.request('DELETE', f'/api/v1/study-packs/{pack}', json={'confirmation': 'no'}).status_code, 422)
        response = self.client.request('DELETE', f'/api/v1/study-packs/{pack}', json={'confirmation': pack})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get('/api/v1/runs/' + run).status_code, 404)
