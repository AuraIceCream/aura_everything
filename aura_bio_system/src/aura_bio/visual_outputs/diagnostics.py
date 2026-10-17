"""Safe public failure codes; raw private diagnostics are separate."""
STAGES={'generation','proposal','grounding','source','rendering'}
CODES={'invalid_proposal','unbound_fact','resource_deferred','provider_failed','source_unavailable','context_limit'}


def failure_record(stage, code, *, private_detail=''):
    if stage not in STAGES or code not in CODES: raise ValueError('Unknown visual failure code.')
    return {'public':{'stage':stage,'reason_code':code},'private':{'detail':private_detail[:65536]}}
