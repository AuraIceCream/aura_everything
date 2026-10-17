"""Hand-authored native and interpreted evidence for visual-output tests."""
from types import SimpleNamespace
from aura_bio.study.claims import StructuredClaim, ClaimDraft, ClaimBlock
from aura_bio.study.searcher import StudyEvidence


TEXT = 'ORION activates VEGA. VEGA may inhibit LUMEN. ORION precedes VEGA. Group A: 33 cells. Group B: 38 cells.'


def context(method='native_text', removed=False):
    try:
        from aura_bio.visual_outputs.context import build_visual_context
    except ImportError:
        raise AssertionError('Retained visual context is not implemented')
    claims = (StructuredClaim('c1', 'ORION activates VEGA.', (1,)),
              StructuredClaim('c2', 'VEGA may inhibit LUMEN.', (1,)),
              StructuredClaim('c3', 'ORION precedes VEGA.', (1,)),
              StructuredClaim('c4', 'Group A: 33 cells.', (1,)),
              StructuredClaim('c5', 'Group B: 38 cells.', (1,)))
    draft = ClaimDraft(1, claims, tuple(ClaimBlock('claim', ref=c.id) for c in claims))
    ids = ['c1', 'c3', 'c4', 'c5'] if removed else [c.id for c in claims]
    kind = {'native_text': 'native_verified', 'vlm': 'interpreted',
            'ocr': 'ocr_transcribed', 'user_annotation': 'user_annotated'}[method]
    delivered = SimpleNamespace(delivered_ids=ids, verification={'claim_basis': [
        {'claim_index': n, 'verification_kind': kind, 'inputs_verified': method == 'native_text',
         'supporting_provenance': [{'chunk_id': 'chunk1', 'provenance': method}]}
        for n, _ in enumerate(ids)]})
    evidence = StudyEvidence('chunk1', 'doc1', 'Fixture', None, TEXT, None, None, 'pack_sparse', 1.,
        pack_id='a'*32, document_id='b'*32, unit_ids=('d'*32,), provenance=method, generation=1)
    return build_visual_context(draft, delivered, [evidence])


def diagram():
    return {'version': 1, 'id': 'v1', 'kind': 'diagram', 'title': 'ORION pathway',
            'description': 'ORION activates VEGA.', 'payload': {
                'nodes': [{'id': 'n1', 'label': 'ORION', 'claim_ids': ['c1']},
                          {'id': 'n2', 'label': 'VEGA', 'claim_ids': ['c1']}],
                'edges': [{'from_id': 'n1', 'to_id': 'n2', 'relation': 'activates',
                           'label': 'activates', 'claim_ids': ['c1']}]}}


def binding(text):
    start = TEXT.index(text)
    return {'cite_id': 1, 'start': start, 'end': start + len(text)}


def plot():
    return {'version': 1, 'id': 'v2', 'kind': 'plot', 'title': 'Cell counts',
        'description': 'Group A: 33 cells; Group B: 38 cells.', 'payload': {
            'chart_type': 'bar', 'x_label': 'Group', 'y_label': 'Count', 'unit': 'cells',
            'series': [{'id': 's1', 'label': 'Cell counts', 'unit': 'cells', 'points': [
                {'group': 'Group A', 'value': '33', 'claim_ids': ['c4'],
                 'bindings': {'group': binding('Group A'), 'value': binding('33'), 'unit': binding('cells')}},
                {'group': 'Group B', 'value': '38', 'claim_ids': ['c5'],
                 'bindings': {'group': binding('Group B'), 'value': binding('38'),
                              'unit': {'cite_id': 1, 'start': TEXT.rindex('cells'), 'end': TEXT.rindex('cells')+5}}}]}]}}
