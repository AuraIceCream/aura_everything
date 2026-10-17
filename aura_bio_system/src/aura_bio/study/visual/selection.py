"""Occurrence-aware discovery; exclusions are returned, not silently hidden."""
from collections import Counter
from dataclasses import asdict,replace
from .schema import FigureCandidate, NormalizedBox,digest
from ..schema import StudyError
from .ocr import needs_ocr
from ..questions import anchors


def figure_context(unit, figure):
    """The caption comes first; unrelated introductory prose cannot displace it."""
    if not figure.caption:
        return unit.text[:4000]
    offset = unit.text.find(figure.caption)
    nearby = unit.text[max(0,offset-600):offset+2800] if offset >= 0 else ''
    return (figure.caption + '\n' + nearby)[:4000]


def caption_regions(unit):
    """Separate caption-owned regions without splitting the panels of one figure.

    Conservative fallback: when geometry cannot bind a caption, retain a page
    candidate instead of guessing a tight crop. Manual crops remain available.
    """
    captions = [a for a in anchors(unit) if a.get('bbox')]
    regions = unit.metadata.get('visual_regions', [])
    groups = {i:[] for i in range(len(captions))}
    for region in regions:
        options = []
        for i, caption in enumerate(captions):
            x0,y0,x1,y1 = caption['bbox']
            if region[2] >= x0 and region[0] <= x1:
                distance = min(abs(y0-region[3]), abs(region[1]-y1))
                # Caption may be above or below its figure. Don't attach a
                # drawing that crosses the caption of a different figure.
                if not any(j != i and region[1] < c['bbox'][1] < region[3] for j,c in enumerate(captions)):
                    options.append((distance,i))
        if options:
            distance,i = min(options)
            if distance <= .3:
                groups[i].append(region)
    result = []
    for i, caption in enumerate(captions):
        owned = groups[i]
        if not owned:
            continue
        # Include the caption itself to preserve identity and legend labels.
        points = [*owned, caption['bbox']]
        box = NormalizedBox(max(0,min(r[0] for r in points)-.02), max(0,min(r[1] for r in points)-.02),
                            min(1,max(r[2] for r in points)+.02), min(1,max(r[3] for r in points)+.02))
        result.append((box, caption))
    return result


def select_figures(units, assets, *, limit=20):
    if not 1 <= limit <= 200:
        raise StudyError('limit','Select between 1 and 200 figures per job.')
    parents = {u.unit_id:u for u in units}
    repeated = Counter(a.checksum for a in assets)
    result,selected = [],0
    for asset in assets:
        unit = parents.get(asset.unit_id)
        if unit is None: continue
        locator = unit.locators[0].as_dict() if unit.locators else {'kind':'image'}
        if asset.metadata.get('shape_id') is not None: locator['shape_id'] = asset.metadata['shape_id']
        is_page = locator['kind'] == 'pdf'
        frame = 'page_normalized' if is_page else 'asset_normalized'
        regions = unit.metadata.get('visual_regions',[])
        reason,excluded,bbox = 'embedded_image',None,NormalizedBox()
        if is_page:
            if regions:
                # Union anchors to retain panels and legends rather than chopping a diagram into labels.
                bbox = NormalizedBox(max(0,min(r[0] for r in regions)-.05),max(0,min(r[1] for r in regions)-.05),
                                     min(1,max(r[2] for r in regions)+.05),min(1,max(r[3] for r in regions)+.05))
                reason = 'drawing_region'
            elif unit.metadata.get('has_drawings') or unit.metadata.get('caption_anchor'):
                reason = 'uncertain_page_manual_available'
            elif needs_ocr(unit.text):
                reason = 'ocr_required_manual_available'
            elif len(unit.text.strip()) < 80:
                reason = 'low_text_page_manual_available'
            else:
                reason,excluded = 'page_preview','text_only'
        tiny = asset.width*asset.height < 16_384 or min(asset.width,asset.height)<64
        if tiny: excluded = 'repeated_logo' if repeated[asset.checksum]>1 else 'tiny_image'
        if excluded is None:
            if selected >= limit: excluded = 'selection_limit'
            else: selected += 1
        context = digest({'text':unit.text,'locator':locator,'metadata':unit.metadata})
        separate = caption_regions(unit) if is_page else []
        native_captions = anchors(unit)
        regions_to_emit = separate or [(bbox, native_captions[0] if len(native_captions) == 1 else {})]
        for number,(box,caption) in enumerate(regions_to_emit):
            skip = excluded
            if number:
                if selected >= limit: skip = 'selection_limit'
                elif skip is None: selected += 1
            fid = digest({'asset':asset.asset_id,'unit':unit.unit_id,'box':asdict(box),'context':context,
                          'caption':caption})[:32] if caption else digest({'asset':asset.asset_id,'unit':unit.unit_id,'box':asdict(box),'context':context})[:32]
            result.append(FigureCandidate(fid,unit.unit_id,asset.asset_id,unit.document_id,locator,box,frame,
                          'caption_region' if separate else reason,context,skip,asset.checksum,
                          caption.get('label',''),caption.get('caption',''),caption.get('kind','figure')))
    return result


def create_crop(candidate, bbox):
    if candidate.frame not in {'page_normalized','asset_normalized'}:
        raise StudyError('invalid_crop','Source coordinate frame is unknown.')
    if not isinstance(bbox,NormalizedBox):
        raise StudyError('invalid_crop','Use upright normalized coordinates.')
    return replace(candidate,figure_id=digest({'parent':candidate.figure_id,'crop':asdict(bbox)})[:32],bbox=bbox,
                   reason='manual_crop',exclusion_reason=None)
