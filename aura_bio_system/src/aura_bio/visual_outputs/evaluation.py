"""Frozen-denominator output gates; unreviewed visuals never count as valid."""
from .schema import KINDS


def evaluate_upgrade_results(bank,records,reviews=None):
    reviews=reviews or {};known={case['id'] for case in bank}
    if len(known)!=len(bank): raise ValueError('Duplicate evaluation identity.')
    latest={}
    for row in records:
        if row['id'] not in known: raise ValueError('Unknown evaluation case.')
        latest[row['id']]=row
    positives=[c for c in bank if c['answerable']];controls=[c for c in bank if not c['answerable']]
    valid={c['id'] for c in positives if latest.get(c['id'],{}).get('status')=='ready' and reviews.get(c['id'],{}).get('valid') is True}
    safe_controls={c['id'] for c in controls if latest.get(c['id'],{}).get('status') in {'ready','omitted'} and reviews.get(c['id'],{}).get('control_safe') is True}
    per_kind={k:{'valid':sum(c['id'] in valid for c in positives if c['kind']==k),'total':sum(c['kind']==k for c in positives)} for k in KINDS}
    failed=[]
    if len(positives)!=20 or len(valid)<14: failed.append('positive_coverage')
    failed += [f'kind_{k}' for k,v in per_kind.items() if v['total']!=4 or v['valid']<3]
    if len(controls)!=10 or len(safe_controls)!=10: failed.append('live_controls')
    violations={key:sum(int(latest.get(c['id'],{}).get(key,0))+int(reviews.get(c['id'],{}).get(key,0)) for c in bank)
        for key in ('grounding_violations','provenance_violations','privacy_violations','false_precision_violations')}
    failed += [key for key,value in violations.items() if value]
    return {'total':len(bank),'attempted':len(latest),'positive_total':len(positives),'positive_valid':len(valid),
        'positive_coverage':len(valid)/len(positives) if positives else 0,'controls_total':len(controls),'controls_correct':len(safe_controls),
        'per_kind':per_kind,'manual_review_pending':sum(c['id'] not in reviews for c in bank),
        'by_evaluation_mode':{mode:{'total':sum(c.get('evaluation_mode')==mode for c in bank),
            'valid_positive':sum(c.get('evaluation_mode')==mode and c['id'] in valid for c in positives)} for mode in {c.get('evaluation_mode','unknown') for c in bank}},
        **violations,'release_passed':not failed,'failed_gates':failed,
        'note':'Frozen denominators include omissions, errors, deferred and unattempted cases. Live controls require manual unsafe-assertion review; fixtures are not real-model accuracy.'}


def evaluate_visual_results(bank, records, reviews=None):
    reviews = reviews or {}
    if len({case['id'] for case in bank}) != len(bank): raise ValueError('Duplicate evaluation case.')
    known = {case['id'] for case in bank}
    latest = {}
    for row in records:
        if row['id'] not in known: raise ValueError('Unknown evaluation case.')
        latest[row['id']] = row
    positives = [case for case in bank if case['answerable']]
    controls = [case for case in bank if not case['answerable']]
    valid = {case['id'] for case in positives if latest.get(case['id'], {}).get('status') == 'ready'
             and reviews.get(case['id'], {}).get('valid') is True}
    per_kind = {kind: {'valid': sum(case['id'] in valid for case in positives if case['kind'] == kind),
                       'total': sum(case['kind'] == kind for case in positives)} for kind in KINDS}
    correct_controls = sum(latest.get(case['id'], {}).get('status') == 'omitted' for case in controls)
    violations = {name: sum(int(row.get(name, 0)) for row in latest.values())
                  for name in ('grounding_violations', 'provenance_violations', 'privacy_violations')}
    failed = []
    if len(valid) < 7 or len(positives) != 9: failed.append('positive_coverage')
    failed += [f'kind_{kind}' for kind, counts in per_kind.items() if counts['valid'] < 1]
    if correct_controls != 3 or len(controls) != 3: failed.append('negative_controls')
    failed += [name for name, count in violations.items() if count]
    return {'total': len(bank), 'attempted': len(latest),
            'completed': sum(row.get('status') in {'ready', 'omitted'} for row in latest.values()),
            'failed': sum(row.get('status') == 'failed' for row in latest.values()),
            'missing': len(bank) - len(latest), 'positive_valid': len(valid), 'positive_total': len(positives),
            'positive_coverage': len(valid) / len(positives) if positives else 0.,
            'controls_correct': correct_controls, 'controls_total': len(controls), 'per_kind': per_kind,
            'manual_review_pending': sum(case['id'] not in reviews for case in positives),
            **violations, 'release_passed': not failed, 'failed_gates': failed,
            'note': 'Synthetic contract/rendering tests do not establish real-model accuracy. Valid positives require explicit manual source-fidelity and readability review.'}
