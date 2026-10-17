"""Owned inspection regions and a question-shared inference budget."""
from dataclasses import asdict,dataclass,replace
import re
import time
from .schema import NormalizedBox,FigureInput,digest
from .assets import crop_bytes
from ..schema import StudyError


@dataclass(frozen=True)
class FocusRegion:
    id: str
    figure_id: str
    bbox: NormalizedBox
    frame: str
    context_refs: tuple[str,...]
    source_hash: str
    question_hash: str
    precision: str = 'region'
    highlight_bbox: NormalizedBox | None = None


class FocusBudget:
    def __init__(self,max_calls,deadline,*,clock=time.monotonic,before_call=None):
        if type(max_calls) is not int or not 1<=max_calls<=2: raise ValueError('Focused reads permit at most two calls.')
        self.max_calls,self.deadline,self.clock,self.calls=max_calls,deadline,clock,0
        self.before_call=before_call

    def reserve_call(self,now=None):
        remaining=self.deadline-(self.clock() if now is None else now)
        if remaining<=0 or self.calls>=self.max_calls:
            raise StudyError('focus_budget_exhausted','Question-focused reading budget exhausted; resume explicitly with a new question job.')
        if self.before_call: self.before_call()
        self.calls+=1
        return remaining


def select_focus(question,figure,details,*,limit=2):
    if type(limit) is not int or not 1<=limit<=2: raise ValueError('At most two regions may be selected.')
    selected=[]
    for row in details.get('owned_regions',[]):
        id=row['id'];label=row.get('label',id)
        if not re.search(r'(?<!\w)'+re.escape(label)+r'(?!\w)',question,re.I): continue
        if row.get('origin') not in {'native_text','ocr','user_annotation'} or row.get('source_hash')!=figure.checksum or row.get('frame')!=figure.frame:
            raise StudyError('source_changed','Focused geometry is not owned by this source/frame.')
        box=NormalizedBox(**row['bbox']);refs=tuple(row.get('context_refs',()))
        boxes=[box]
        for ref in refs:
            context=details.get('context_regions',{}).get(ref)
            if context is None: raise StudyError('unresolved_reference','Required legend/header geometry is unavailable.')
            boxes.append(NormalizedBox(**context))
        union=NormalizedBox(min(b.x0 for b in boxes),min(b.y0 for b in boxes),max(b.x1 for b in boxes),max(b.y1 for b in boxes))
        selected.append(FocusRegion(id,figure.figure_id,union,figure.frame,refs,figure.checksum,digest(question),row.get('precision','region'),box))
    if len(selected)>limit: raise StudyError('limit','Question requires more than two detail regions; specify a smaller scope.')
    return tuple(selected)


def table_regions(tables, cropbox, figure):
    """Native PDF cell boundaries are inspection geometry, not verified values.

    Only an explicit first-column row label selects a row. Keep the complete
    first row (headers) and every cell in the selected row; never infer a panel
    rectangle from a model-proposed box or a nearby letter.
    """
    result={'owned_regions':[],'context_regions':{}}
    x0,y0,x1,y1=cropbox
    def box(cells):
        cells=[c for c in cells if c is not None]
        if not cells: return None
        values=(max(0,(min(c[0] for c in cells)-x0)/(x1-x0)),
                max(0,(min(c[1] for c in cells)-y0)/(y1-y0)),
                min(1,(max(c[2] for c in cells)-x0)/(x1-x0)),
                min(1,(max(c[3] for c in cells)-y0)/(y1-y0)))
        if values[0]>=values[2] or values[1]>=values[3]: return None
        return asdict(NormalizedBox(*values))
    for index,table in enumerate(tables[:4]):
        values=table.extract(); rows=table.rows
        if not rows or not values: continue
        header=box(rows[0].cells)
        if header is None: continue
        ref=f'table{index}-headers';result['context_regions'][ref]=header
        for ordinal,(row,cells) in enumerate(zip(rows[1:33],values[1:33]),1):
            label=(cells[0] or '').strip() if cells else ''
            region=box(row.cells)
            if not label or len(label)>120 or region is None: continue
            # Do not select a table whose geometry is outside this figure.
            b=NormalizedBox(**region); f=figure.bbox
            if not (f.x0<=b.x0<b.x1<=f.x1 and f.y0<=b.y0<b.y1<=f.y1): continue
            result['owned_regions'].append({'id':f'table{index}-row{ordinal}','label':label,
                'bbox':region,'source_hash':figure.checksum,'frame':figure.frame,
                'origin':'native_text','context_refs':[ref],'precision':'table_row'})
    return result


def owned_details(visual_store,figure):
    """Read-only geometry refresh for old packs, only inside explicit processing."""
    if figure.locator.get('kind')!='pdf': return {'owned_regions':[],'context_regions':{}}
    try: import pdfplumber
    except ImportError: return {'owned_regions':[],'context_regions':{}}
    path=visual_store.store.original_path(visual_store.pack_id,figure.document_id)
    document=visual_store.store.document(visual_store.pack_id,figure.document_id)
    if digest(path.read_bytes())!=document.checksum: raise StudyError('source_changed','Original PDF changed; native region geometry was not used.')
    with pdfplumber.open(path) as pdf:
        page=pdf.pages[figure.locator['page']-1]
        try: return table_regions(page.find_tables(),page.cropbox or page.bbox,figure)
        finally: page.close()


def read_focus(regions,question,config,visual_store,describer,budget):
    results=[]
    for region in regions:
        with visual_store.store.lease(visual_store.pack_id,require_ready=False):
            figure=visual_store.figure(region.figure_id)
            if figure.checksum!=region.source_hash or region.question_hash!=digest(question):
                raise StudyError('source_changed','Focused source/question identity changed.')
            asset=visual_store.rendered_asset(figure.document_id,figure.asset_id)
            parent=next(u for u in visual_store.store.units(visual_store.pack_id,figure.document_id) if u.unit_id==figure.unit_id)
            from .selection import figure_context
            pixels=crop_bytes(asset.content,region.bbox,max_pixels=config.max_pixels)
            focused=replace(figure,bbox=region.bbox,context_hash=digest(asdict(region)))
            input=FigureInput(focused,pixels,replace(config,question=question),visual_store.ocr_hint(figure),figure_context(parent,figure))
        description=describer.describe(input,timeout_seconds=config.timeout_seconds,call_budget=budget)
        # Reacquire ownership before returning any private derivative.
        with visual_store.store.lease(visual_store.pack_id,require_ready=False):
            current=visual_store.figure(region.figure_id)
            if current.checksum!=region.source_hash: raise StudyError('source_changed','Source changed during interpretation.')
            visual_store.rendered_asset(current.document_id,current.asset_id)
        results.append({'region':asdict(region),'fields':description.fields,
            'responses':[asdict(r) for r in description.responses],'prompt_hash':description.prompt_hash,
            'config_hash':description.config_hash,'image_hash':digest(pixels),'provenance':'vlm','numbers_verified':False})
    return tuple(results)
