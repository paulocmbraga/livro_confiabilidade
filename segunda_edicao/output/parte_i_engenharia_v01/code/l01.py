"""Classificação da tarefa separada do HTTP e do conhecimento do cliente."""
from collections import Counter

STATES = ('success','failure','abstained','pending','unknown')

def assess(case):
    """Oráculo de tarefa: fixtures explícitas de fonte, destino e observabilidade."""
    observed=case['observed']; contract=case['contract']
    violations=[]
    if observed['destination_known'] and observed['foreign_effect']: violations.append('foreign_effect')
    if observed['effect_count'] is not None and observed['effect_count']>1: violations.append('duplicate')
    if not contract['authorized'] and observed['effect_count']:
        violations.append('unauthorized_effect')
    if violations:
        state='failure'
    elif observed['in_flight']:
        state='pending'
    elif not observed['destination_known']:
        state='unknown'
    elif observed['refused'] and not observed['effect_count']:
        state='abstained' if not contract['authorized'] else 'failure'
    elif (contract['authorized'] and observed['text_supported'] and
          observed['effect_count']==contract['expected_effects'] and
          observed['deadline_met']):
        state='success'
    else:
        state='failure'
    return {'id':case['id'],'segment':case['segment'],'state':state,
            'http_accept':case['http']==200,'violations':violations,
            'client_state':case['client_state']}

def summarize(cases):
    ids=[x['id'] for x in cases]
    if len(ids)!=len(set(ids)): raise ValueError('Admissão duplicada')
    rows=[assess(x) for x in cases]; counts=Counter(x['state'] for x in rows)
    matrix={str(http):{s:sum(x['http_accept']==http and x['state']==s for x in rows)
                       for s in STATES} for http in (False,True)}
    return {'admitted':len(rows),'states':{s:counts[s] for s in STATES},
            'false_success':sum(x['http_accept'] and x['state']!='success' for x in rows),
            'false_negative':sum(not x['http_accept'] and x['state']=='success' for x in rows),
            'critical_violations':sum(bool(x['violations']) for x in rows),
            'matrix':matrix,'rows':rows}
