"""Frozen, checkpointed production visual evaluation; inference is opt-in."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
SAFE_INPUTS = ('id', 'kind', 'question', 'pack_id', 'figure_ids', 'prepare_figures', 'think')
UNKNOWN = {'unknown_completion', 'in_flight'}


def sha(value):
    return hashlib.sha256(value).hexdigest()


def validate_manifest(manifest, bank_bytes):
    if sha(bank_bytes) != manifest.get('bank_sha256'):
        raise ValueError('Frozen bank hash changed; no inference started.')
    cases = [json.loads(line) for line in bank_bytes.decode('utf-8').splitlines() if line.strip()]
    ids = [c['id'] for c in cases]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', id) for id in ids):
        raise ValueError('Invalid or duplicate case identity.')
    for source in manifest.get('sources', []):
        if sha(Path(source['path']).read_bytes()) != source['sha256']:
            raise ValueError('Frozen source changed; no inference started.')
    return cases


def _append(path, row):
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')


def run_case(case, runtime, output):
    output.mkdir(parents=True, exist_ok=True)
    began = time.monotonic()
    row = {'id':case['id'], 'kind':case['kind'], 'case_sha256':sha(json.dumps(case, sort_keys=True).encode())}
    # Neither review keys nor authored control proposals can enter the runtime.
    inputs = {key:case[key] for key in SAFE_INPUTS if key in case}
    try:
        result = runtime(inputs)
        if not isinstance(result, dict) or result.get('status') not in {'ready','omitted','failed','deferred'}:
            raise ValueError('Runtime did not return an explicit visual outcome.')
        row.update(result)
    except Exception as exc:
        code = getattr(exc, 'code', type(exc).__name__)
        unknown = isinstance(exc, TimeoutError) or code in {'provider_timeout', 'unknown_completion'}
        deferred = code in {'busy_gpu','busy_memory','resource_unknown','model_missing','not_ready'}
        row.update(status='unknown_completion' if unknown else 'deferred' if deferred else 'failed', reason_code=code)
        _append(output/'private-errors.jsonl', {'id':case['id'], 'code':code, 'detail':str(exc)})
    row['seconds'] = round(time.monotonic()-began, 3)
    return row


def run_cases(cases, runtime, output, *, identity, resume=False):
    output.mkdir(parents=True, exist_ok=True)
    path = output/'runtime.json'
    if path.exists():
        if not resume or json.loads(path.read_text(encoding='utf-8')) != identity:
            raise ValueError('Existing run retained; resume requires identical frozen runtime.')
    elif resume:
        raise ValueError('No run exists to resume.')
    else:
        path.write_text(json.dumps(identity, indent=2), encoding='utf-8')
    prior = {}
    if (output/'records.jsonl').exists():
        for line in (output/'records.jsonl').read_text(encoding='utf-8').splitlines():
            row=json.loads(line); prior[row['id']]=row
    for case in cases:
        digest=sha(json.dumps(case, sort_keys=True).encode())
        if case['id'] in prior:
            if prior[case['id']].get('case_sha256') != digest: raise ValueError('Question/source configuration changed.')
            # Even failed attempts need a fresh run to be attempted again.
            continue
        started={'id':case['id'],'kind':case['kind'],'status':'in_flight','case_sha256':digest}
        _append(output/'records.jsonl', started)
        event={'id':case['id'],'state':'started'}
        _append(output/'events.jsonl',event)
        with (output/'progress.log').open('a',encoding='utf-8') as stream: stream.write(f"START {case['id']}\n")
        row=run_case(case,runtime,output)
        _append(output/'records.jsonl',row); prior[case['id']]=row
        _append(output/'events.jsonl',{'id':case['id'],'state':row['status']})
        with (output/'progress.log').open('a',encoding='utf-8') as stream:
            stream.write(f"{case['id']} | {row['status']} | {row['seconds']}s\n")
        print(json.dumps({key:row.get(key) for key in ('id','status','reason_code','seconds')}),flush=True)
    return [prior[case['id']] for case in cases]


class ProductionRuntime:
    """Use the same resolve, visual job, index and answer APIs as explicit Ask."""
    def __init__(self, model, *, require_full_stages=True,model_digest=None):
        self.model,self.require_full_stages,self.model_digest=model,require_full_stages,model_digest

    def _check_model(self):
        if self.model_digest is None: return
        import requests
        from aura_bio.study.schema import StudyError
        response=requests.get(os.environ.get('AURA_OLLAMA_HOST','http://127.0.0.1:11434')+'/api/tags',timeout=5);response.raise_for_status()
        selected=next((m for m in response.json().get('models',[]) if self.model in {m.get('name'),m.get('model')}),{})
        if selected.get('digest')!=self.model_digest: raise StudyError('model_changed','Frozen model digest changed; no substitute result accepted.')

    def __call__(self, case):
        from aura_bio.api.app import _execute, RunRequestModel
        from aura_bio.api.study_packs import study_services
        from aura_bio.api.study_visual import resolve_question, VisualQuestionRequest, start_job, StartRequest, job_status
        from aura_bio.study.schema import StudyError
        self._check_model()
        if self.require_full_stages:
            from aura_bio.resources import available_memory_mb
            memory=available_memory_mb()
            if memory is None: raise StudyError('resource_unknown','Complete benchmark memory admission could not be measured.')
            if memory['commit']<8192: raise StudyError('busy_memory',f"Complete hybrid/rerank/NLI admission needs 8192 MiB commit headroom; {memory['commit']:.0f} MiB available. No stage was disabled.")
        pack=case.get('pack_id')
        if not pack: raise ValueError('Model cases require an explicit study pack, never a fabricated checked context.')
        figures=case.get('figure_ids', [])
        if case.get('prepare_figures'):
            figures=[f['figure_id'] for f in resolve_question(pack,VisualQuestionRequest(question=case['question']))['figures']]
            if figures:
                think=case.get('think',False)
                job=start_job(pack,StartRequest(figure_ids=figures,config=question_config(self.model,case['question'],think)))
                _,indexer=study_services(); indexer.start()
                deadline=time.monotonic()+900
                while time.monotonic()<deadline:
                    current=job_status(pack,job['job_id'])
                    if current.get('state') in {'failed','partial','paused','cancelled'}:
                        raise RuntimeError(current.get('error') or 'Figure preparation did not complete.')
                    if current.get('index_error'): raise RuntimeError(current['index_error'])
                    if current.get('indexed'): break
                    time.sleep(1)
                else: raise TimeoutError('Preparation timed out; inspect checkpoint, do not resubmit.')
        request=RunRequestModel(query=case['question'],evidence_scope='pack_only',pack_id=pack,
            figure_ids=figures,visual_output=case['kind'],think=case.get('think',False))
        captured=[];admission={}
        if self.require_full_stages:
            # Audit hooks preserve the actual API pipeline and its normal trace
            # write. They only refuse a degraded configuration and capture its
            # private record; no mocked model/retrieval result is substituted.
            from unittest.mock import patch
            from aura_bio.study import runtime
            original_build,original_record=runtime.build_pack_pipeline,runtime.PrivateTraceStore.record
            def checked_build(*args,**kwargs):
                kwargs['require_model']=True
                pipeline=original_build(*args,**kwargs)
                try: admission.update(check_pipeline_stages(pipeline,self.model))
                except Exception:
                    pipeline.searcher.close();pipeline.store.close();raise
                return pipeline
            def record(store,trace):
                original_record(store,trace);captured.append(trace.as_dict())
            with patch.object(runtime,'build_pack_pipeline',checked_build),patch.object(runtime.PrivateTraceStore,'record',record):
                result=_execute(request)
            if len(captured)!=1: raise RuntimeError('Expected exactly one complete production answer trace.')
            report=captured[0].get('final_verification',{})
            if any('unavailable' in str(value).casefold() for value in report.get('checker_status',{}).values()):
                raise StudyError('stage_unavailable','Actual verification reported an unavailable checker; this is not a complete-pipeline result.')
        else: result=_execute(request)
        answer=result['answer_payload']; visuals=answer.get('visuals') or []
        visual=visuals[0] if visuals else {'status':'omitted','limitations':['No visual delivered.']}
        self._check_model()
        return {'status':visual['status'],'result':visual,'answer':answer,'decision':result['decision'],
                'mode':'production_ask','model':self.model,'stage_admission':admission,
                'private_trace':captured[0] if captured else None}


def question_config(model,question,think):
    return {'provider':'ollama','model':model,'question':question,'think':think,
            'num_predict':4096 if think else 2048,'timeout_seconds':300,'description_version':2,'focus':True}


def check_pipeline_stages(pipeline,model):
    from aura_bio.api.generation import OllamaGenerator
    from aura_bio.study.schema import StudyError
    if (getattr(pipeline.searcher,'mode',None)!='hybrid' or pipeline.reranker is None or
        not getattr(pipeline.verifier,'use_entailment',False) or not isinstance(pipeline.generator,OllamaGenerator) or
        pipeline.generator.model_name!=model):
        raise StudyError('stage_unavailable','Complete benchmark requires actual hybrid retrieval, reranker, enabled NLI and the selected model. No fallback result accepted.')
    return {'retrieval':'hybrid','reranker':pipeline.reranker.model_name,'nli_enabled':True,'generator':model,
            'external_critic':'disabled_no_hosted_consent'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mode',choices=['model'],required=True,help='Production Ask only; authored renderer/guard fixtures use run_visual_output_eval.py.')
    parser.add_argument('--model')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--reviews',type=Path,help='Private manual fidelity/readability and control-safe reviews; never sent to inference.')
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    bank_path=args.manifest.parent/manifest['bank']
    cases=validate_manifest(manifest,bank_path.read_bytes())
    if not args.model: parser.error('--model is required for explicit inference')
    os.environ['AURA_GENERATOR']='ollama'; os.environ['AURA_OLLAMA_MODEL']=args.model
    import requests
    response=requests.get(os.environ.get('AURA_OLLAMA_HOST','http://127.0.0.1:11434')+'/api/tags',timeout=5)
    response.raise_for_status()
    model=next((m for m in response.json().get('models',[]) if args.model in {m.get('name'),m.get('model')}),None)
    if not model or not model.get('digest'): raise SystemExit('Selected model/digest unavailable; no pull or inference attempted.')
    src=Path(__file__).resolve().parents[1]/'src'
    code_hash=sha(''.join(str(p.relative_to(src))+sha(p.read_bytes()) for p in sorted(src.rglob('*.py'))).encode())
    identity={'manifest_sha256':sha(args.manifest.read_bytes()),'model':args.model,'mode':args.mode,
              'runner_sha256':sha(Path(__file__).read_bytes()),'code_sha256':code_hash,'model_digest':model['digest'],
              'configuration':{key:os.environ.get(key) for key in ('AURA_STUDY_ROOT','AURA_STUDY_INDEX_MODE','AURA_STUDY_RERANK','AURA_NLI','AURA_ACCURACY_MODE','AURA_DRAFT_CANDIDATES','AURA_CRITIC')}}
    records=run_cases(cases,ProductionRuntime(args.model,model_digest=model['digest']),args.output,identity=identity,resume=args.resume)
    from aura_bio.visual_outputs.evaluation import evaluate_upgrade_results
    reviews=json.loads(args.reviews.read_text(encoding='utf-8')) if args.reviews else {}
    summary=evaluate_upgrade_results(cases,records,reviews)
    summary['states']={state:sum(r['status']==state for r in records) for state in {r['status'] for r in records}}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')


if __name__=='__main__': main()
