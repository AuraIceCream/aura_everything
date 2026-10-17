"""Bounded request-intent hints copied from evidence, not generated answers."""
import re

from ..retrieval.strategies import question_parts
from ..verification.checkers import content_tokens, STOPWORDS

BIAS = re.compile(r'\b(?:bias\w*|disadvantage\w*|understudied|underestimat\w*|'
                  r'unrepresentative|sampling (?:error|limitation)|selection effect)\b', re.I)
OBJECTIVE = re.compile(r'\b(?:to (?:test|determine|investigate|assess|evaluate|examine|detect|measure)\b|'
                      r'(?:test|reveal|determine|investigate) (?:whether|if|for)\b|'
                      r'presence of\b|look for\b)', re.I)
EXPERIMENT_REQUEST = re.compile(r'\b(?:follow[- ]?up|experiment\w*|propos\w*)\b', re.I)
SPECIFIC_OBJECTIVE = re.compile(r'\b(?:presence of|(?:test|reveal|determine|investigate|'
                                r'assess|examine) (?:whether|if))\b', re.I)


def sentences(text):
    # Join extraction wraps, including end-of-line word hyphenation; no inferred
    # spelling, acronym expansion or numeric changes. Citations keep raw text.
    text = re.sub(r'(?<=\w)-\s*\n\s*(?=\w)', '', text)
    return re.split(r'(?<=[.!?])\s+(?=[A-Z(])', ' '.join(text.split()))


def intent_patterns(question):
    patterns = []
    if re.search(r'\b(?:bias|limitation\w*|caveat\w*|disadvantage\w*)\b', question, re.I):
        patterns.append(('bias', BIAS))
    if EXPERIMENT_REQUEST.search(question):
        patterns.append(('experiment_objective', OBJECTIVE))
    return patterns


def intent_bonus(question, text):
    """Neighbour priority for explicitly requested caveats/endpoints only."""
    return .6 * sum(bool(pattern.search(text)) for _, pattern in intent_patterns(question))


def source_focus(question, evidence, limit=6):
    result, seen, remaining = [], set(), 2400
    for part in question_parts(question):
        terms = content_tokens(part)
        for intent, pattern in intent_patterns(part):
            options = []
            for citation, item in enumerate(evidence, 1):
                for quote in sentences(item.text):
                    if pattern.search(quote):
                        priority = len(terms & content_tokens(quote))
                        if intent == 'experiment_objective':
                            fragment = bool(re.match(r'^presence of\b', quote, re.I))
                            future = bool(re.search(r'\b(?:would|could|might|will|should|aim\w*|intend\w*)\b', quote, re.I))
                            planned = bool(EXPERIMENT_REQUEST.search(quote))
                            if (re.search(r'\bpresence of\b', quote, re.I)
                                    and not (fragment or future or planned)
                                    and not re.search(r'\bto (?:test|determine|investigate|assess|evaluate|examine)\b', quote, re.I)):
                                continue  # A background/result observation is not a proposed endpoint.
                            # A continuation may name the endpoint without repeating
                            # "follow-up experiment". Generic background purposes
                            # must not crowd that fragment out.
                            priority += 3 * bool(SPECIFIC_OBJECTIVE.search(quote))
                            priority += 5 * fragment + 2 * planned
                        options.append((priority, citation, quote))
            options.sort(key=lambda item: -item[0])
            for _, citation, quote in options[:2]:
                key = (intent, citation, quote)
                if key in seen or len(result) >= limit or remaining <= 0:
                    continue
                seen.add(key)
                quote = quote[:min(650, remaining)]
                result.append({'intent': intent, 'part': part, 'citation': citation, 'quote': quote})
                remaining -= len(quote)
    return result


def objective_terms(text):
    match = OBJECTIVE.search(text)
    if not match:
        return set()
    terms = set()
    for word in re.findall(r'[a-z][a-z0-9]+', text[match.end():].lower()):
        if word in STOPWORDS or word in {'would', 'could', 'might', 'may', 'using', 'engage', 'engaging'}:
            continue
        word = word[:-3] if word.endswith('ing') and len(word) > 5 else word.rstrip('s')
        terms.add(word)
    return terms


def answer_terms(text):
    return {word[:-3] if word.endswith('ing') and len(word) > 5 else word.rstrip('s')
            for word in re.findall(r'[a-z][a-z0-9]+', text.lower())}
