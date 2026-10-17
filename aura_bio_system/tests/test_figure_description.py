import json
import unittest
import time
from aura_bio.study.visual.description import FigureDescriber,validate_description
from aura_bio.study.visual.schema import FigureInput,VisualJobConfig,FigureCandidate,NormalizedBox,ProviderResponse
from aura_bio.study.schema import StudyError
from dataclasses import replace


FIELDS={'kind':'pathway','labels':['A','B'],'axes':[],'relations':[{'from':'A','to':'B','relation':'arrow'}],'summary':'A points to B','uncertainties':[]}


def figure_input():
    return FigureInput(FigureCandidate('a'*32,'b'*32,'c'*32,'d'*32,{'kind':'image'},NormalizedBox(),'asset_normalized','manual','hash'),
                       b'pixels',VisualJobConfig(),ocr_hint='Hint says ImaginaryZ exists')


class Backend:
    def __init__(self,outputs): self.outputs=iter(outputs); self.calls=0
    def complete(self,input,**kwargs): self.calls+=1; return ProviderResponse(next(self.outputs),'ollama',input.config.model)


class SlowIsolatedBackend:
    isolated=True
    def complete(self,*args,**kwargs):
        time.sleep(10)
        raise AssertionError('Should have been terminated at the deadline')


class EchoIsolatedBackend:
    isolated=True
    def complete(self,input,**kwargs): return ProviderResponse(json.dumps(FIELDS),'ollama',input.config.model)


class DescriptionTests(unittest.TestCase):
    def test_valid_output_one_call(self):
        backend=Backend([json.dumps(FIELDS)])
        result=FigureDescriber(backend).describe(figure_input(),timeout_seconds=120)
        self.assertEqual(backend.calls,1); self.assertEqual(result.fields,FIELDS)

    def test_malformed_bounded_repair(self):
        backend=Backend(['bad',json.dumps(FIELDS)])
        self.assertEqual(len(FigureDescriber(backend).describe(figure_input(),timeout_seconds=120).responses),2)
        backend=Backend(['bad','still bad'])
        with self.assertRaises(StudyError): FigureDescriber(backend).describe(figure_input(),timeout_seconds=120)
        self.assertEqual(backend.calls,2)

    def test_limits_and_unknown_fields_rejected(self):
        for altered in ({**FIELDS,'labels':['X']*65},{**FIELDS,'summary':'x'*1501},{**FIELDS,'tool':'exec'}, {**FIELDS,'axes':[{}]*5}):
            with self.assertRaises(StudyError): validate_description(json.dumps(altered))
        with self.assertRaises(StudyError): validate_description('x'*65537)

    def test_schema_does_not_certify_hint_labels(self):
        fields=validate_description(json.dumps({**FIELDS,'labels':['ImaginaryZ']}))
        self.assertNotIn('verified',fields)
        self.assertNotIn('supported',fields)

    def test_provider_timeout_not_reuploaded(self):
        class Timeout:
            calls=0
            def complete(self,*args,**kwargs): self.calls+=1; raise StudyError('provider_timeout','Unknown completion.')
        backend=Timeout()
        with self.assertRaises(StudyError): FigureDescriber(backend).describe(figure_input(),timeout_seconds=120)
        self.assertEqual(backend.calls,1)

    def test_hosted_budget_gates_each_attempt_and_counts_failed_output(self):
        from aura_bio.study.visual.description import HostedTokenBudget,request_reservation
        input=replace(figure_input(),config=VisualJobConfig(provider='groq',model='vision-test'))
        class Hosted:
            calls=0
            def complete(self,input,**kwargs):
                self.calls+=1
                return ProviderResponse('bad','groq',input.config.model,usage={'total_tokens':100})
        backend=Hosted(); saved=[]
        budget=HostedTokenBudget(request_reservation(input),save=saved.append)
        # First malformed response is charged; its larger repair cannot fit.
        with self.assertRaises(StudyError) as caught:
            FigureDescriber(backend).describe(input,budget=budget)
        self.assertEqual(caught.exception.code,'budget_exhausted')
        self.assertEqual(backend.calls,1); self.assertEqual(budget.used,100)
        self.assertEqual(len(caught.exception.responses),1)
        self.assertEqual(saved[-1],100)

    def test_unknown_hosted_completion_keeps_durable_reservation(self):
        from aura_bio.study.visual.description import HostedTokenBudget,request_reservation
        input=replace(figure_input(),config=VisualJobConfig(provider='groq',model='vision-test'))
        class Timeout:
            def complete(self,*args,**kwargs): raise StudyError('provider_timeout','Unknown completion.')
        saved=[]; budget=HostedTokenBudget(50000,save=saved.append)
        with self.assertRaises(StudyError): FigureDescriber(Timeout()).describe(input,budget=budget)
        self.assertEqual(saved[-1],request_reservation(input))

    def test_slow_transport_is_terminated_at_wall_clock_deadline(self):
        start=time.monotonic()
        with self.assertRaises(StudyError) as caught:
            FigureDescriber(SlowIsolatedBackend()).describe(figure_input(),timeout_seconds=.2)
        self.assertEqual(caught.exception.code,'provider_timeout')
        self.assertLess(time.monotonic()-start,3)
        self.assertEqual(caught.exception.attempts,1)

    def test_spawned_transport_returns_structured_response(self):
        result=FigureDescriber(EchoIsolatedBackend()).describe(figure_input(),timeout_seconds=10)
        self.assertEqual(result.fields,FIELDS)
        self.assertEqual(len(result.responses),1)
