"""Deterministic document references; never invent search facts or figure labels."""
import re
from dataclasses import dataclass
from .schema import StudyError

_LABEL = r'(S?\d+(?:\.\d+)?)(?:[a-z]\b|\s*\([a-z]\))?(?!\w)'
_REFERENCE = re.compile(r'\b(fig(?:ure)?s?\.?|tables?|pages?|slides?)\s*' + _LABEL, re.I)
_CAPTION = re.compile(r'^\s*(Fig(?:ure)?\.?|Table)\s*(S?\d+(?:\.\d+)?)\s*[|.:]\s*\S', re.I)


@dataclass(frozen=True)
class Reference:
    kind: str
    value: str


def references(question):
    result=[]
    for match in _REFERENCE.finditer(question):
        kind,value=match[1].lower(),match[2].upper()
        kind='figure' if kind.startswith('fig') else kind.rstrip('s')
        result.append(Reference(kind,value))
        tail=question[match.end():]
        for _ in range(20):
            extra=re.match(r'\s*(?:-|–|to)\s*(\d+)\b',tail,re.I)
            if extra and value.isdigit():
                end=int(extra[1]); start=int(value)
                if end < start or end-start>=20:
                    raise StudyError('limit','Use an ascending reference range of at most twenty items.')
                result.extend(Reference(kind,str(n)) for n in range(start+1,end+1))
                value=str(end)
            else:
                extra=re.match(r'\s*(?:,\s*(?:and\s+)?|and\s+|&\s*)'+_LABEL,tail,re.I)
                if not extra: break
                value=extra[1].upper();result.append(Reference(kind,value))
            tail=tail[extra.end():]
        else:
            raise StudyError('limit','Use at most twenty references in one list.')
    return list(dict.fromkeys(result))


def caption_anchors(lines):
    """Only caption-shaped line starts, not prose such as 'see Fig. 5'."""
    result = []
    for line in lines:
        match = _CAPTION.match(line['text'])
        if match:
            result.append({'kind':'figure' if match[1].lower().startswith('fig') else 'table',
                           'label':match[2].upper(), 'caption':line['text'][:4000], 'bbox':line.get('bbox')})
    return result


def anchors(unit):
    if unit.provenance != 'native_text':
        return []  # A model interpretation is never authority for document identity.
    return unit.metadata.get('figure_anchors') or caption_anchors([{'text':s} for s in unit.text.splitlines()])


def is_overview(question):
    return bool(re.search(r'\b(?:summari[sz]e|summary|overview|main points|key points|study guide|revision notes|practice questions|flashcards)\b', question, re.I)
                and re.search(r'\b(?:this|the|my|uploaded|given|whole|entire|these)\s+(?:(?:study|uploaded)\s+)?(?:doc(?:ument)?s?|pdfs?|material|pack|chapters?|decks?|notes|slides|book)\b', question, re.I))


def scoped_units(store, pack_id, question):
    """None means ordinary topical search; [] means a requested target is absent."""
    refs = references(question)
    docs = [d for d in store.documents(pack_id) if d.active]
    named = [d for d in docs if d.filename.casefold() in question.casefold()]
    if named:
        docs = named
    if not refs and not named:
        return None
    units = [u for d in docs for u in store.units(pack_id, d.document_id)]
    if not refs:
        return units
    # A page qualification restricts a figure identity; it is not another
    # independent passage to union into an otherwise contradictory request.
    pages=[r for r in refs if r.kind in {'page','slide'}]
    if pages and any(r.kind in {'figure','table'} for r in refs):
        units=[u for u in units if any(str(getattr(loc,r.kind,''))==r.value for loc in u.locators for r in pages)]
    selected = {}
    for ref in refs:
        if ref.kind in {'page','slide'}:
            matched = [u for u in units if any(str(getattr(loc, ref.kind, '')) == ref.value for loc in u.locators)]
        else:
            matched = [u for u in units if any(a.get('kind','figure') == ref.kind and a['label'].upper() == ref.value for a in anchors(u))]
        doc_ids = {u.document_id for u in matched}
        if len(doc_ids) > 1:
            choices = ', '.join(d.filename for d in docs if d.document_id in doc_ids)
            raise StudyError('ambiguous_reference', f'{ref.kind.title()} {ref.value} occurs in multiple documents: {choices}. Include the document filename in your question.')
        if not matched:
            return []  # Do not answer a missing Figure 5 using Figure 6.
        selected.update((u.unit_id, u) for u in matched)
        if ref.kind in {'figure','table'}:
            from .attachments import question_hash
            for unit in units:
                details = unit.provenance_details
                if (unit.document_id in doc_ids and unit.provenance != 'native_text'
                        and details.get('figure_label') == ref.value
                        and details.get('reference_kind','figure') == ref.kind
                        and details.get('question_hash','') in {'',question_hash(question)}):
                    selected[unit.unit_id] = unit
    return list(selected.values())
