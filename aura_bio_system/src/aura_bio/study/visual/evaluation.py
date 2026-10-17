"""Evaluator only. No model-produced ground truth or unreviewed quality claims."""
from statistics import mean
from dataclasses import replace


def pin_evaluation_config(config,previous,*,score_only,preflight=None):
    if config.provider!='ollama': return config
    frozen=previous.get('model_digest') if previous else None
    if score_only:
        if not frozen: raise ValueError('Run has no pinned local model digest; use a new run.')
        return replace(config,model_digest=frozen)
    current=preflight(config)
    if frozen is not None and current!=frozen:
        raise ValueError('Local vision model digest changed; use a new run.')
    return replace(config,model_digest=current)


def validate_resume(previous,current):
    if previous!=current: raise ValueError('Frozen manifest/split/source/prompt/config differs; use a new run, never resume it.')


def evaluate_figure_run(records,bank):
    if len({q.get('split') for q in bank})>1: raise ValueError('Evaluate development and holdout separately.')
    questions={q['id']:q for q in bank}
    if len(questions)!=len(bank): raise ValueError('Duplicate evaluation question IDs.')
    if len({r['id'] for r in records})!=len(records): raise ValueError('Duplicate run IDs; preserve old outputs and rescore a separate revision.')
    if any(r['id'] not in questions for r in records): raise ValueError('Run contains questions outside this frozen split.')
    completed=[r for r in records if r.get('state')=='completed']
    reviewed=[r for r in completed if isinstance(r.get('review'),dict)]
    labels_seen,label_found,label_total,label_unmatched=0,0,0,0
    reviewed_labels,reviewed_inventions=0,0
    label_reviews={}
    unmatched_labels=[]
    # The frozen node-label key is not an exhaustive transcription of titles,
    # legends, values and units. An exact-key mismatch cannot establish that
    # model-reported text is absent from the actual source image.
    for r in completed:
        review=r.get('review')
        if not isinstance(review,dict) or review.get('label_review_complete') is not True:
            continue
        invented=review.get('hallucinated_labels')
        if not isinstance(invented,list) or any(not isinstance(v,str) for v in invented):
            raise ValueError('Completed label review requires a hallucinated_labels list of strings.')
        observed=set(r.get('labels',[]))
        invented=set(invented)
        if not invented<=observed:
            raise ValueError('Reviewed hallucinated labels must occur in the model output.')
        fid=questions[r['id']].get('figure_id',r['id'])
        value=(frozenset(observed),frozenset(invented))
        if fid in label_reviews and label_reviews[fid]!=value:
            raise ValueError('Conflicting label reviews for the same figure.')
        label_reviews[fid]=value
    figures=set()
    for r in completed:
        q=questions[r['id']]; fid=q.get('figure_id',q['id'])
        if fid in figures or 'labels' not in r: continue
        figures.add(fid)
        gold=set(q.get('visible_labels') or [v['key'] for v in bank if v.get('figure_id')==fid and v.get('category')=='label' and v.get('key')])
        observed=set(r['labels']); labels_seen+=len(observed)
        if gold:
            label_found+=len(observed&gold)
            label_total+=len(gold)
            unmatched=observed-gold
            label_unmatched+=len(unmatched)
            if unmatched:
                unmatched_labels.append({'figure_id':fid,'labels':sorted(unmatched)})
        if fid in label_reviews:
            reviewed_observed,invented=label_reviews[fid]
            if reviewed_observed!=frozenset(observed):
                raise ValueError('Model labels differ across reviewed copies of a figure.')
            reviewed_labels+=len(reviewed_observed)
            reviewed_inventions+=len(invented)
    def rate(category,field):
        values=[bool(r['review'][field]) for r in reviewed if questions[r['id']].get('category')==category and field in r['review']]
        return mean(values) if values else None
    locators=[bool(r['review']['locator_correct']) for r in reviewed if 'locator_correct' in r['review']]
    latencies=[r['latency_ms'] for r in records if isinstance(r.get('latency_ms'),(float,int))]
    return {'total':len(bank),'attempted':len(records),'completed':len(completed),'errors':sum(r.get('state')!='completed' for r in records),
            'missing':len(bank)-len(records),'manual_reviewed':len(reviewed),'manual_review_pending':len(completed)-len(reviewed),
            'label_recall':label_found/label_total if label_total else None,
            'hallucinated_label_rate':reviewed_inventions/reviewed_labels if reviewed_labels else None,
            'unmatched_label_rate':label_unmatched/labels_seen if labels_seen and label_total else None,
            'unmatched_labels':unmatched_labels,
            'label_reviewed_figures':len(label_reviews),
            'label_review_pending_figures':len(figures-label_reviews.keys()),
            'label_reviewed_observed_labels':reviewed_labels,
            'label_accounting_version':'visible-text-review-v2',
            'authored_labels':label_total,'observed_labels':labels_seen,
            'relation_accuracy':rate('relationship','answer_correct'),'value_accuracy':rate('value','answer_correct'),
            'unsupported_abstention':rate('absent','abstained'),'locator_crop_accuracy':mean(locators) if locators else None,
            'numeric_certification_violations':sum(r.get('numeric_certified') is True for r in records),
            'mean_latency_ms':mean(latencies) if latencies else None,
            'peak_memory_mb':max((r['peak_memory_mb'] for r in records if isinstance(r.get('peak_memory_mb'),(float,int))),default=None),
            'tokens_used':sum(r.get('tokens',0) for r in records),'split':bank[0].get('split') if bank else None,
            'note':'Synthetic fixture coverage does not establish real figure understanding. Unmatched labels are not proven hallucinations: the authored node-label key omits other visible text. Hallucinated-label rate requires complete manual label review; answer/relation/value/abstention scores stay null until reviewed.'}
