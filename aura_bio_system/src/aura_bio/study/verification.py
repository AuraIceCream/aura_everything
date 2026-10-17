"""Claim-by-claim pack grounding; lexical fallback is never certification."""
import ast
import math
import operator
import re
from dataclasses import asdict,dataclass,field,replace

from ..verification.checkers import check_citations,check_claim_support,content_tokens
from .provenance import ClaimBasis,source_method
from ..verification.schema import Claim, Certainty, Issue, Support, VerificationReport
from ..verification.verifier import BiologyVerifier


def _verification_windows(claim, passages, max_chars=800):
    """Short, cited source spans for NLI; original chunks remain the audit record."""
    wanted = content_tokens(claim)
    ranked = []
    for passage in passages:
        body = re.sub(r'(?<=\w)-\s+(?=\w)', '-', passage.text)
        body = re.sub(r'\b([a-z]{3,})\d+(?=[.!?])', r'\1', body)
        if not re.search(r'\b(?:tables?|fig(?:ure)?s?\.?)\b', claim, re.I):
            body = re.sub(r'\((?:tables?|fig(?:ure)?s?\.?|refs?\.?)\s*'
                          r'\d+(?:\s*[,–-]\s*\d+)*\)', '', body, flags=re.I)
        body = re.sub(r'\s+', ' ', body).strip()
        sentences = []
        for sentence in re.split(r'(?<=[.!?])\s+(?=[A-Z(])', body):
            if len(sentence) <= max_chars:
                sentences.append(sentence)
                continue
            # OCR/PDF extraction can omit punctuation for an entire page.
            # Overlap word-bounded pieces so a late fact is never truncated.
            words = sentence.split()
            start = 0
            while start < len(words):
                end = start
                length = 0
                while end < len(words) and length + len(words[end]) + bool(length) <= max_chars:
                    length += len(words[end]) + bool(length)
                    end += 1
                if end == start:  # One pathological token cannot consume the loop.
                    sentences.append(words[start][:max_chars])
                    start += 1
                    continue
                sentences.append(' '.join(words[start:end]))
                if end == len(words):
                    break
                start = max(start + 1, end - max(1, (end - start) // 2))
        windows = []
        for start in range(len(sentences)):
            group = []
            for sentence in sentences[start:start + 3]:
                if len(' '.join(group + [sentence])) > max_chars:
                    break
                group.append(sentence)
                windows.append(' '.join(group))
        if not windows:
            windows = [body[:max_chars]]
        for position, window in enumerate(windows):
            overlap = len(wanted & content_tokens(window)) / max(1, len(wanted))
            ranked.append((overlap, -len(window), -position, replace(passage, text=window)))
    ranked.sort(key=lambda row: row[:3], reverse=True)
    first_per_source = []
    seen_sources = set()
    for row in ranked:
        source_id = row[3].chunk_id
        if source_id not in seen_sources:
            first_per_source.append(row[3])
            seen_sources.add(source_id)
    selected = first_per_source[:4]
    if len(selected) < 4:
        for row in ranked:
            if row[3] not in selected:
                selected.append(row[3])
                if len(selected) == 4:
                    break
    return selected[:4]


def _joint_native_window(claim, passages):
    """One bounded joint premise; no inferred sentence joins or foreign sources."""
    if len(passages) != 2 or len({p.chunk_id for p in passages}) != 2:
        return None
    if any(source_method(getattr(p, 'provenance', 'native_text')) != 'native_text'
           for p in passages):
        return None
    scope = {(getattr(p, 'pack_id', None), getattr(p, 'document_id', None)) for p in passages}
    if len(scope) != 1 or not all(next(iter(scope))):
        return None
    fragments = [_verification_windows(claim, [p], max_chars=550)[0].text for p in passages]
    # Explicit excerpt boundaries avoid pretending disjoint spans are contiguous.
    text = '\n'.join(f'Cited excerpt {n}: {fragment}' for n, fragment in enumerate(fragments, 1))
    return replace(passages[0], chunk_id='joint-native-citations', text=text)


def _reversed_via_activation(claim, passages):
    """Catch only an explicit reversal of a source's 'effect via activation of X'."""
    relation = re.search(r'\b([A-Za-z][A-Za-z0-9_-]{1,32})\s+'
                         r'(?:activates?|triggers?|induces?|causes?)\s+'
                         r'([A-Za-z][A-Za-z0-9_-]{1,32})\b', claim, re.I)
    if not relation:
        return False
    effect, activator = (re.escape(value) for value in relation.groups())
    pattern = rf'\b{effect}\b.{{0,160}}\bvia activation of\b.{{0,100}}\b{activator}\b'
    return any(re.search(pattern, re.sub(r'\s+', ' ', passage.text), re.I)
               for passage in passages)


def bounded_arithmetic(expression):
    if len(expression) > 256:
        raise ValueError('Expression too long.')
    try:
        root = ast.parse(expression.strip(), mode='eval')
    except (SyntaxError, RecursionError) as exc:
        raise ValueError('Invalid arithmetic.') from exc
    if sum(1 for _ in ast.walk(root)) > 32:
        raise ValueError('Expression too complex.')
    operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in operations:
            try:
                value = operations[type(node.op)](visit(node.left), visit(node.right))
            except ZeroDivisionError as exc:
                raise ValueError('Division by zero.') from exc
        else:
            raise ValueError('Only literal arithmetic is allowed.')
        if not math.isfinite(value) or abs(value) > 1e12:
            raise ValueError('Non-finite or excessive value.')
        return value
    return visit(root.body)


def claim_pairs(answer):
    # Bold list numbering is formatting, not a standalone assertion. Strip
    # only the marker; the remaining factual heading must still be checked.
    # Requiring whitespace after the period preserves values such as 1.2 mg.
    answer=re.sub(r'^([ \t]*(?:\*\*|__))\d+[.)][ \t]+',r'\1',answer,flags=re.M)
    answer=re.sub(r'^[ \t]*(?:\*\*|__)\d+[.)](?:\*\*|__)[ \t]+','',answer,flags=re.M)
    # Horizontal whitespace only: \s consumed the newline after a trailing
    # citation, moving the previous bullet's period into the next claim.
    normalized = re.sub(r'([.!?])[ \t]*((?:\[\d+\][ \t]*)+)', r' \2\1 ', answer)
    pairs = []
    for line in normalized.splitlines():
        # A valid list marker needs whitespace. A leading -7 or 1.2 is data.
        line = re.sub(r'^[ \t]*(?:[-*•]|\d+[.)]|#+)[ \t]+', '', line).strip()
        if not line or re.fullmatch(r'(?:key points|summary|answer|working|sources|references):?', line, re.I):
            continue
        # Closed, non-factual framing only. Never exempt arbitrary text starting
        # with "Based on", "Note", or "Summary": it may contain a false claim.
        if re.fullmatch(r'Based on the (?:provided|selected) (?:source |study )?'
                        r'material, here is the (?:answer|(?:guided )?explanation):', line, re.I):
            continue
        for span in re.split(r'(?<=[.!?])\s+(?=[A-Z(])', line):
            text = re.sub(r'\s+([.!?])', r'\1', re.sub(r'\[\d+\]', '', span)).strip()
            if text and not text.endswith('?'):
                pairs.append((text, span))
    return pairs


def _native_sentence_matches(text, passages):
    """Confirm a transcription, not truth, paraphrase, or substring entailment."""
    def normalize(value):
        value = re.sub(r'\*\*(?=\S)(.+?)\*\*', r'\1', value)
        value = re.sub(r'`([^`\n]+)`', r'\1', value)
        # Case is significant in units (mg/Mg), symbols and identifiers.
        return ' '.join(value.split()).rstrip('.!?')

    wanted = normalize(text)
    if len(content_tokens(wanted)) < 2:
        return []
    matches = []
    for passage in passages:
        # Context can explicitly retract an otherwise verbatim sentence.
        if re.search(r'\b(?:false|incorrect|erroneous|mistaken|not true)\b', passage.text, re.I):
            continue
        # Extraction line breaks are not sentence boundaries: a following line
        # may contain "only if ...". Join before splitting complete statements.
        body = ' '.join(re.sub(r'^[ \t]*(?:[-*•]|\d+[.)])[ \t]+', '', line)
                        for line in passage.text.splitlines()
                        if not re.match(r'^\s*#', line))
        if any(normalize(sentence) == wanted for sentence, _ in claim_pairs(body)):
            matches.append(passage)
    return matches


def derived_check(text, cited, question):
    """Only an explicit, source/question-premised equality earns a numeric check."""
    match = re.fullmatch(r'Derived:\s*(.+?)\s*=\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*([A-Za-zµ°/]+)?[.]?', text, re.I)
    if not match or not cited:
        return None
    left, raw_result, right_unit = match.groups()
    normalize = lambda value: re.sub(r'\s+', '', value).casefold()
    premises = [question or ''] + [item.text for item in cited]
    if not any(normalize(left) in normalize(premise) for premise in premises):
        return None  # Do not bind unrelated numbers elsewhere in the passages.
    try:
        if right_unit:
            unit_input = re.fullmatch(r'([+-]?\d+(?:\.\d+)?)\s*([A-Za-zµ°/]{1,24})', left)
            if not unit_input or len(right_unit) > 24:
                return None
            import pint
            expected = float(pint.UnitRegistry().Quantity(float(unit_input[1]), unit_input[2]).to(right_unit).magnitude)
        else:
            expected = float(bounded_arithmetic(left))
        stated = float(raw_result)
        if not all(math.isfinite(value) and abs(value) <= 1e12 for value in (expected, stated)):
            return None
    except Exception:
        # Pint's dimensionality/undefined-unit errors are safe failures, never permission to guess.
        return None
    return {'solver': 'source_arithmetic_or_units', 'quantity': left, 'expected': expected,
            'stated': stated, 'verdict': 'correct' if math.isclose(stated, expected, rel_tol=1e-6, abs_tol=1e-9) else 'incorrect',
            'working': f'{left} = {expected:g}',
            'inputs_from': [item.chunk_id for item in cited if normalize(left) in normalize(item.text)]}


@dataclass
class StudyReport(VerificationReport):
    claim_basis: list[ClaimBasis] = field(default_factory=list)
    interpreted_coverage: float = 0

    def decision(self):
        if self.checker_status.get('pack_grounding') == 'insufficient':
            return 'insufficient_evidence'
        if not self.blocking and any(b.verification_kind in {'native_unverified','interpreted','ocr_transcribed','user_annotated'} for b in self.claim_basis):
            return 'degraded'
        result = super().decision()
        return 'degraded' if result == 'accept' and self.support_backend != 'nli' else result

    def as_dict(self):
        payload=super().as_dict()
        payload.update(claim_basis=[asdict(b) for b in self.claim_basis],interpreted_coverage=round(self.interpreted_coverage,3))
        for claim,basis in zip(payload['claims'],self.claim_basis):
            claim.update(verification_kind=basis.verification_kind,inputs_verified=basis.inputs_verified)
        return payload


class StudyVerifier(BiologyVerifier):
    def before_generation(self):
        """NLI and Ollama use the same system commit, even on different devices."""
        from ..resources import available_memory_mb
        from ..verification.entailment import release_default_scorer
        from .model_lifecycle import release_retrieval_weights
        before = available_memory_mb()
        released = release_default_scorer() if self.use_entailment else False
        retrieval_released = release_retrieval_weights()
        return {'nli_released': released, 'retrieval_models_released': retrieval_released,
                'before': before, 'after': available_memory_mb()}

    def __init__(self, domain='general', use_entailment=True):
        super().__init__(check_terms=False, check_processes=domain == 'biology',
                         check_numbers=domain == 'biology', check_biochemistry=domain == 'biology',
                         check_ontology=False, use_entailment=use_entailment)
        self.domain = domain

    def verify(self, answer, evidence, route=None, question=None):
        return self._verify_pairs(answer, claim_pairs(answer), evidence, route, question)

    def verify_claims(self, claims, evidence, route=None, question=None):
        """Check supplied claim boundaries and citation IDs without prose splitting."""
        pairs = [(item.claim, item.claim + ' ' + ' '.join(f'[{n}]' for n in item.cite_ids))
                 for item in claims]
        answer = '\n'.join(span for _, span in pairs)
        return self._verify_pairs(answer, pairs, evidence, route, question)

    def _verify_pairs(self, answer, pairs, evidence, route=None, question=None):
        report = StudyReport()
        report.checker_status.update(scope='pack_only', biology_adapter=self.domain,
                                     terminology='disabled_pack', ontology='disabled_pack')
        if not evidence or not pairs:
            report.checker_status['pack_grounding'] = 'insufficient'
            report.issues.append(Issue('study', 'pack_unsupported_claim', 'Retrieve supporting material before answering.', 'error'))
            return report
        report.citation_coverage, issues = check_citations(answer, len(evidence))
        report.issues.extend(issues)
        backends = []
        for index, (text, span) in enumerate(pairs):
            indices = [int(n) for n in re.findall(r'\[(\d+)\]', span)]
            cited = [evidence[n - 1] for n in indices if 1 <= n <= len(evidence)]
            native=[e for e in cited if source_method(getattr(e,'provenance','native_text'))=='native_text']
            derived=[e for e in cited if e not in native]
            # A nearby native passage is not an independent support source. Scope NLI to relevant citations.
            tokens=content_tokens(text)
            relevant=[e for e in native if len(tokens & content_tokens(e.text))/max(1,len(tokens))>=.4]
            basis_kind='unsupported'; inputs_verified=False; supporting=[]
            exact_native = _native_sentence_matches(text, native)
            calculation = derived_check(text, cited, question or (route.query if route else ''))
            if calculation is not None:
                input_sources=[e for e in cited if e.chunk_id in calculation['inputs_from']]
                inputs_verified=bool(input_sources) and all(e in native for e in input_sources)
                calculation['inputs_verified']=inputs_verified
                calculation['conditional']=not inputs_verified
                report.numerical.append(calculation)
                backends.append('deterministic')
                claim = Claim(index, text, (Support.SUPPORTED if inputs_verified else Support.UNVERIFIABLE) if calculation['verdict'] == 'correct' else Support.CONTRADICTORY,
                              Certainty.ESTABLISHED, 1.0, tuple(item.chunk_id for item in cited))
                supporting=cited
                basis_kind='native_unverified' if inputs_verified or not derived else _derived_kind(derived)
                if calculation['verdict'] == 'incorrect':
                    report.issues.append(Issue('numerical', 'wrong_value', calculation['working'], 'error', text))
            elif not cited:
                claim = Claim(index, text, Support.UNSUPPORTED, Certainty.ESTABLISHED, 0.0)
            elif native:
                local = VerificationReport()
                matches = self._support([text], _verification_windows(text, native), local)
                report.issues.extend(local.issues)
                backends.append(local.support_backend)
                claim = replace(matches[0], index=index) if matches else Claim(index, text, Support.UNSUPPORTED, Certainty.ESTABLISHED, 0.0)
                if (self.use_entailment and local.support_backend == 'nli'
                        and claim.support not in {Support.SUPPORTED, Support.CONTRADICTORY}):
                    joint = _joint_native_window(text, native)
                    if joint is not None:
                        combined = VerificationReport()
                        combined_matches = self._support([text], [joint], combined)
                        report.issues.extend(combined.issues)
                        if (combined.support_backend == 'nli' and combined_matches
                                and combined_matches[0].support in {Support.SUPPORTED, Support.CONTRADICTORY}):
                            claim = replace(combined_matches[0], index=index,
                                            evidence_chunk_ids=tuple(p.chunk_id for p in native))
                            report.checker_status['joint_native_citations'] = 'bounded_same_document_nli'
                if exact_native and claim.support != Support.CONTRADICTORY and (
                        claim.support != Support.SUPPORTED or local.support_backend != 'nli'):
                    # A neutral NLI result cannot erase an exact transcription.
                    # Keep confident contradictions blocking. This fallback is
                    # NOT semantic, independent truth, or numeric certification.
                    claim = Claim(index, text, Support.SUPPORTED, Certainty.ESTABLISHED,
                                  1.0, tuple(item.chunk_id for item in exact_native))
                    basis_kind='native_unverified'; supporting=exact_native
                    backends[-1] = 'native_text_span'
                    report.checker_status['native_text_span'] = 'matched_not_semantic_verification'
                elif claim.support==Support.SUPPORTED:
                    inputs_verified=local.support_backend=='nli'
                    basis_kind='native_verified' if inputs_verified else 'native_unverified'
                    supporting=[e for e in native if e.chunk_id in claim.evidence_chunk_ids]
                elif derived and claim.support!=Support.CONTRADICTORY:
                    claim,basis_kind,supporting=_interpret_claim(index,text,derived)
            elif derived:
                claim,basis_kind,supporting=_interpret_claim(index,text,derived)
                backends.append('interpreted')
            else:
                claim=Claim(index,text,Support.UNSUPPORTED,Certainty.ESTABLISHED,0)
            if cited and _reversed_via_activation(text, native):
                claim = replace(claim, support=Support.CONTRADICTORY, score=0.0)
                basis_kind = 'unsupported'; inputs_verified = False; supporting = []
                report.issues.append(Issue('study', 'reversed_causal_direction',
                    'The cited source places the activation upstream of this effect.', 'error', text))
            report.claims.append(claim)
            records=tuple({'chunk_id':e.chunk_id,'provenance':getattr(e,'provenance','native_text'),
                           'provenance_details':getattr(e,'provenance_details',{}),
                           'pack_id':getattr(e,'pack_id',None),'document_id':getattr(e,'document_id',None),
                           'unit_ids':list(getattr(e,'unit_ids',()))} for e in supporting)
            report.claim_basis.append(ClaimBasis(index,records,basis_kind,inputs_verified))
            if claim.support not in {Support.SUPPORTED,Support.UNVERIFIABLE}:
                report.issues.append(Issue('study', 'pack_unsupported_claim', 'Remove this claim or support it with its own relevant inline citation: ' + text[:180], 'error', text))
        if backends and all(b == 'nli' for b in backends):
            report.support_backend = 'nli'
        elif backends and all(b == 'native_text_span' for b in backends):
            report.support_backend = 'native_text_span'
        elif backends and all(b in {'nli', 'native_text_span'} for b in backends):
            report.support_backend = 'mixed_native_text_span_nli'
        else:
            report.support_backend = 'lexical'
        report.grounded_fraction = sum(b.verification_kind=='native_verified' for b in report.claim_basis) / len(report.claims)
        report.interpreted_coverage=sum(b.verification_kind in {'interpreted','ocr_transcribed','user_annotated'} for b in report.claim_basis)/len(report.claims)
        if report.support_backend in {'native_text_span', 'mixed_native_text_span_nli'}:
            report.checker_status['semantic_support'] = 'native_transcription_not_independent_verification'
            report.issues.append(Issue('study', 'native_transcription_only',
                'Exact native-text matches confirm transcription, not independent factual or numeric verification.', 'warning'))
        elif report.support_backend != 'nli':
            report.checker_status['semantic_support'] = 'unavailable_lexical_fallback'
            report.issues.append(Issue('study', 'semantic_support_unavailable', 'Lexical relevance is not semantic proof; this answer is degraded.', 'warning'))
        if self.domain == 'biology' and not any(getattr(e,'provenance','native_text')!='native_text' for e in evidence):
            biological = super().verify(answer, evidence, route, question)
            report.issues.extend(biological.issues)
            report.numerical.extend(biological.numerical)
        else:
            report.checker_status.update(processes='disabled_general_pack', biochemistry='disabled_general_pack',
                                         numerical='source_backed_arithmetic_units_unrecognised_unverified')
        return report


def _derived_kind(passages):
    methods={getattr(e,'provenance','native_text') for e in passages}
    return 'interpreted' if 'vlm' in methods else 'ocr_transcribed' if 'ocr' in methods else 'user_annotated'


def _interpret_claim(index,text,passages):
    # Alignment permits delivery of an interpretation, not verification of its truth.
    matches=check_claim_support([text],passages)
    numeric=set(re.findall(r'(?<![\w.])[+-]?\d+(?:\.\d+)?(?!\w)',text))
    source_numbers=set(re.findall(r'(?<![\w.])[+-]?\d+(?:\.\d+)?(?!\w)',' '.join(e.text for e in passages)))
    if matches and matches[0].support==Support.SUPPORTED and numeric<=source_numbers:
        return (Claim(index,text,Support.UNVERIFIABLE,Certainty.ESTABLISHED,matches[0].score,tuple(e.chunk_id for e in passages),tuple(sorted(numeric))),
                _derived_kind(passages),passages)
    return Claim(index,text,Support.UNSUPPORTED,Certainty.ESTABLISHED,0), 'unsupported',[]
