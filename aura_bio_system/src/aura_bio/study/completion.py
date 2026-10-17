"""Conservative request-coverage diagnostics, separate from factual support.

Lexical coverage cannot prove completeness. It can flag explicit unaddressed
parts and guide the existing second draft without certifying additional facts.
"""
import re

from ..retrieval.strategies import question_parts
from ..verification.checkers import content_tokens
from .focus import source_focus, objective_terms, answer_terms, SPECIFIC_OBJECTIVE

_GRAMMAR = {'document', 'paper', 'authors', 'author', 'reported', 'report', 'according',
            'does', 'did', 'provide', 'given', 'explain', 'describe', 'pdf'}
_NUMBER = re.compile(r'\d|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|hundred)\b', re.I)
_BOUNDARY = re.compile(r'(?:[<>≤≥]=?\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?)')


def _tokens(text):
    return {t.casefold().rstrip('s') for t in content_tokens(text) if t.casefold() not in _GRAMMAR}


def _boundaries(text):
    text = text.replace('≥', '>=').replace('≤', '<=').replace('–', '-')
    return {re.sub(r'\s+', '', match[0]) for match in _BOUNDARY.finditer(text)
            if not re.search(r'\b(?:p|p-value|pvalue)\s*=?\s*$', text[max(0, match.start()-16):match.start()], re.I)}


def _has_requested_count(part, text):
    match = re.search(r'\bhow many\s+(?:(?:different|distinct|total)\s+)?([a-z]+)', part, re.I)
    if not match or match[1].lower() in {'were', 'are', 'was', 'do', 'did', 'of'}:
        return bool(_NUMBER.search(text))
    noun = re.escape(match[1].rstrip('s')) + 's?'
    quantity = r'(?:\d+(?:\.\d+)?|zero|one|two|three|four|five|six|seven|eight|nine|ten|hundred)'
    return bool(re.search(r'\b' + quantity + r'\s+(?:[a-z-]+\s+){0,2}' + noun + r'\b', text, re.I)
                or re.search(r'\b' + noun + r'\s+(?:(?:count|number|total|size|was|were|is|are|of|=)\s+){0,3}'
                             + quantity + r'\b', text, re.I))


def assess_completion(question, claims, evidence=()):
    parts = question_parts(question)
    text = ' '.join(claims)
    focus = source_focus(question, evidence)
    assessed = len(parts) > 1 or bool(re.search(
        r'\b(?:assign\w*|classif\w*|categor\w*)\b', question, re.I)) or bool(focus)
    if not assessed:
        return {'method': 'lexical_request_coverage', 'assessed': False,
                'completeness_verified': False, 'requested_parts': parts,
                'addressed_parts': int(bool(text)), 'possible_omissions': []}
    answer_tokens = _tokens(text)
    missing = []
    for part in parts:
        tokens = _tokens(part)
        covered = bool(tokens & answer_tokens) and len(tokens & answer_tokens) / max(1, len(tokens)) >= .3
        if re.search(r'\b(?:how many|number of)\b', part, re.I):
            covered = covered and _has_requested_count(part, text)
        if re.search(r'\b(?:bias|limitation\w*|missing)\b', part, re.I):
            covered = covered or bool(re.search(
                r'\b(?:bias\w*|limit\w*|missing|lack\w*|understudied|uncertain\w*|unavailable|not measured|small sample)\b', text, re.I))
        if re.search(r'\b(?:follow[- ]?up|experiment|propose\w*)\b', part, re.I):
            covered = covered or bool(re.search(r'\b(?:follow[- ]?up|propose\w*|experiment\w*|profiling|transcriptomics)\b', text, re.I))
            quotes = [item['quote'] for item in focus
                      if item['intent'] == 'experiment_objective' and item['part'] == part]
            specific = [quote for quote in quotes if SPECIFIC_OBJECTIVE.search(quote)]
            objectives = [objective_terms(quote) for quote in (specific or quotes)]
            objectives = [terms for terms in objectives if len(terms) >= 2]
            if objectives:
                # Shared subject words distributed across other facts are not
                # an experimental endpoint. Prefer distinctive objective words
                # and require them together in one substantive claim.
                context = answer_terms(question)
                targets = [{term for term in terms - context if len(term) > 3} or terms
                           for terms in objectives]
                covered = covered and all(any(
                    len(terms & answer_terms(claim)) >= min(2, len(terms)) and
                    len(terms & answer_terms(claim)) / len(terms) >= .4
                    for claim in claims) for terms in targets)
        if re.match(r'^(?:does|did|has|have|is|are)\b', part, re.I) and re.search(
                r'\b(?:demonstrat\w*|prov\w*|confirm\w*|caus\w*|establish\w*)\b', part, re.I):
            # Shared topic nouns are not a direct answer to a proof/causality question.
            covered = covered and any(re.search(
                r'\b(?:yes|no|not|never|unproven|unknown|untested|unconfirmed|'
                r'demonstrat\w*|confirm\w*|establish\w*)\b', claim, re.I)
                and len(tokens & _tokens(claim)) / max(1, len(tokens)) >= .3 for claim in claims)
        # When a requested classification rule is explicitly numerical in the
        # cited context, a broad "based on frequency" omits that rule.
        if re.search(r'\b(?:assign\w*|classif\w*|categor\w*)\b', part, re.I) and re.search(r'\b(?:groups?|classes|categor\w*)\b', part, re.I):
            expected = set()
            for item in evidence:
                for sentence in re.split(r'(?<=[.!?])\s+', ' '.join(item.text.split())):
                    if re.search(r'\b(?:groups?|classes|categor\w*)\b', sentence, re.I):
                        expected.update(_boundaries(sentence))
            if expected and not expected <= _boundaries(text):
                covered = False
        if not covered:
            missing.append(part)
    return {'method': 'lexical_request_coverage', 'assessed': True, 'completeness_verified': False,
            'requested_parts': parts, 'addressed_parts': len(parts) - len(missing),
            'possible_omissions': missing}
