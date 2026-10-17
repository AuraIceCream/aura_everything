from contextlib import ExitStack
import re

from .extractors import unit_id
from .schema import Extraction, Locator, StudyError, Unit


def _spacing_cost(text):
    """Compare parser artifacts, never rewrite scientific words by guesswork."""
    tracked = sum(len(value) for value in re.findall(r'\b(?:[A-Za-z]\s+){3,}[A-Za-z]\b', text))
    merged = sum(len(value) - 24 for value in re.findall(r'[A-Za-z]{25,}', text))
    return tracked + merged


def extract_pdf_page(path, document, page, limits):
    """One bounded worker step; no enclosing document OCR timeout."""
    import pypdf
    with path.open('rb') as handle:
        reader = pypdf.PdfReader(handle)
        if reader.is_encrypted:
            raise StudyError('encrypted', 'Upload a decrypted PDF.')
        if len(reader.pages) > limits.max_pages_or_slides or not 1 <= page <= len(reader.pages):
            raise StudyError('limit', 'PDF page count/index exceeds the limit.')
        raw = (reader.pages[page-1].extract_text() or '').strip()
        label = reader.page_labels[page-1]
        rotation = int(reader.pages[page-1].get('/Rotate',0)) % 360
    text, engine, regions, drawings, captions = raw, 'pypdf', [], False, []
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            physical = pdf.pages[page-1]
            candidates = [(raw,'pypdf')]
            for tolerance in (1,3):
                value = (physical.extract_text(use_text_flow=True,x_tolerance=tolerance) or '').strip()
                if value: candidates.append((value,f'pdfplumber-flow-x{tolerance}'))
            text,engine = min(candidates,key=lambda item:(_spacing_cost(item[0]),-len(item[0])))
            # Geometry is already upright/top-left in pdfplumber; retain source region anchors.
            objects = list(physical.images)+list(physical.curves)+list(physical.rects)+list(physical.lines)
            drawings = bool(objects)
            # Both pdfplumber coordinates and CropBox are upright. The rendered
            # asset uses CropBox, not MediaBox; normalise in that exact frame.
            cx0,cy0,cx1,cy1=physical.cropbox or physical.bbox
            cw,ch=cx1-cx0,cy1-cy0
            for obj in objects:
                x0,x1 = max(0,(float(obj.get('x0',cx0))-cx0)/cw),min(1,(float(obj.get('x1',cx1))-cx0)/cw)
                y0,y1 = max(0,(float(obj.get('top',cy0))-cy0)/ch),min(1,(float(obj.get('bottom',cy1))-cy0)/ch)
                if x1>x0 and y1>y0: regions.append([x0,y0,x1,y1])
            # Preserve caption identity and geometry separately from body prose.
            from .questions import caption_anchors
            lines = []
            for word in physical.extract_words(x_tolerance=1):
                group = next((g for g in reversed(lines[-8:]) if abs(g['top']-word['top']) < 3), None)
                if group is None:
                    group = {'top':word['top'], 'words':[]}; lines.append(group)
                group['words'].append(word)
            caption_lines = []
            for group in lines:
                words = sorted(group['words'],key=lambda w:w['x0'])
                segments=[[]]
                for word in words:
                    if segments[-1]:
                        previous=segments[-1][-1]
                        height=min(previous['bottom']-previous['top'],word['bottom']-word['top'])
                        if word['x0']-previous['x1'] > max(8,height):
                            segments.append([])  # Same baseline does not imply the same text column.
                    segments[-1].append(word)
                for segment in segments:
                    box = [max(0,(min(w['x0'] for w in segment)-cx0)/cw),max(0,(min(w['top'] for w in segment)-cy0)/ch),
                           min(1,(max(w['x1'] for w in segment)-cx0)/cw),min(1,(max(w['bottom'] for w in segment)-cy0)/ch)]
                    if box[2] > box[0] and box[3] > box[1]:
                        caption_lines.append({'text':' '.join(w['text'] for w in segment),'bbox':box})
            captions = caption_anchors(caption_lines)
            physical.close()
    except ImportError:
        pass
    if max(len(raw),len(text)) > 10_000_000:
        raise StudyError('limit','Page text exceeds safety limit.')
    return Unit(unit_id(document,f'page:{page}'),document.document_id,page-1,'body',document.filename,'',text,
                (Locator('pdf',page=page,page_label=label),),{'raw_text':raw,'text_extractor':engine,'rotation':rotation,
                'visual_regions':regions,'figure_anchors':captions,'has_drawings':drawings,
                'caption_anchor':bool(re.search(r'\b(fig(?:ure)?[. ]?\s*\d|diagram|pathway)\b',text,re.I))})


def extract(path, document, limits):
    import pypdf
    units, warnings = [], ['PDF text reading order may be imperfect for columns, equations and figures; no OCR/vision was run.']
    with ExitStack() as stack:
        handle = stack.enter_context(path.open('rb'))
        reader = pypdf.PdfReader(handle)
        if reader.is_encrypted:
            raise StudyError('encrypted', 'Upload a decrypted PDF; password-protected files are unsupported.')
        if len(reader.pages) > limits.max_pages_or_slides:
            raise StudyError('limit', 'PDF page count exceeds the configured limit.')
        labels = reader.page_labels
        geometry = None
        try:
            import pdfplumber
            geometry = stack.enter_context(pdfplumber.open(path))
        except ImportError:
            warnings.append('pdfplumber is unavailable: using basic PDF extraction. Install the study extra for geometry-aware word spacing.')
        total = 0
        for number, page in enumerate(reader.pages, 1):
            raw = (page.extract_text() or '').strip()
            text, engine = raw, 'pypdf'
            if geometry is not None:
                physical = geometry.pages[number - 1]
                try:
                    # Character coordinates recover tracked letters. Content-flow
                    # order avoids joining prose horizontally across columns;
                    # complex reading order still needs a source-page inspection.
                    candidates = [(raw, 'pypdf')]
                    for tolerance in (1, 3):
                        parsed = (physical.extract_text(use_text_flow=True, x_tolerance=tolerance) or '').strip()
                        if parsed:
                            candidates.append((parsed, f'pdfplumber-flow-x{tolerance}'))
                    # Narrow spacing avoids merging small-font words; wider
                    # spacing can recover tracked letters. Raw extraction stays
                    # eligible, rather than universally replacing a good parser.
                    text, engine = min(candidates, key=lambda item: (_spacing_cost(item[0]), -len(item[0])))
                except Exception as exc:
                    warnings.append(f'Page {number}: geometry extraction failed ({type(exc).__name__}); basic text retained.')
                finally:
                    physical.close()
            total += max(len(text), len(raw))
            if total > 10_000_000:
                raise StudyError('limit', 'PDF extracted text exceeds the safety limit.')
            if not text:
                warnings.append(f'Page {number}: no extracted text; blank or image-only content is uninterpreted.')
            units.append(Unit(unit_id(document, f'page:{number}'), document.document_id, number - 1,
                              'body', document.filename, '', text,
                              (Locator('pdf', page=number, page_label=labels[number - 1]),),
                              metadata={'raw_text': raw, 'text_extractor': engine}))
    if not any(u.text for u in units):
        raise StudyError('ocr_required', 'No usable PDF text layer. OCR or a text-based PDF is required; OCR is not included yet.')
    version = f'pypdf-{pypdf.__version__}'
    if geometry is not None:
        version += f'+pdfplumber-{pdfplumber.__version__}-flow-quality-v2'
    return Extraction(units, [], warnings, {'units': len(units), 'text_units': sum(bool(u.text) for u in units)}, version)
