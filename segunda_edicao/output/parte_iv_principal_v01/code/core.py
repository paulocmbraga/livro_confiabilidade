"""Transparent binary SGD; data clock contract and independent metrics."""
import copy, math, random, statistics, time
from laboratorios.parte_i.common import digest

SCHEMA = {'version':'features-1', 'age_unit':'hour', 'queue_unit':'ticket',
          'channels':['web','phone'], 'order':['bias','age/24','queue/20','phone','vip','age*queue','missing_age']}

def sigmoid(z):
    return 1/(1+math.exp(-max(-700,min(700,z))))

def generate(n, seed, name, start=0, shifted=False):
    rng=random.Random(seed); rows=[]
    for i in range(n):
        age=rng.uniform(0,48); queue=rng.randrange(0,41)
        vip=rng.random()<.25; phone=rng.random()<.4
        a=age/24; q=queue/20
        z=(-3+1.3*a+1.2*q+.5*a*q-.8*vip+.35*phone)
        if shifted:z=3-1.8*a-1.1*q+.5*a*q-.8*vip+.35*phone
        y=int(rng.random()<sigmoid(z)); t=start+i*10
        missing=rng.random()<.06
        rows.append({'id':f'{name}-{i:04d}','group':'vip' if vip else 'regular',
            'at':t,'age':None if missing else age,'unit':'hour',
            'channel':'phone' if phone else 'web','telemetry':rng.random(),
            'history':[{'id':'initial','event':t-20,'available':t-10,'queue':queue},
                       {'id':'late-correction','event':t-15,'available':t+90,'queue':20*y},
                       {'id':'outcome','event':t+120,'available':t+180,'queue':40*y}],
            'y':y,'label_available':t+180})
    return rows

def asof(row, future=False):
    candidates=[v for v in row['history'] if future or
                (v['event']<=row['at'] and v['available']<=row['at'])]
    if not candidates:raise ValueError('no_feature_at_decision')
    return max(candidates,key=lambda v:(v['event'],v['available'],v['id']))

def preprocessor(rows):
    values=[r['age'] for r in rows if r['age'] is not None]
    if not values:raise ValueError('no_observed_age')
    return {'schema':copy.deepcopy(SCHEMA),'median_age':statistics.median(values),
            'fit_ids':digest([r['id'] for r in rows])}

def features(row, prep, future=False, unsafe_unit=False):
    if prep['schema']!=SCHEMA:raise ValueError('schema_identity')
    if row['unit']!='hour' and not unsafe_unit:raise ValueError('unit')
    if row['channel'] not in SCHEMA['channels']:raise ValueError('category')
    if row['group'] not in ['vip','regular']:raise ValueError('group')
    age=prep['median_age'] if row['age'] is None else row['age']
    if isinstance(age,bool) or not isinstance(age,(float,int)) or not math.isfinite(age):raise ValueError('age')
    if not unsafe_unit and not 0<=age<=240:raise ValueError('age_range')
    h=asof(row,future);q=h['queue']
    if isinstance(q,bool) or not isinstance(q,int) or not 0<=q<=400:raise ValueError('queue')
    a=age/24;q=q/20
    return [1,a,q,int(row['channel']=='phone'),int(row['group']=='vip'),a*q,int(row['age'] is None)]

def fit(rows, prep, seed=13, epochs=40, rate=.08, l2=.001, batch=20, initial=None, future=False):
    started=time.perf_counter();rng=random.Random(seed)
    data=[(features(r,prep,future),r['y']) for r in rows]
    weights=list(initial) if initial is not None else [rng.uniform(-.02,.02) for _ in range(7)]
    history=[];order=list(range(len(data)))
    if not data or any(y not in (0,1) for _,y in data):raise ValueError('training_data')
    for epoch in range(epochs):
        rng.shuffle(order)
        for offset in range(0,len(order),batch):
            indices=order[offset:offset+batch];grad=[0.]*7
            for j in indices:
                x,y=data[j];delta=sigmoid(sum(w*v for w,v in zip(weights,x)))-y
                for k,v in enumerate(x):grad[k]+=delta*v/len(indices)
            weights=[w-rate*(g+(l2*w if k else 0)) for k,(w,g) in enumerate(zip(weights,grad))]
        history.append(sum((sigmoid(sum(w*v for w,v in zip(weights,x)))-y)**2 for x,y in data)/len(data))
    return {'weights':weights,'prep':copy.deepcopy(prep),'seed':seed,'epochs':epochs,'l2':l2,
            'rate':rate,'batch':batch,'warm_start':initial is not None,'future_join':future,
            'fit_ids':digest([r['id'] for r in rows]),'fit_data':digest(rows),
            'history_brier':history,'seconds':time.perf_counter()-started}

def predict(model, row, future=None, unsafe_unit=False):
    x=features(row,model['prep'],model['future_join'] if future is None else future,unsafe_unit)
    p=sigmoid(sum(w*v for w,v in zip(model['weights'],x)))
    return {'id':row['id'],'group':row['group'],'x':x,'p':p,'prediction':int(p>=.5)}

def predictions(model,rows):return [predict(model,r) for r in rows]

def auc(y,p):
    # Pairwise reference, ties receive half credit; undefined for one class.
    pos=[v for t,v in zip(y,p) if t==1];neg=[v for t,v in zip(y,p) if t==0]
    return sum((a>b)+.5*(a==b) for a in pos for b in neg)/(len(pos)*len(neg)) if pos and neg else None

def wilson(k,n):
    if not n:return None
    z=1.959963984540054;p=k/n;d=1+z*z/n
    center=(p+z*z/(2*n))/d;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [max(0,center-half),min(1,center+half)]

def metrics(rows, outputs):
    if len(rows)!=len(outputs) or [r['id'] for r in rows]!=[p['id'] for p in outputs]:raise ValueError('prediction_identity')
    if not rows:return {'n':0,'error':None,'brier':None,'log_loss':None,'auc':None,'error_ci':None}
    y=[r['y'] for r in rows];p=[o['p'] for o in outputs]
    if any(not math.isfinite(v) or not 0<=v<=1 for v in p):raise ValueError('probability')
    errors=sum(int(v>=.5)!=t for t,v in zip(y,p));eps=1e-12
    return {'n':len(y),'errors':errors,'error':errors/len(y),'error_ci':wilson(errors,len(y)),
            'brier':statistics.mean((v-t)**2 for t,v in zip(y,p)),
            'log_loss':-statistics.mean(t*math.log(max(eps,v))+(1-t)*math.log(max(eps,1-v)) for t,v in zip(y,p)),
            'auc':auc(y,p)}

def by_group(rows,outputs):
    return {g:metrics([r for r in rows if g=='all' or r['group']==g],
                     [p for p in outputs if g=='all' or p['group']==g]) for g in ['all','vip','regular']}

def identity(model):
    # Runtime timings and learning traces are provenance, not inference identity.
    return digest({k:model[k] for k in ['weights','prep','future_join']})

def promote(model, expected, accessed):
    if identity(model)!=expected:raise ValueError('artifact_mismatch')
    if not set(accessed)<=set(['train','tune']):raise ValueError('test_contamination')
    return {'registered':True,'identity':expected,'operational_release':False}
