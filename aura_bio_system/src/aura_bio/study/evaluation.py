"""Offline scoring only. Gold keys are never imported by the serving pipeline."""
import json
from pathlib import Path


def load_bank(path):
    bank = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    ids = [q['id'] for q in bank]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate evaluation IDs.')
    for q in bank:
        if bool(q['expected_units']) != bool(q['answerable']):
            raise ValueError('Expected source units and answerability disagree.')
    return bank


def validate_resume(previous, config, records):
    if previous.get('config') != config:
        raise ValueError('Run metadata changed: use a new tag; do not mix model/source/code/bank snapshots.')
    ids = [row['id'] for row in records]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate output IDs; repair the output before resuming.')


def evaluate_pack_run(records, bank):
    keys = {q['id']: q for q in bank}
    recalls, covered, locators, abstained, reviewed, citations = [], [], [], [], [], []
    for row in records:
        if row['id'] not in keys or row.get('error'):
            continue
        q = keys[row['id']]
        actual = row.get('retrieved_units', [])
        valid = row.get('retrieved_locators_valid', [])
        supported_units = {unit for unit, ok in zip(actual, valid) if ok is True}
        locators.extend(float(ok is True) for ok in valid)
        expected = set(q['expected_units'])
        if expected:
            recalls.append(len(expected & supported_units) / len(expected))
            covered.append(float(expected <= supported_units))
        elif row.get('decision') is not None:
            abstained.append(float(row['decision'] == 'insufficient_evidence'))
        # Entailment and concept recall are not proof of citation correctness.
        review = row.get('manual_review')
        if review:
            if type(review.get('grounded_answer_correct')) is bool and q['answerable']:
                reviewed.append(float(review['grounded_answer_correct']))
            for value in review.get('citation_correct', []):
                if type(value) is bool:
                    citations.append(float(value))
    mean = lambda values: sum(values) / len(values) if values else None
    return {'completed': len(records), 'bank_questions': len(bank),
            'retrieval_recall_at_k': mean(recalls), 'all_unit_coverage': mean(covered),
            'locator_accuracy': mean(locators), 'citation_correctness': mean(citations),
            'absent_abstention_rate': mean(abstained), 'reviewed_grounded_answer_rate': mean(reviewed),
            'answer_reviews': len(reviewed), 'citation_reviews': len(citations)}
