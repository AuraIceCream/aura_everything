from unittest.mock import patch
from test_study_api import StudyApiTests
from test_attachments import png


class AttachmentRunsTests(StudyApiTests):
    def test_context_without_image_or_core_with_image_is_rejected(self):
        for body in [{'query': 'ORION', 'context_pack_id': '1' * 32},
                     {'query': 'ORION', 'attachment_id': '1' * 32}]:
            self.assertEqual(self.client.post('/api/v1/runs', json=body).status_code, 422)

    def test_empty_attachment_cannot_be_answered_from_context_alone(self):
        item = self.client.post('/api/v1/study-attachments', files={'file': ('diagram.png', png().getvalue(), 'image/png')}).json()
        context = self.pack()
        self.ready(context)
        body = {'query': 'ORION', 'evidence_scope': 'pack_only', 'pack_id': item['attachment_id'],
                'attachment_id': item['attachment_id'], 'context_pack_id': context}
        self.assertEqual(self.client.post('/api/v1/runs', json=body).status_code, 409)

    def test_context_purge_invalidates_dependent_run_without_deleting_image(self):
        from aura_bio.api.app import _RUNS, _RUN_ORDER, forget_pack_runs
        image = self.pack()
        context = self.pack()
        _RUNS['run-dependent'] = {'request': {'pack_id': image}, 'source_pack_ids': [image, context]}
        _RUN_ORDER.append('run-dependent')
        forget_pack_runs(context)
        self.assertNotIn('run-dependent', _RUNS)
        self.assertEqual(self.client.get('/api/v1/study-packs/' + image).status_code, 200)

    def test_expiry_after_generation_prevents_cache_publication(self):
        from aura_bio.api.app import _RUNS
        from aura_bio.api.study_packs import study_services
        item = self.client.post('/api/v1/study-attachments', files={'file': ('diagram.png', png().getvalue(), 'image/png')}).json()
        id = item['attachment_id']
        store, _ = study_services()
        from dataclasses import replace
        store.update_pack(replace(store.get_pack(id), state='sparse-ready'))
        def expire(request):
            store.clock = lambda: item['pack']['expires_at']
            return {'decision': 'accept', 'events': [], 'answer_payload': {'markdown': 'Never publish this'}, 'created_at': 'now', 'summary': {}}
        with patch('aura_bio.api.app._execute', side_effect=expire), patch('aura_bio.study.attachments.AttachmentService.indexed_for', return_value=True):
            result = self.client.post('/api/v1/runs', json={'query': 'Arrow?', 'evidence_scope': 'pack_only', 'pack_id': id, 'attachment_id': id})
        self.assertEqual(result.status_code, 410)
        self.assertEqual(_RUNS, {})

    def test_active_visual_job_blocks_answer_even_with_an_existing_index(self):
        from aura_bio.api.study_packs import study_services
        from dataclasses import replace
        item = self.client.post('/api/v1/study-attachments', files={'file': ('diagram.png', png().getvalue(), 'image/png')}).json()
        store, _ = study_services(); id = item['attachment_id']
        store.update_pack(replace(store.get_pack(id), state='sparse-ready'))
        store.enqueue(id, kind='visual')
        with patch('aura_bio.study.attachments.AttachmentService.indexed_for', return_value=True), patch('aura_bio.api.app._execute') as execute:
            response=self.client.post('/api/v1/runs', json={'query':'Arrow?', 'evidence_scope':'pack_only','pack_id':id,'attachment_id':id})
        self.assertEqual(response.status_code,409);execute.assert_not_called()

    def test_private_trace_write_rechecks_lifetime(self):
        from aura_bio.study.runtime import PrivateTraceStore
        from aura_bio.api.study_packs import study_services
        from aura_bio.tracing import Trace
        from aura_bio.study.schema import StudyError
        from pathlib import Path
        item=self.client.post('/api/v1/study-attachments',files={'file':('diagram.png',png().getvalue(),'image/png')}).json()
        store,_=study_services();id=item['attachment_id']
        traces=PrivateTraceStore(store,[id],Path(self.tmp.name)/id/'traces'/'fixture.sqlite3')
        store.clock=lambda:item['pack']['expires_at']
        try:
            with self.assertRaises(StudyError):traces.record(Trace(query='private'))
            self.assertEqual(traces.connection.execute('SELECT COUNT(*) FROM traces').fetchone()[0],0)
        finally:traces.close()
