"""Search representations only: cited source text and offsets stay untouched."""
import re
import unicodedata

NORMALIZATION_VERSION = 'unicode-greek-dehyphen-v1'
_GREEK = dict(zip('αβγδεζηθικλμνξοπρστυφχψω',
    'alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega'.split()))
# Query grammar, not the verification checker's content vocabulary. Preserve
# negation, quantities and one-letter scientific identifiers (e.g. T/B cells).
_STOPWORDS = frozenset('''a an the and or but as at by for from in into of on to with
    is are was were be been being am do does did have has had can could would should
    will shall may might must what which who whom whose when where why how this that
    these those it its they them their we our you your i my me us please tell explain
    describe compare according about through than then also'''.split())


def search_text(text):
    text = unicodedata.normalize('NFKC', text).replace('\u00ad', '')
    # Repair only a hyphen at an actual line break, not ordinary compound words.
    text = re.sub(r'(?<=\w)[-‐]\s*\n\s*(?=[a-z])', '', text)
    text = ''.join(f' {_GREEK[c.lower()]} ' if c.lower() in _GREEK else c for c in text)
    return re.sub(r'\s+', ' ', text).strip()


def query_terms(query):
    return list(dict.fromkeys(word for word in re.findall(r'\w+', search_text(query), re.UNICODE)
                             if word.casefold() not in _STOPWORDS))[:32]
