"""Contratos puros usados pela bancada e pelos exemplos impressos."""
from collections import Counter
import math, threading
from laboratorios.parte_i.common import save,load,sha,digest,seal,check_manifest


def percentile(values, q):
    if not 0 < q <= 1: raise ValueError('quantil')
    values=sorted(values)
    return values[math.ceil(q*len(values))-1] if values else None


def cohort(events, now, window, lag=12, segment=None):
    """Tempo em minutos virtuais; intervalos [corte-janela,corte)."""
    cutoff=now-lag
    rows=[e for e in events if cutoff-window<=e['at']<cutoff
          and (segment is None or e['segment']==segment)]
    observed=[e for e in rows if e['observed']]
    known=[e for e in observed if e['label_at'] is not None and e['label_at']<=now]
    good=sum(e['good'] for e in known);bad=len(known)-good;n=len(rows)
    return dict(n=n,observed=len(observed),known=len(known),good=good,bad=bad,
        unknown=n-len(known),coverage=len(known)/n if n else None,
        availability=sum(e['http_ok'] for e in rows)/n if n else None,
        quality_known=good/len(known) if known else None,
        quality_lower=good/n if n else None,quality_upper=(n-bad)/n if n else None)


def burn(view, target=.99, minimum=20, coverage=.95):
    if not 0<target<1: raise ValueError('alvo')
    if view['n']<minimum or view['coverage']<coverage:return None
    return view['bad']/view['known']/(1-target)


def alert(events, now, target=.99):
    long=cohort(events,now,30);short=cohort(events,now,5)
    a,b=burn(long,target),burn(short,target)
    return dict(long=long,short=short,long_burn=a,short_burn=b,
        quality=a is not None and b is not None and a>=6 and b>=6,
        observation=short['n']>=20 and short['coverage']<.95)


def useful_cost(cost, useful):
    if cost<0 or useful<0:raise ValueError('custo/denominador')
    return cost/useful if useful else None


def cache_key(tenant, prompt, model, policy, schema):
    return digest(dict(tenant=tenant,prompt=prompt,model=model,policy=policy,schema=schema))


class Budget:
    """Unidades monetárias inteiras; desconhecido conserva a reserva."""
    def __init__(self,limit):
        if limit<0:raise ValueError('limite')
        self.limit=limit;self.spent=0;self.holds={};self.done=set();self.lock=threading.Lock()
    def reserve(self,key,amount):
        if amount<0:raise ValueError('reserva')
        with self.lock:
            if key in self.holds or key in self.done:raise ValueError('identidade reutilizada')
            if self.spent+sum(self.holds.values())+amount>self.limit:return False
            self.holds[key]=amount;return True
    def settle(self,key,actual):
        with self.lock:
            if key not in self.holds:raise ValueError('reserva ausente')
            if actual is None:return
            if actual<0 or actual>self.holds[key]:raise ValueError('custo fora da reserva')
            self.holds.pop(key);self.spent+=actual;self.done.add(key)


def route(complexity, threshold):
    return 'smol' if complexity<=threshold else 'qwen'


def expected(task):
    # Oráculo sintético autoral; nunca fornece a resposta ao modelo.
    return 'aprovar' if task['active'] and task['value']<=task['limit'] and not task['blocked'] else 'revisar'


def reconcile(ledger, spans, attempts):
    def key(row):return (row['trace_id'],row['span_id'])
    offered={key(x):x for x in ledger if x['sampled']}
    received={key(x):x for x in spans}
    sent={tuple(k) for batch in attempts for k in batch['ids']}
    if len(received)!=len(spans):raise ValueError('span duplicado no coletor')
    if set(received)-set(offered):raise ValueError('span sem origem no ledger')
    wrong=[]
    for k,s in received.items():
        e=offered[k]
        if any(s.get(n)!=e.get(n) for n in ['task','role','parent_id']):wrong.append(k)
    return dict(offered=len(ledger),sampled=len(offered),planned_exclusions=len(ledger)-len(offered),
        received=len(received),lost=len(set(offered)-set(received)),
        never_exported=len(set(offered)-sent),attempted_not_received=len((set(offered)&sent)-set(received)),
        wrong_bindings=len(wrong),coverage=len(received)/len(offered) if offered else None)
