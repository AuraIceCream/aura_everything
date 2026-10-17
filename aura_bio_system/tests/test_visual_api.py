import io
import unittest
from PIL import Image
import test_study_api as fixtures


class VisualApiTests(fixtures.StudyApiTests):
    def test_completed_visual_job_is_not_ready_until_its_revision_is_indexed(self):
        from aura_bio.api.study_packs import study_services
        from aura_bio.api.study_visual import visual_services
        from aura_bio.study.visual.schema import VisualJobConfig
        from test_visual_jobs import FakeDescriber
        pack=self.pack(); self.ready(pack); doc,fig,_=self.figure(pack)
        jobs=visual_services(); jobs.describer=FakeDescriber()
        job=jobs.start(pack,[fig['figure_id']],VisualJobConfig(question='What is this?'))
        jobs.run_once()
        path=f'/api/v1/study-packs/{pack}/visual-jobs/{job.job_id}'
        first=self.client.get(path).json()
        self.assertEqual(first['state'],'completed')
        self.assertFalse(first['indexed'])
        request={'query':'What is this?','evidence_scope':'pack_only','pack_id':pack,'figure_ids':[fig['figure_id']]}
        early=self.client.post('/api/v1/runs',json=request)
        self.assertEqual(early.status_code,409,early.text)
        study_services()[1].run_once()
        self.assertTrue(self.client.get(path).json()['indexed'])
        ready=self.client.post('/api/v1/runs',json=request)
        self.assertEqual(ready.status_code,202,ready.text)

    def test_missing_caption_crop_never_substitutes_a_different_number(self):
        import tempfile
        from pathlib import Path
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        from aura_bio.api.study_packs import study_services
        pack=self.pack()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'two-figures.pdf'
            writer=PdfWriter(); page=writer.add_blank_page(width=600,height=800)
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
            stream=DecodedStreamObject()
            stream.set_data(b'BT /F1 12 Tf 40 600 Td (Fig. 5 | Target procedure.) Tj ET BT /F1 12 Tf 40 100 Td (Fig. 6 | Unrelated control.) Tj ET 50 130 200 170 re S')
            page[NameObject('/Contents')]=writer._add_object(stream); writer.write(path)
            self.client.post(f'/api/v1/study-packs/{pack}/documents',files={'file':('two-figures.pdf',path.read_bytes(),'application/pdf')})
        study_services()[1].run_once()
        response=self.client.post(f'/api/v1/study-packs/{pack}/visual-question',json={'question':'Explain Fig. 5'})
        self.assertEqual(response.status_code,422,response.text)

    def test_resolve_named_pdf_figure_without_running_vision(self):
        import tempfile
        from pathlib import Path
        from study_fixtures import pdf_fixture
        from aura_bio.api.study_packs import study_services
        from aura_bio.api.study_visual import visual_services
        from test_visual_jobs import FakeDescriber
        pack = self.pack()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'procedure.pdf'
            pdf_fixture(path, ('Intro refers to Fig. 5.', 'Fig. 5 | ORION wash procedure.'))
            upload = self.client.post(f'/api/v1/study-packs/{pack}/documents',files={'file':('procedure.pdf',path.read_bytes(),'application/pdf')})
        study_services()[1].run_once()
        fake = FakeDescriber(); visual_services().describer = fake
        response = self.client.post(f'/api/v1/study-packs/{pack}/visual-question',json={'question':'Explain the procedure in Fig. 5'})
        self.assertEqual(response.status_code,200,response.text)
        targets = response.json()['figures']
        self.assertEqual(len(targets),1)
        self.assertEqual(targets[0]['locator']['page'],2)
        self.assertEqual(targets[0]['figure_label'],'5')
        self.assertEqual(fake.calls,0)
        self.assertEqual(study_services()[0].document(pack, upload.json()['document']['document_id']).filename,'procedure.pdf')
        missing = self.client.post(f'/api/v1/study-packs/{pack}/visual-question',json={'question':'Explain Fig. 99'})
        self.assertEqual(missing.status_code,422,missing.text)

    def figure(self,pack):
        raw=io.BytesIO(); Image.new('RGB',(200,150),'white').save(raw,format='PNG')
        response=self.client.post(f'/api/v1/study-packs/{pack}/documents',files={'file':('figure.png',raw.getvalue(),'image/png')})
        self.assertEqual(response.status_code,202,response.text)
        from aura_bio.api.study_packs import study_services
        study_services()[1].run_once()
        doc=response.json()['document']['document_id']; base=f'/api/v1/study-packs/{pack}/documents/{doc}'
        result=self.client.get(base+'/figures'); self.assertEqual(result.status_code,200,result.text)
        return doc,result.json()['figures'][0],raw.getvalue()

    def test_crop_preview_annotation_and_old_revision(self):
        pack=self.pack(); doc,fig,raw=self.figure(pack); base=f'/api/v1/study-packs/{pack}/documents/{doc}'
        cropped=self.client.post(base+'/figures/crops',json={'figure_id':fig['figure_id'],'bbox':{'x0':.1,'y0':.1,'x1':.9,'y1':.9}})
        self.assertEqual(cropped.status_code,201,cropped.text)
        self.assertEqual(self.client.post(base+'/figures/crops',json={'figure_id':fig['figure_id'],'bbox':{'x0':-1,'y0':0,'x1':1,'y1':1}}).status_code,422)
        url=base+'/figures/'+fig['figure_id']+'/annotations'
        first=self.client.post(url,json={'text':'User assertion <script>bad</script>'})
        self.assertEqual(first.status_code,201,first.text)
        self.client.post(url,json={'text':'Updated user assertion'})
        old=self.client.get(base+'/units/'+first.json()['unit_id'])
        self.assertEqual(old.json()['text'],'User assertion <script>bad</script>')
        self.assertEqual(old.json()['provenance'],'user_annotation')
        self.assertEqual(self.client.get(base+'/original').content,raw)
        preview=self.client.get(base+'/figures/'+fig['figure_id']+'/preview')
        self.assertEqual(preview.headers['cache-control'],'no-store')

    def test_foreign_ids_origins_and_external_permission(self):
        pack=self.pack(); doc,fig,_=self.figure(pack); other=self.pack()
        self.assertEqual(self.client.get(f'/api/v1/study-packs/{other}/documents/{doc}/figures').status_code,404)
        response=self.client.post(f'/api/v1/study-packs/{pack}/visual-jobs',json={'figure_ids':[fig['figure_id']],'config':{'provider':'groq','model':'configured'}})
        self.assertEqual(response.status_code,422,response.text)
        response=self.client.get(f'/api/v1/study-packs/{pack}/documents/{doc}/figures',headers={'Origin':'https://evil.example'})
        self.assertEqual(response.status_code,403)

    def test_interrupted_visual_history_is_readable_without_starting_work(self):
        from aura_bio.api.study_visual import visual_services
        from aura_bio.study.visual.schema import VisualJobConfig
        from test_visual_jobs import FakeDescriber
        pack=self.pack(); doc,fig,_=self.figure(pack)
        jobs=visual_services(); jobs.describer=FakeDescriber()
        job=jobs.start(pack,[fig['figure_id']],VisualJobConfig()); jobs.recover()
        response=self.client.get(f'/api/v1/study-packs/{pack}/visual-jobs',params={'document_id':doc})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['jobs'][0]['job_id'],job.job_id)
        self.assertEqual(response.json()['jobs'][0]['state'],'paused')
        self.assertEqual(jobs.describer.calls,0)

    def test_interrupted_visual_history_is_readable_without_starting_work(self):
        from aura_bio.api.study_visual import visual_services
        from aura_bio.study.visual.schema import VisualJobConfig
        from test_visual_jobs import FakeDescriber
        pack=self.pack(); doc,fig,_=self.figure(pack)
        jobs=visual_services(); jobs.describer=FakeDescriber()
        job=jobs.start(pack,[fig['figure_id']],VisualJobConfig()); jobs.recover()
        response=self.client.get(f'/api/v1/study-packs/{pack}/visual-jobs',params={'document_id':doc})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['jobs'][0]['job_id'],job.job_id)
        self.assertEqual(response.json()['jobs'][0]['state'],'paused')
        self.assertEqual(jobs.describer.calls,0)
