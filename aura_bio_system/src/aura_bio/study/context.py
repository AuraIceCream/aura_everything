"""Bounded neighbouring context and structural bibliography detection."""
import re

from ..verification.checkers import content_tokens


def asks_for_references(question):
    return bool(re.search(r'\b(?:references|bibliography|citations|cited (?:papers|studies|sources)|'
                          r'papers (?:cited|referenced))\b', question, re.I)
                or re.search(r'\b(?:which|list|identify)\b.*\b(?:papers|publications|authors)\b', question, re.I))


def is_reference_passage(text):
    if re.search(r'(?mi)^\s*(?:references|bibliography|literature cited)\s*$', text[:350]):
        return True
    entries = re.findall(r'(?m)^\s*\d{1,3}[.)]\s+[A-Z][^\n]{0,160}', text)
    years = re.findall(r'\b(?:19|20)\d{2}\b', text)
    return len(entries) >= 3 and len(years) >= 3


def body_evidence(question, items):
    items = list(items)
    return items if asks_for_references(question) else [
        h for h in items if not is_reference_passage(h.text)]


def with_neighbours(searcher, question, primary, max_passages):
    """Reserve at most two nearby native chunks without changing their citations."""
    from .questions import references, is_overview
    primary = body_evidence(question, primary)
    if (not primary or max_passages <= 1 or asks_for_references(question) or is_overview(question)
            or any(ref.kind in {'page', 'slide'} for ref in references(question))):
        return primary
    anchors = [h for h in primary[:3] if h.provenance == 'native_text']
    if not anchors:
        return primary
    try:
        adjacent = searcher.neighbors(anchors, radius=1, limit=12)
    except Exception as exc:
        warning = f'Neighbouring document context unavailable ({type(exc).__name__}).'
        if warning not in searcher.runtime_warnings:
            searcher.runtime_warnings.append(warning)
        return primary
    head = min(3, len(primary), max_passages)
    known = {(h.pack_id, h.chunk_id) for h in primary[:head]}
    terms = content_tokens(question)
    methods = bool(re.search(r'\b(?:assign|assigned|classif\w*|categor\w*|method\w*|procedure|protocol)\b', question, re.I))
    def relevance(hit):
        from .focus import intent_bonus
        score = len(terms & content_tokens(hit.text)) / max(1, len(terms))
        score += intent_bonus(question, hit.text)
        if methods and re.search(r'\b(?:methods|categorized|classified|threshold)\b', hit.text, re.I):
            score += .2
        if re.match(r'^\s*[a-z]', hit.text):  # A page can continue a prior sentence.
            score += .1
        return score
    pool = []
    for h in [*primary[head:], *body_evidence(question, adjacent)]:
        key = (h.pack_id, h.chunk_id)
        if h.provenance == 'native_text' and key not in known:
            known.add(key)
            pool.append(h)
    adjacent = pool
    adjacent.sort(key=relevance, reverse=True)
    keep = min(2, max(0, max_passages - head))
    context = [h for h in adjacent if relevance(h) > 0][:keep]
    return primary[:head] + context + primary[head:]
