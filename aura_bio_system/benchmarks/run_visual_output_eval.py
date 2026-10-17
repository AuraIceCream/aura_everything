"""Frozen visual-contract evaluation. Model inference is explicit, never default."""
import argparse
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import sys
from contextlib import nullcontext
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aura_bio.study.claims import StructuredClaim, ClaimDraft, ClaimBlock
from aura_bio.study.schema import Unit, Asset, Extraction, Locator
from aura_bio.study.storage import StudyStore
from aura_bio.study.searcher import StudyEvidence
from aura_bio.visual_outputs.context import build_visual_context
from aura_bio.visual_outputs.schema import parse_visual, VisualResult
from aura_bio.visual_outputs.grounding import ground_visual
from aura_bio.visual_outputs.source import resolve_source_visual
from aura_bio.visual_outputs.evaluation import evaluate_visual_results


def case_context(case, store):
    from PIL import Image, ImageDraw
    image=Image.new('RGB',(800,320),'white'); draw=ImageDraw.Draw(image)
    for n,sentence in enumerate(case['evidence_text'].split('. ')):
        draw.text((24,32+n*40),sentence,fill='black')
    draw.text((24,280),'Synthetic source fixture; not a biology accuracy result.',fill='black')
    stream=io.BytesIO();image.save(stream,format='PNG');pixels=stream.getvalue()
    pack=store.create_pack(case['id']);doc,_=store.add_document(pack.pack_id,'fixture.png',io.BytesIO(pixels))
    unit=Unit('d'*32,doc.document_id,0,'body','Synthetic fixture','',case['evidence_text'],(Locator('image'),),asset_ids=('e'*32,),provenance=case['provenance'])
    store.publish_extraction(doc.document_id,Extraction([unit],[Asset('e'*32,unit.unit_id,'image/png',pixels,{'width':800,'height':320})],[],{},'fixture'))
    evidence=[StudyEvidence('chunk1','fixture','Synthetic fixture',None,case['evidence_text'],None,None,'pack_sparse',1.,pack_id=pack.pack_id,document_id=doc.document_id,unit_ids=(unit.unit_id,),provenance=case['provenance'])]
    for item in case.get('extra_evidence',[]):
        evidence.append(replace(evidence[0],chunk_id=item['chunk_id'],document_id=item['document_id'],text=item['text'],provenance=item['provenance']))
    sentences=case['evidence_text'].split('. ')
    labels=['c1','c2','c3','c4','c5'] if case['id']!='plot-time' else ['c4','c5']
    claims=[];basis=[]
    for id,text in zip(labels,sentences):
        override=case.get('claim_overrides',{}).get(id,{})
        method=override.get('provenance',case['provenance']);cites=tuple(override.get('cite_ids',[1]))
        claims.append(StructuredClaim(id,text.rstrip('.')+'.',cites))
        kind={'native_text':'native_verified','vlm':'interpreted','ocr':'ocr_transcribed','user_annotation':'user_annotated'}[method]
        basis.append({'claim_index':len(basis),'verification_kind':kind,'inputs_verified':method=='native_text',
                      'supporting_provenance':[{'chunk_id':evidence[cites[0]-1].chunk_id,'provenance':method}]})
    draft=ClaimDraft(1,tuple(claims),tuple(ClaimBlock('claim',ref=c.id) for c in claims))
    delivery=SimpleNamespace(delivered_ids=[c.id for c in claims],verification={'claim_basis':basis})
    context=build_visual_context(draft,delivery,evidence)
    proposal=json.loads(json.dumps(case['proposal']))
    if case['kind']=='source': proposal['payload'].update(pack_id=pack.pack_id,document_id=doc.document_id)
    return context,proposal


def evaluate_case(case, context, proposal, generator=None, *, diagnostics=None):
    # The frozen negative cases encode bad layouts, but their question text is
    # deliberately identical to a positive request. They test guard rejection,
    # not model refusal. Generating a different valid layout would invalidate
    # that control. Keep the mode visible rather than claiming model accuracy.
    if generator and case['answerable']:
        from aura_bio.visual_outputs.planner import plan_visual
        return plan_visual(case['kind'],case['question'],context,generator,None,diagnostics=diagnostics), 'model'
    mode = 'guard_fixture' if generator else 'fixture'
    return ground_visual(parse_visual(json.dumps(proposal),context),context), mode


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model',help='Explicit local Ollama visual-proposal run; absent means frozen fixtures only.')
    parser.add_argument('--reviews',type=Path,help='JSON object mapping case IDs to manually reviewed {valid: true/false}.')
    args=parser.parse_args();data=Path(__file__).parent/'data'
    manifest=json.loads((data/'visual_output_bank_v1.manifest.json').read_text(encoding='utf-8'))
    raw=(data/manifest['bank']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=manifest['sha256']: raise SystemExit('Frozen visual bank hash mismatch.')
    bank=[json.loads(line) for line in raw.decode().splitlines()]
    if args.output.exists(): raise SystemExit('Use a new output directory; prior records are never overwritten.')
    args.output.mkdir(parents=True);records=[]
    generator=None
    if args.model:
        from aura_bio.study.claim_generation import StudyClaimGenerator
        generator=StudyClaimGenerator(model=args.model)
    with nullcontext(args.output) as fixture_dir:
        store=StudyStore(Path(fixture_dir)/'packs')
        try:
            for case in bank:
                began=time.monotonic();context,proposal=case_context(case,store)
                diagnostics={}
                try:
                    result, mode=evaluate_case(case,context,proposal,generator,diagnostics=diagnostics)
                    if result.status=='ready' and case['kind']=='source': result=resolve_source_visual(result.spec,context,store)
                except ValueError:
                    mode='guard_fixture' if generator and not case['answerable'] else ('model' if generator else 'fixture')
                    result=VisualResult('omitted',limitations=('Frozen proposal rejected by the authoritative schema.',))
                row={'id':case['id'],'kind':case['kind'],'status':result.status,'seconds':round(time.monotonic()-began,3),
                     'mode':mode,'result':result.as_dict()}
                records.append(row)
                with (args.output/'records.jsonl').open('a',encoding='utf-8') as handle: handle.write(json.dumps(row,ensure_ascii=False)+'\n')
                if diagnostics:
                    # Private local evaluation artifact. Never merge raw source
                    # material/provider diagnostics into public VisualResult.
                    with (args.output/'diagnostics.private.jsonl').open('a',encoding='utf-8') as handle:
                        handle.write(json.dumps({'id':case['id'],'diagnostics':diagnostics},ensure_ascii=False)+'\n')
                print(json.dumps({key:row[key] for key in ('id','status','seconds')}),flush=True)
        finally: store.close()
    reviews=json.loads(args.reviews.read_text(encoding='utf-8')) if args.reviews else {}
    summary=evaluate_visual_results(bank,records,reviews)
    summary.update(bank_sha256=manifest['sha256'],mode='model' if generator else 'fixture',
                   model=args.model,runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   controls_mode='guard_fixture' if generator else 'fixture',
                   controls_note='Frozen controls test rejection of authored bad layouts, not model unsupported-question refusal.',
                   source_assets='Synthetic private fixtures retained under the output directory for visual review; no user pack was modified.')
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
