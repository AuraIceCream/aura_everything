import unittest
from dataclasses import replace
from unittest.mock import patch
from test_figure_description import figure_input,FIELDS
from aura_bio.study.visual.ollama import OllamaVisionBackend
from aura_bio.study.visual.groq import GroqVisionBackend
from aura_bio.study.schema import StudyError


class Response:
    def __init__(self,data,status=200,headers=None): self.data=data; self.status_code=status; self.headers=headers or {}
    def json(self): return self.data


class Http:
    def __init__(self,replies): self.replies=iter(replies); self.calls=[]
    def get(self,*args,**kwargs): self.calls.append((args,kwargs)); return next(self.replies)
    def post(self,*args,**kwargs): self.calls.append((args,kwargs)); return next(self.replies)


class VisionProviderTests(unittest.TestCase):
    def test_vlm_absent_and_busy_fail_without_switch(self):
        config=figure_input().config
        http=Http([Response({'models':[]})])
        with self.assertRaises(StudyError): OllamaVisionBackend(http=http).preflight(config)
        http=Http([Response({'models':[{'name':config.model,'digest':'one','size':1000}]}),Response({'capabilities':['vision']}),Response({'models':[{'name':'other:4b'}]})])
        with self.assertRaises(StudyError) as error: OllamaVisionBackend(http=http).preflight(config)
        self.assertEqual(error.exception.code,'busy_gpu')
        self.assertEqual(len(http.calls),3)

    def test_preflight_accepts_idle_selected_model_already_resident(self):
        config=figure_input().config
        http=Http([Response({'models':[{'name':config.model,'digest':'one','size':3389983735}]}),
                   Response({'capabilities':['vision']}),
                   Response({'models':[{'name':config.model}]})])
        with patch('aura_bio.study.visual.ollama.gpu_free_mb',return_value=(170,4096,0)):
            self.assertEqual(OllamaVisionBackend(http=http).preflight(config),'one')

    def test_hosted_requires_crop_and_hint_consent(self):
        input=figure_input(); input=replace(input,config=replace(input.config,provider='groq'))
        http=Http([])
        with self.assertRaises(StudyError): GroqVisionBackend(http=http).complete(input,repair=None,timeout_seconds=120)
        self.assertEqual(http.calls,[])

    def test_429_pauses_and_no_fallback(self):
        input=figure_input(); input=replace(input,config=replace(input.config,provider='groq',consent={'external_allowed':True,'images':True,'hints':True}))
        http=Http([Response({},429,{'retry-after':'30'})])
        with patch.dict('os.environ',{'GROQ_API_KEY':'test-secret'}):
            with self.assertRaises(StudyError) as error: GroqVisionBackend(http=http).complete(input,repair=None,timeout_seconds=120)
        self.assertEqual(error.exception.code,'rate_limited'); self.assertNotIn('test-secret',str(error.exception))
        self.assertEqual(len(http.calls),1)
