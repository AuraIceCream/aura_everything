"""Bound private answer context without cutting validated figure objects."""
from copy import copy
from .schema import StudyError


def _complete_figure(item):
    if item.provenance!='vlm': return False
    from .visual.description import validate_description
    try: validate_description(item.text)
    except StudyError: return False
    return True


def budget_evidence(items, *, max_passages, max_chars, warnings, originals=()):
    complete={(h.pack_id,h.chunk_id):h for h in originals if _complete_figure(h)}
    chosen,seen,remaining=[],set(),max_chars
    for hit in items:
        if hit is None: continue
        key=(hit.pack_id,hit.chunk_id)
        if key in seen or len(chosen)>=max_passages: continue
        seen.add(key)
        item=copy(complete.get(key,hit))
        if _complete_figure(item) and len(item.text)>remaining:
            warning=('A complete figure interpretation was omitted because it exceeds the remaining '
                     'context budget. Narrow the question or inspect figures separately.')
            if warning not in warnings: warnings.append(warning)
            continue
        if remaining<=0 or not item.text.strip(): continue
        item.text=item.text[:remaining]
        chosen.append(item)
        remaining-=len(item.text)
    return chosen
