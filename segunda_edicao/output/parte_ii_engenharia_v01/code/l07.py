"""Treino e inferência reais em CPU, sobre população sintética declarada."""
import math
import random
import time
from collections import defaultdict
from statistics import mean
from .stats import bootstrap_groups, paired_decision, quantile


def sigmoid(x):
    return 1/(1+math.exp(-max(-700,min(700,x))))


def dataset(seed, groups, rows=4, prefix='T'):
    rng=random.Random(seed); result=[]
    for family in range(groups):
        x1,x2=rng.uniform(-2,2),rng.uniform(-2,2)
        critical=family%4==0
        # Um choque comum por família: reformulações não são independentes.
        y=int(rng.random()<sigmoid(1.4*x1-1.1*x2+.9*x1*x2-.4*critical))
        for r in range(rows):
            result.append({'id':f'{prefix}{family:03}-R{r}','family':f'{prefix}{family:03}',
                'segment':'critical' if critical else 'routine',
                'x':[x1+rng.uniform(-.04,.04),x2+rng.uniform(-.04,.04)],'y':y})
    return result


def features(x, kind):
    if len(x)!=2 or not all(math.isfinite(v) for v in x):raise ValueError('Entrada inválida')
    if kind=='linear':return [1.,*x]
    if kind=='interaction':return [1.,*x,x[0]*x[1]]
    raise ValueError('Candidato desconhecido')


def fit(rows, kind, epochs, rate, l2):
    if not rows or epochs<1 or rate<=0 or l2<0:raise ValueError('Treino inválido')
    if any(r['y'] not in (0,1) for r in rows):raise ValueError('Alvo inválido')
    matrix=[features(r['x'],kind) for r in rows]; w=[0.]*len(matrix[0])
    losses=[]
    for epoch in range(epochs):
        grad=[0.]*len(w); loss=0.
        for row,x in zip(rows,matrix):
            p=sigmoid(sum(a*b for a,b in zip(w,x))); y=row['y']
            loss-=y*math.log(max(p,1e-15))+(1-y)*math.log(max(1-p,1e-15))
            for j,v in enumerate(x):grad[j]+=(p-y)*v
        losses.append(loss/len(rows)+.5*l2*sum(v*v for v in w[1:]))
        for j in range(len(w)):w[j]-=rate*(grad[j]/len(rows)+(l2*w[j] if j else 0))
    return {'kind':kind,'weights':w,'epochs':epochs,'learning_rate':rate,'l2':l2,
            'training_rows':len(rows),'training_families':len({r['family'] for r in rows}),
            'loss_before_updates':losses,'threshold':.5,'precision':'Python float CPU'}


def predict(model, x):
    f=features(x,model['kind'])
    if len(f)!=len(model['weights']):raise ValueError('Pesos incompatíveis')
    p=sigmoid(sum(a*b for a,b in zip(model['weights'],f)))
    return {'probability':p,'prediction':int(p>=model['threshold'])}


def schedule(rows, plan):
    result=[];rng=random.Random(plan['order_seed'])
    for rep in range(plan['repetitions']):
        ids=[r['id'] for r in rows];rng.shuffle(ids)
        for pos,cid in enumerate(ids):
            order=plan['candidates'] if (pos+rep)%2==0 else list(reversed(plan['candidates']))
            for index,kind in enumerate(order):
                result.append({'case':cid,'repetition':rep,'candidate':kind,'position':index,
                    'attempt':f'{cid}-{rep}-{kind}'})
    return result


def infer(models, rows, admitted):
    data={r['id']:r for r in rows}; observations=[]
    for job in admitted:
        start=time.perf_counter_ns()
        try:
            raw=predict(models[job['candidate']],data[job['case']]['x']);status='ok';error=None
        except Exception as exc:raw=None;status='error';error=type(exc).__name__+': '+str(exc)
        elapsed=(time.perf_counter_ns()-start)/1e9
        observations.append({**job,'raw':raw,'status':status,'error':error,'seconds':elapsed})
    return observations


def analyze(rows, observations, plan):
    index={r['id']:r for r in rows};by_case=defaultdict(dict)
    expected=schedule(rows,plan)
    if [{k:o[k] for k in j} for o,j in zip(observations,expected)]!=expected or len(observations)!=len(expected):
        raise ValueError('Admissões ausentes, duplicadas ou fora da ordem')
    for o in observations:
        # Erro de inferência conta como zero na utilidade composta congelada.
        correct=int(o['status']=='ok' and o['raw']['prediction']==index[o['case']]['y'])
        by_case[o['case']].setdefault(o['candidate'],[]).append(correct)
    estimates={}
    for segment in plan['segments']:
        groups=defaultdict(list)
        for cid,entry in by_case.items():
            if segment!='all' and index[cid]['segment']!=segment:continue
            delta=mean(entry['interaction'])-mean(entry['linear'])
            groups[index[cid]['family']].append(delta)
        result=bootstrap_groups(list(groups.values()),plan['bootstrap_draws'],plan['bootstrap_seed'])
        result['decision']=paired_decision(result['interval'],plan['margin']);estimates[segment]=result
    timing={}
    for kind in plan['candidates']:
        own=[o for o in observations if o['candidate']==kind]
        timing[kind]={'admitted':len(own),'failed':sum(o['status']!='ok' for o in own),
            'correct':sum(o['status']=='ok' and o['raw']['prediction']==index[o['case']]['y'] for o in own),
            'p95_seconds':quantile([o['seconds'] for o in own],.95),
            'total_seconds':sum(o['seconds'] for o in own)}
    decisions=[r['decision'] for r in estimates.values()]
    quality='eligible_in_scope' if all(x=='noninferior_in_scope' for x in decisions) else (
        'rejected_in_scope' if 'inferior_in_scope' in decisions else 'inconclusive')
    feasible=timing['interaction']['p95_seconds']<=plan['p95_ceiling_seconds']
    return {'segments':estimates,'timing':timing,'quality_decision':quality,
            'latency_within_local_ceiling':feasible,'selection':quality if feasible else 'latency_rejected',
            'unique_test_rows':len(rows),'unique_test_families':len({r['family'] for r in rows}),
            'repetitions_are_not_independent_samples':True}
