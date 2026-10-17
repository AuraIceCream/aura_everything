from test_study_api import StudyApiTests
from test_attachments import png


class AttachmentApiTests(StudyApiTests):
    def test_temporary_image_cannot_accept_a_second_document(self):
        item=self.client.post('/api/v1/study-attachments',files={'file':('diagram.png',png().getvalue(),'image/png')}).json()
        result=self.client.post(f"/api/v1/study-packs/{item['attachment_id']}/documents",files={'file':('extra.txt',b'second source')})
        self.assertEqual(result.status_code,409)

    def test_bad_ttl_does_not_poison_service_initialization(self):
        import os
        from unittest.mock import patch
        from aura_bio.api.study_packs import shutdown_study
        shutdown_study()
        with patch.dict(os.environ,{'AURA_ATTACHMENT_TTL_SECONDS':'bad'}):
            self.assertEqual(self.client.post('/api/v1/study-attachments',files={'file':('diagram.png',png().getvalue(),'image/png')}).status_code,422)
        self.assertEqual(self.client.post('/api/v1/study-attachments',files={'file':('diagram.png',png().getvalue(),'image/png')}).status_code,202)
    def test_upload_is_private_hidden_and_no_model_runs(self):
        response = self.client.post('/api/v1/study-attachments', files={'file': ('diagram.png', png().getvalue(), 'image/png')})
        self.assertEqual(response.status_code, 202, response.text)
        item = response.json()
        self.assertFalse(item['usable'])
        self.assertEqual(self.client.get('/api/v1/study-packs').json()['packs'], [])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.get('/api/v1/study-attachments/' + item['attachment_id'], headers={'Origin': 'https://evil.invalid'}).status_code, 403)

    def test_expiry_denies_regular_source_route_save_then_delete_retained_refused(self):
        from aura_bio.api.study_packs import study_services
        item = self.client.post('/api/v1/study-attachments', files={'file': ('diagram.png', png().getvalue(), 'image/png')}).json()
        self.assertIn('attachment_id', item)
        id = item['attachment_id']
        store, _ = study_services()
        store.clock = lambda: item['pack']['expires_at']
        source = f"/api/v1/study-packs/{id}/documents/{item['document']['document_id']}/original"
        self.assertEqual(self.client.get(source).status_code, 410)
        self.assertEqual(self.client.post(f'/api/v1/study-attachments/{id}/save', json={'name': 'Too late'}).status_code, 410)

    def test_save_and_detach_never_delete_saved_pack(self):
        item = self.client.post('/api/v1/study-attachments', files={'file': ('diagram.png', png().getvalue(), 'image/png')}).json()
        self.assertIn('attachment_id', item)
        id = item['attachment_id']
        self.assertEqual(self.client.post(f'/api/v1/study-attachments/{id}/save', json={'name': 'Saved diagram'}).status_code, 200)
        result = self.client.request('DELETE', f'/api/v1/study-attachments/{id}', json={'confirmation': id})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.client.get('/api/v1/study-packs').json()['packs'][0]['name'], 'Saved diagram')
