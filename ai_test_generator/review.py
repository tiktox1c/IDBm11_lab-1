"""Явная ручная проверка: структура проверяется программой, смысл — человеком."""
import copy
import hashlib
import json
from .validation import validate_question

LABELS={'review':'Требует проверки','checked':'Проверено','corrected':'Исправлено'}
FIELDS=('type','prompt','options','items','left','right','answer','acceptable_answers','attachments','source_quote')

def fingerprint(q):
    body={k:q[k] for k in FIELDS if k in q}
    return hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def question_status(q):
    state=q.get('review_status','review')
    if state not in LABELS or state!='review' and q.get('review_fingerprint')!=fingerprint(q):
        state='review'
    return LABELS[state]

def return_to_review(q):
    q.update(review_status='review',manual_confirmed=False,review_required=True)
    q.pop('review_fingerprint',None)

def _set(q,state):
    validate_question(q,grounding=False)
    q.update(review_status=state,manual_confirmed=True,review_required=False,review_reasons=[])
    q['review_fingerprint']=fingerprint(q)

def confirm_question(q):
    _set(q,'checked')

def save_correction(q,candidate):
    validate_question(candidate,grounding=False)
    changed=fingerprint(q)!=fingerprint(candidate)
    previous=question_status(q)
    updated=copy.deepcopy(candidate)
    if changed:
        updated['edited']=True
        _set(updated,'corrected')
    elif previous=='Требует проверки':
        return_to_review(updated)
    q.clear();q.update(updated)
