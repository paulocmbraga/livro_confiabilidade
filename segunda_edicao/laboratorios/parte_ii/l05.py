"""Divisões de catálogo sintético e protocolo humano ainda não coletado."""
from collections import Counter
import random


def catalog():
    rows=[]
    for family in range(24):
        for entity in range(2):
            for month in range(1,4):
                for paraphrase in range(2):
                    rows.append({'id':f'F{family:02}-E{entity}-M{month}-R{paraphrase}',
                        'family':f'F{family:02}','entity':f'F{family:02}-E{entity}',
                        'month':month,'segment':'critical' if family>=18 else 'routine',
                        'text':f'Caso sintético {family}, entidade {entity}, mês {month}, formulação {paraphrase}.',
                        'source':'authorial synthetic generator v1; no people or third-party dataset'})
    return rows


def split(rows, unit, seed=505):
    if unit=='time':
        return [r for r in rows if r['month']<3],[r for r in rows if r['month']==3]
    if unit not in ('id','entity','family'):raise ValueError(unit)
    keys=sorted({r[unit] for r in rows});random.Random(seed).shuffle(keys)
    cut=set(keys[:int(.75*len(keys))])
    return [r for r in rows if r[unit] in cut],[r for r in rows if r[unit] not in cut]


def audit_split(train,test):
    if len({r['id'] for r in train+test})!=len(train)+len(test):
        raise ValueError('Identidade repetida ou linha sobreposta')
    return {'train_rows':len(train),'test_rows':len(test),
        'entity_overlap':sorted({r['entity'] for r in train}&{r['entity'] for r in test}),
        'family_overlap':sorted({r['family'] for r in train}&{r['family'] for r in test}),
        'train_segments':dict(Counter(r['segment'] for r in train)),
        'test_segments':dict(Counter(r['segment'] for r in test)),
        'train_max_month':max(r['month'] for r in train),
        'test_min_month':min(r['month'] for r in test)}


def run(rows):
    active=[r for r in rows if int(r['family'][1:])<20]
    reserve=[r for r in rows if int(r['family'][1:])>=20]
    outputs={}
    for unit in ('id','entity','family','time'):
        train,test=split(active,unit)
        outputs[unit]={'train_ids':[r['id'] for r in train],
                       'test_ids':[r['id'] for r in test],**audit_split(train,test)}
    return {'total':len(rows),'active':len(active),'reserve_ids':[r['id'] for r in reserve],
            'splits':outputs,'human_review':'pending','reserve_custodian':None,
            'reserve_unseen_by_development':False,
            'scope':'Synthetic families held aside structurally, not an independently sealed final test.'}


def validate_human(form):
    if not form.get('reviewer') or not form.get('independence_statement'):
        raise ValueError('Revisor e declaração ausentes')
    if not form.get('items') or any(x.get('verdict') not in ('adequate','inadequate','uncertain')
                                  or not x.get('reason') for x in form['items']):
        raise ValueError('Coleta incompleta')
    return {'complete_form':True,'independence_verified':False}
