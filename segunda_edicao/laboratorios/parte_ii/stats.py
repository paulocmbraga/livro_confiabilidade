"""Instrumentos pequenos, com unidade amostral explícita e entradas validadas."""
import math
import random
from statistics import NormalDist, mean


def proportion(k, n):
    if type(n) is not int or type(k) is not int or not 0 <= k <= n or n == 0:
        raise ValueError('Exige contagens inteiras e denominador positivo')
    return k / n


def wilson(k, n, alpha=.05):
    p = proportion(k, n)
    if not 0 < alpha < 1:
        raise ValueError('alpha inválido')
    z = NormalDist().inv_cdf(1 - alpha / 2)
    scale = 1 + z*z/n
    center = (p + z*z/(2*n)) / scale
    radius = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / scale
    return [max(0., center-radius), min(1., center+radius)]


def zero_upper(n, alpha=.05):
    proportion(0, n)
    if not 0 < alpha < 1:
        raise ValueError('alpha inválido')
    return -math.expm1(math.log(alpha)/n)


def minimum_zero_sample(limit, alpha=.05):
    if not 0 < limit < 1 or not 0 < alpha < 1:
        raise ValueError('Probabilidade inválida')
    return math.ceil(math.log(alpha)/math.log1p(-limit))


def quantile(values, p):
    if not values or not 0 <= p <= 1 or not all(math.isfinite(v) for v in values):
        raise ValueError('Quantil sem dados finitos ou p inválido')
    s = sorted(values); rank = (len(s)-1)*p
    lo = int(rank); hi = min(lo+1, len(s)-1)
    return s[lo] + (rank-lo)*(s[hi]-s[lo])


def bootstrap_groups(groups, draws=3000, seed=601, alpha=.05):
    """Famílias equiponderadas; preserva o vetor de cada família sorteada."""
    if len(groups) < 2 or any(not g for g in groups) or draws < 2 or not 0 < alpha < 1:
        raise ValueError('Bootstrap exige >=2 grupos não vazios e sorteios')
    if not all(math.isfinite(x) for g in groups for x in g):
        raise ValueError('Valor não finito')
    means = [mean(g) for g in groups]; rng = random.Random(seed)
    samples = [mean(rng.choices(means, k=len(means))) for _ in range(draws)]
    return {'estimate':mean(means), 'interval':[quantile(samples,alpha/2),
             quantile(samples,1-alpha/2)], 'groups':len(groups), 'draws':draws,
             'seed':seed, 'estimand':'equal family means'}


def missing_bounds(success, failure, missing):
    for n in (success,failure,missing):
        if type(n) is not int or n < 0:raise ValueError('Contagem inválida')
    n = success+failure+missing
    return [proportion(success,n), proportion(success+missing,n)]


def paired_decision(interval, margin):
    lo,hi=interval
    if not math.isfinite(lo+hi) or lo>hi or margin<=0:raise ValueError('Intervalo/margem inválidos')
    if lo > -margin:return 'noninferior_in_scope'
    if hi < -margin:return 'inferior_in_scope'
    return 'inconclusive'


def binomial_two_sided_half(k,n):
    proportion(k,n)
    tail=sum(math.comb(n,i) for i in range(min(k,n-k)+1))/(2**n)
    return min(1.,2*tail)


def sequential(seed, trials, looks, alpha=.05):
    if trials<1 or not looks or sorted(set(looks))!=looks or looks[0]<1:
        raise ValueError('Plano de consultas inválido')
    if not 0<alpha<1:raise ValueError('alpha inválido')
    rng=random.Random(seed); cache={(n,k):binomial_two_sided_half(k,n)
        for n in looks for k in range(n+1)}
    rows=[]
    for trial in range(trials):
        s=0; checks=[]
        for n in range(1,looks[-1]+1):
            s+=rng.random()<.5
            if n in looks:checks.append({'n':n,'success':s,'p':cache[n,s]})
        rows.append({'trial':trial,'looks':checks,'fixed':checks[-1]['p']<=alpha,
            'opportunistic':any(x['p']<=alpha for x in checks),
            'bonferroni':any(x['p']<=alpha/len(looks) for x in checks)})
    return rows


def coverage(seed=602, trials=1000, groups=20, repeats=5, truth=.8):
    rng=random.Random(seed); rows=[]
    for trial in range(trials):
        k=sum(rng.random()<truth for _ in range(groups))
        naive=wilson(k*repeats,groups*repeats); correct=wilson(k,groups)
        rows.append({'trial':trial,'group_successes':k,'naive':naive,'group':correct,
            'naive_covers':naive[0]<=truth<=naive[1],
            'group_covers':correct[0]<=truth<=correct[1]})
    return rows


def bounded_mean_interval(values, alpha=.05, low=-1., high=1.):
    """Hoeffding bilateral para médias de unidades independentes limitadas."""
    if not values or not 0<alpha<1 or high<=low or any(not low<=v<=high for v in values):
        raise ValueError('Valores ou limites inválidos')
    radius=(high-low)*math.sqrt(math.log(2/alpha)/(2*len(values)))
    center=mean(values)
    return [max(low,center-radius),min(high,center+radius)]


def selection_optimism(seed=705, trials=1000, candidates=20, development=40, final=200):
    """Controle D: candidatas fictícias igualmente boas, não inferências reais."""
    rng=random.Random(seed);rows=[]
    for t in range(trials):
        dev=[sum(rng.random()<.75 for _ in range(development)) for _ in range(candidates)]
        winner=max(range(candidates),key=lambda k:dev[k])
        held=sum(rng.random()<.75 for _ in range(final))
        rows.append({'trial':t,'dev_counts':dev,'winner':winner,'selected_dev':dev[winner]/development,
                     'independent_final_count':held,'independent_final_rate':held/final})
    return rows
