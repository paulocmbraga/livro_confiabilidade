"""Álgebra exata de eventos e Monte Carlo identificado, sem medir fornecedores."""
from itertools import product
from math import prod, sqrt
import random

def validate(q,r):
    if not all(isinstance(v,(float,int)) and 0<=v<=1 for v in (q,r)):
        raise ValueError('Probabilidades fora de [0,1]')

def analytic(q,r):
    validate(q,r)
    marginal=(1-q)*(1-r)
    return {'series':(1-q)*(1-r)**3,'naive_series':marginal**3,
            'parallel_failure':q+(1-q)*r*r,
            'naive_parallel_failure':(1-marginal)**2,'marginal':marginal,
            'common_path':q,'local_path':(1-q)*(1-(1-r)**3)}

def enumerate_states(q,r):
    validate(q,r); rows=[]
    for common,a,b,c in product((False,True),repeat=4):
        prob=(q if common else 1-q)*prod(r if f else 1-r for f in (a,b,c))
        good=[not(common or f) for f in (a,b,c)]
        rows.append({'bits':[common,a,b,c],'probability':prob,
                     'series':all(good),'parallel_failure':not(good[0] or good[1])})
    return rows

def simulate(q,r,n,seed):
    validate(q,r)
    if type(n) is not int or n<1:raise ValueError('n precisa ser positivo')
    rng=random.Random(seed); counts={'success':0,'common':0,'local':0,'parallel_failure':0}
    marginals=[0,0,0]
    for _ in range(n):
        common=rng.random()<q
        # Consome sempre quatro sorteios; mudanças de ramo não mudam o desenho.
        local=[rng.random()<r for _ in range(3)]
        good=[not(common or f) for f in local]
        key='common' if common else 'local' if any(local) else 'success'
        counts[key]+=1; counts['parallel_failure']+=not(good[0] or good[1])
        for i,x in enumerate(good):marginals[i]+=x
    truth=analytic(q,r)['series']; rate=counts['success']/n
    return {'q':q,'r':r,'n':n,'seed':seed,'counts':counts,'marginals':marginals,
            'series_estimate':rate,'series_true':truth,
            'standard_error_under_model':sqrt(truth*(1-truth)/n),
            'naive_from_observed_marginals':prod(x/n for x in marginals)}
