"""Explicit, pack-owned visual evaluation; keys never enter provider prompts.

The initial run records descriptions, not generated answers. Answer/control
quality requires manual review of the frozen question alongside the output.
"""
import argparse
import io
import json
import sys
from dataclasses import asdict,replace
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'src'))
from figure_bank import validate_figure_bank
from aura_bio.study.storage import StudyStore
from aura_bio.study.jobs import StudyJobs
from aura_bio.study.visual.storage import VisualStore
from aura_bio.study.visual.schema import VisualJobConfig,FigureInput,digest
from aura_bio.study.visual.assets import crop_bytes
from aura_bio.study.visual.description import FigureDescriber,PROMPT_HASH,HostedTokenBudget
from aura_bio.study.visual.evaluation import evaluate_figure_run,validate_resume,pin_evaluation_config
from aura_bio.study.validation import contained,validate_id


def main():
    import os
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(os.environ.get('AURA_STUDY_ROOT','.local/study-packs')))
    parser.add_argument('--pack-id',required=True); parser.add_argument('--run-id',required=True,help='Generated 32-character hexadecimal run ID')
    parser.add_argument('--split',choices=['dev','holdout'],required=True)
    parser.add_argument('--provider',choices=['ollama','groq'],default='ollama'); parser.add_argument('--model',default='qwen3.5:4b')
    parser.add_argument('--allow-inference',action='store_true'); parser.add_argument('--approve-external',action='store_true')
    parser.add_argument('--score-only',action='store_true'); parser.add_argument('--ocr-hints',action='store_true')
    args=parser.parse_args(); validate_id(args.run_id)
    checked=validate_figure_bank(ROOT/'figure_bank.jsonl',ROOT/'figure_sources.json')
    manifest=json.loads((ROOT/'figure_sources.json').read_text(encoding='utf-8'))
    sources={s['figure_id']:s for s in manifest['sources']}
    bank=[{**json.loads(line),'visible_labels':sources[json.loads(line)['figure_id']]['visible_labels']} for line in (ROOT/'figure_bank.jsonl').read_text(encoding='utf-8').splitlines() if json.loads(line)['split']==args.split]
    store=StudyStore(args.root); store.assert_available(args.pack_id); visual=VisualStore(store,args.pack_id)
    config=VisualJobConfig(provider=args.provider,model=args.model,prompt_hash=PROMPT_HASH,
                          consent={'external_allowed':args.approve_external,'images':args.approve_external,'hints':args.approve_external})
    folder=contained(store.root,args.pack_id,'traces','evaluation',args.run_id); folder.mkdir(parents=True,exist_ok=True)
    metadata=folder/'manifest.json'; output=folder/'records.jsonl'
    previous=json.loads(metadata.read_text(encoding='utf-8')) if metadata.exists() else None
    if not args.score_only:
        if not args.allow_inference: parser.error('Real model calls require --allow-inference. No inference was started.')
        if args.provider=='groq' and (not args.approve_external or not visual.permission()): parser.error('Groq needs pack permission plus --approve-external; all frozen selected fixtures/hints are sent.')
        if args.provider=='ollama':
            from aura_bio.study.visual.ollama import OllamaVisionBackend
            backend=OllamaVisionBackend()
            config=pin_evaluation_config(config,previous,score_only=False,preflight=backend.preflight)
        else:
            from aura_bio.study.visual.groq import GroqVisionBackend
            backend=GroqVisionBackend()
    else: config=pin_evaluation_config(config,previous,score_only=True)
    identity={'manifest_hash':checked['manifest_sha256'],'bank_hash':manifest['bank_sha256'],'split_hash':manifest['split_sha256'],'split':args.split,
              'provider':args.provider,'model':args.model,'model_digest':config.model_digest,'prompt_hash':PROMPT_HASH,
              'config_hash':config.checksum,'ocr_hints':args.ocr_hints}
    if previous: validate_resume(previous,identity)
    elif args.score_only: raise ValueError('No existing run to score.')
    else: metadata.write_text(json.dumps(identity,indent=2),encoding='utf-8')
    records=[json.loads(line) for line in output.read_text(encoding='utf-8').splitlines()] if output.exists() else []
    if not args.score_only:
        seen={r['id'] for r in records}; spent=sum(r.get('tokens',0) for r in records)
        usage_file=folder/'usage.json'
        if usage_file.exists(): spent=max(spent,json.loads(usage_file.read_text(encoding='utf-8'))['used'])
        budget=HostedTokenBudget(config.token_budget,spent,lambda value:usage_file.write_text(json.dumps({'used':value}),encoding='utf-8')) if args.provider=='groq' else None
        for fid in dict.fromkeys(q['figure_id'] for q in bank):
            questions=[q for q in bank if q['figure_id']==fid]
            if all(q['id'] in seen for q in questions): continue
            raw=(ROOT/sources[fid]['path']).read_bytes()
            doc,_=store.add_document(args.pack_id,f'{fid}.png',io.BytesIO(raw))
            jobs=StudyJobs(store)
            while not store.units(args.pack_id,doc.document_id) and jobs.run_once(): pass
            figure=visual.figures(doc.document_id)[0]; asset=visual.rendered_asset(doc.document_id,figure.asset_id)
            hint=' '.join(q.get('hint_control','') for q in questions)
            ocr=''
            if args.ocr_hints:
                from aura_bio.study.visual.ocr import TesseractOcr
                ocr=TesseractOcr().read(asset,language='eng',timeout_seconds=60).text
            try:
                result=FigureDescriber(backend).describe(FigureInput(figure,crop_bytes(asset.content,figure.bbox),config,ocr,hint),
                                                       timeout_seconds=config.timeout_seconds,budget=budget)
                tokens=sum(r.usage.get('total_tokens',sum(r.usage.get(k,0) for k in ('prompt_tokens','completion_tokens'))) for r in result.responses)
                spent+=tokens
                result_payload={'state':'completed','labels':result.fields['labels'],'description':asdict(result),
                                'latency_ms':sum(r.elapsed_seconds for r in result.responses)*1000,'tokens':tokens,'numeric_certified':False,'model_digest':config.model_digest,
                                'figure_id':figure.figure_id,'document_id':doc.document_id,'bbox':asdict(figure.bbox)}
            except Exception as exc:
                result_payload={'state':'error','error':getattr(exc,'code',type(exc).__name__),'numeric_certified':False,
                                'responses':[asdict(r) for r in getattr(exc,'responses',())]}
            for n,q in enumerate(questions):
                if q['id'] in seen: continue
                record={'id':q['id'],**result_payload,'tokens':result_payload.get('tokens',0) if n==0 else 0}
                with output.open('a',encoding='utf-8') as handle: handle.write(json.dumps(record,ensure_ascii=False)+'\n')
                records.append(record)
            if result_payload['state']=='error': break  # No repeated upload/fallback after unknown failure.
    summary=evaluate_figure_run(records,bank)
    (folder/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary))


if __name__=='__main__': main()
