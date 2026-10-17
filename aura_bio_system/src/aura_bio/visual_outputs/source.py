"""Resolve only cited, owned, immutable source units under existing pack leases."""
from copy import deepcopy
from dataclasses import replace, asdict
import hashlib
from .schema import VisualResult
from .grounding import ground_visual


def resolve_source_visual(spec, context, store, visual_store=None, *, question=''):
    rejected = VisualResult('omitted', limitations=('The cited source is unavailable, expired or no longer matches this answer. No substitute was selected.',))
    if store is None or spec.kind != 'source': return rejected
    grounded = ground_visual(spec, context)
    if grounded.status != 'ready': return grounded
    payload = deepcopy(grounded.spec.payload)
    pack, doc, uid = (payload[key] for key in ('pack_id', 'document_id', 'unit_id'))
    try:
        with store.lease(pack, require_ready=False), store.lock:
            document = store.document(pack, doc)
            if not document.active: return rejected
            unit = next((u for u in store.units(pack, doc) if u.unit_id == uid), None)
            if unit is None:
                from ..study.visual.storage import VisualStore
                owned = visual_store if visual_store is not None and visual_store.pack_id == pack else VisualStore(store, pack)
                unit = owned.revision(uid)
                if unit.document_id != doc: return rejected
            from ..study.visual.schema import NormalizedBox
            actual = unit.provenance_details.get('bbox')
            if actual is not None: actual = asdict(NormalizedBox(**actual))
            if payload['bbox'] is not None and payload['bbox'] != actual: return rejected
            asset = payload['asset_id']
            if asset is not None and asset not in unit.asset_ids: return rejected
            if asset is None: asset = next(iter(unit.asset_ids), None)
            checksum = None
            if asset:
                metadata = store.asset(pack, doc, asset)
                if unit.provenance == 'native_text' and metadata['unit_id'] != uid: return rejected
                checksum = hashlib.sha256(store.asset_path(pack, doc, asset).read_bytes()).hexdigest()
                if checksum != metadata['checksum']: return rejected
            elif actual is not None:
                return rejected
            focus_unit=unit
            if question and not unit.provenance_details.get('focus_regions'):
                # A retained native-caption citation may point at the parent
                # page. Use only revisions frozen into this answer's evidence,
                # never a mutable active pointer or a later upload.
                from ..study.visual.storage import VisualStore
                from ..study.attachments import question_hash
                selected=[id for e in context.evidence if getattr(e,'pack_id',None)==pack and
                    getattr(e,'document_id',None)==doc and getattr(e,'provenance','native_text') in {'vlm','user_annotation'}
                    for id in getattr(e,'unit_ids',()) if id!=uid]
                if selected:
                    owned=visual_store if visual_store is not None and visual_store.pack_id==pack else VisualStore(store,pack)
                    for id in dict.fromkeys(selected):
                        try: candidate=owned.revision(id)
                        except Exception: continue
                        details=candidate.provenance_details
                        if (candidate.document_id==doc and asset in candidate.asset_ids and details.get('source_unit_id')==uid and
                            details.get('question_hash')==question_hash(question) and details.get('focus_regions')):
                            focus_unit=candidate;break
            regions=focus_unit.provenance_details.get('focus_regions',())
            highlights=[]
            if regions:
                from ..study.attachments import question_hash
                from ..study.visual.schema import digest
                if not question or focus_unit.provenance_details.get('question_hash')!=question_hash(question): return rejected
                if not checksum or len(regions)>2: return rejected
                for region in regions:
                    if region['source_hash']!=checksum or region['question_hash']!=digest(question): return rejected
                    if region['frame'] not in {'page_normalized','asset_normalized'}: return rejected
                    precision=region.get('precision','region')
                    if precision not in {'region','panel','table_row'}: return rejected
                    box=asdict(NormalizedBox(**(region.get('highlight_bbox') or region['bbox'])))
                    if actual and not (actual['x0']<=box['x0']<box['x1']<=actual['x1'] and actual['y0']<=box['y0']<box['y1']<=actual['y1']): return rejected
                    if region['id']!='whole-figure':
                        highlights.append({'id':region['id'],'bbox':box,'precision':precision})
            payload.update(asset_id=asset, bbox=actual, revision_id=uid,
                source_checksum=document.checksum, asset_checksum=checksum,
                generation=next((getattr(e, 'generation', 0) for e in context.evidence
                                 if getattr(e, 'pack_id', None) == pack and uid in getattr(e, 'unit_ids', ())), 0),
                locators=[loc.as_dict() for loc in unit.locators], coordinates='upright_normalized',
                highlight_precision='region' if actual else 'whole_asset' if asset else 'unit_only',
                resolved=True)
            if regions:
                payload['highlights']=highlights
                payload['warnings']=list(focus_unit.metadata.get('focus_warnings',()))
                payload['geometry_revision_ids']=[focus_unit.unit_id]
                if highlights: payload['highlight_precision']=highlights[0]['precision']
            return replace(grounded, spec=replace(grounded.spec, version=2 if regions else spec.version, payload=payload))
    except Exception:
        return rejected
