"""Separated sigmoid calibration and split-conformal sets."""
import math,statistics
from laboratorios.parte_iv.core import sigmoid,wilson

def logit(p):
    p=max(1e-9,min(1-1e-9,p));return math.log(p/(1-p))

def fit_calibrator(outputs,rows,epochs=800):
    if [o['id'] for o in outputs]!=[r['id'] for r in rows] or not rows:raise ValueError('calibration_identity')
    # Constrain slope positive: calibration cannot reverse ranking to hide drift.
    a,b=1.,0.;xy=[(logit(o['p']),r['y']) for o,r in zip(outputs,rows)]
    for _ in range(epochs):
        da=sum((sigmoid(a*x+b)-y)*x for x,y in xy)/len(xy)
        db=sum(sigmoid(a*x+b)-y for x,y in xy)/len(xy)
        a=max(.01,a-.03*da);b-=.03*db
    return {'a':a,'b':b,'epochs':epochs,'kind':'positive-slope sigmoid','ids':[r['id'] for r in rows]}

def calibrate(outputs,cal):
    return [dict(o,p=sigmoid(cal['a']*logit(o['p'])+cal['b']),
                 prediction=int(sigmoid(cal['a']*logit(o['p'])+cal['b'])>=.5)) for o in outputs]

def quantile(scores,alpha):
    if not scores or not 0<alpha<1 or any(not 0<=s<=1 for s in scores):raise ValueError('conformal_inputs')
    k=math.ceil((len(scores)+1)*(1-alpha))
    # 1 includes both labels, implementing infinite threshold for bounded scores.
    return {'n':len(scores),'rank':k,'q':sorted(scores)[k-1] if k<=len(scores) else 1.,'alpha':alpha}

def conformal(outputs,rows,alpha=.1):
    if [o['id'] for o in outputs]!=[r['id'] for r in rows]:raise ValueError('conformal_identity')
    return quantile([1-o['p'] if r['y'] else o['p'] for o,r in zip(outputs,rows)],alpha)

def label_set(p,q):return [y for y in (0,1) if (1-p if y else p)<=q]

def coverage(outputs,rows,conf):
    if [o['id'] for o in outputs]!=[r['id'] for r in rows]:raise ValueError('coverage_identity')
    result={}
    for g in ['all','vip','regular']:
        pairs=[(o,r) for o,r in zip(outputs,rows) if g=='all' or r['group']==g]
        sets=[label_set(o['p'],conf['q']) for o,r in pairs];n=len(pairs)
        k=sum(r['y'] in s for (_,r),s in zip(pairs,sets))
        result[g]={'n':n,'covered':k,'coverage':k/n if n else None,'ci':wilson(k,n),
                   'mean_size':statistics.mean(map(len,sets)) if n else None,
                   'empty':sum(not s for s in sets),'single':sum(len(s)==1 for s in sets),
                   'double':sum(len(s)==2 for s in sets)}
    return result

def selective(outputs,rows,threshold,cost=.2):
    accepted=[(o,r) for o,r in zip(outputs,rows) if max(o['p'],1-o['p'])>=threshold]
    n=len(rows);k=sum(int(o['p']>=.5)!=r['y'] for o,r in accepted)
    if len(outputs)!=n or [o['id'] for o in outputs]!=[r['id'] for r in rows]:raise ValueError('selective_identity')
    return {'n':n,'accepted':len(accepted),'errors':k,'coverage':len(accepted)/n if n else None,
            'risk':k/len(accepted) if accepted else None,'risk_ci':wilson(k,len(accepted)),
            'cost_per_admission':(k+cost*(n-len(accepted)))/n if n else None}

def reliability(outputs,rows,bins=5):
    result=[]
    for k in range(bins):
        pairs=[(o['p'],r['y']) for o,r in zip(outputs,rows) if min(bins-1,int(o['p']*bins))==k]
        result.append({'bin':k,'n':len(pairs),'mean_p':statistics.mean(p for p,y in pairs) if pairs else None,
            'observed':statistics.mean(y for p,y in pairs) if pairs else None})
    return result
