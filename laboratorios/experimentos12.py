"""L12: fatorial local de contexto/gerador/cache e simulações identificadas."""
from copy import deepcopy
from collections import Counter
import math
import random
import time
from .dados_ii import corpus, write, lines, table
from .recuperacao06 import queries, public_query, rank, generate

VARIANTS=((1,'primeiro'),(1,'compor'),(2,'primeiro'),(2,'compor'))


def cache_key(query):
    return (query['question'],query['topic'],query['custom'],query['identity'],query['day'],'corpus-II-1.0','hibrida')


def retrieve(query, cache):
    key=cache_key(query)
    if key in cache:return deepcopy(cache[key]),0
    ranking=rank(query,'hibrida');cache[key]=ranking
    return deepcopy(ranking),1


def run_once(query, k, generator, condition):
    if k not in (1,2) or generator not in ('primeiro','compor') or condition not in ('frio','quente'):
        raise ValueError('Fator inválido')
    cache={};public=public_query(query);warm_calls=0
    if condition=='quente':_,warm_calls=retrieve(public,cache)
    start=time.perf_counter_ns();ranking,calls=retrieve(public,cache)
    index={d['doc_id']:d for d in corpus()};docs=[index[i] for i in ranking[:k]]
    response=generate(public,docs,generator);elapsed=(time.perf_counter_ns()-start)/1000
    return dict(query_id=query['query_id'],k=k,generator=generator,cache=condition,
        selected=[d['doc_id'] for d in docs],response=response,correct=response==query['expected'],
        retrieval_calls=calls,warmup_calls=warm_calls,generation_calls=1,
        context_chars=sum(len(d['text']) for d in docs),elapsed_us=elapsed)


def plan():
    order=queries();random.Random(1201).shuffle(order);rows=[]
    for task_index,query in enumerate(order):
        for repeat in range(4):
            rotated=list(VARIANTS[repeat:]+VARIANTS[:repeat])
            conditions=('frio','quente') if (task_index+repeat)%2==0 else ('quente','frio')
            for condition in conditions:
                for position,(k,generator) in enumerate(rotated,1):
                    rows.append(dict(run_id=f'{query["query_id"]}:{repeat}:{condition}:{k}:{generator}',
                        query_id=query['query_id'],repeat=repeat,cache=condition,position=position,k=k,generator=generator))
    return rows


def factorial():
    index={q['query_id']:q for q in queries()}
    return [dict(**p,**{k:v for k,v in run_once(index[p['query_id']],p['k'],p['generator'],p['cache']).items()
                      if k not in p}) for p in plan()]


def effects(rows):
    means={}
    for k,g in VARIANTS:
        group=[r for r in rows if r['k']==k and r['generator']==g]
        if not group:raise ValueError('Célula ausente')
        means[(k,g)]=sum(r['correct'] for r in group)/len(group)
    a0,b0=means[(1,'primeiro')],means[(1,'compor')]
    a1,b1=means[(2,'primeiro')],means[(2,'compor')]
    return dict(cell_means=[dict(k=k,generator=g,quality=means[(k,g)]) for k,g in VARIANTS],
        context_given_first=a1-a0,context_given_compose=b1-b0,
        generator_given_one=b0-a0,generator_given_two=b1-a1,
        interaction=(b1-b0)-(a1-a0),context_main=((a1-a0)+(b1-b0))/2,
        generator_main=((b0-a0)+(b1-a1))/2,combined=b1-a0)


def naive():
    index={q['query_id']:q for q in queries()}
    rows=[]
    for name,ids,k,g,c in (
        ('anterior',['R01','R02','R08','R03'],1,'primeiro','frio'),
        ('nova',['R03','R04','R05','R06'],2,'compor','quente')):
        rows.extend(dict(variant=name,**run_once(index[i],k,g,c)) for i in ids)
    return rows


def online_simulation():
    teams=list(range(12));random.Random(1202).shuffle(teams)
    treatment=set(teams[:6]);rows=[]
    for team in range(12):
        for user in range(4):
            variant='B' if team in treatment else 'A'
            status='abandono' if user==0 else 'falha' if variant=='A' and user==1 else 'concluido'
            rows.append(dict(team=team,user=f'{team}:{user}',assigned=variant,
                alternating_assignment='A' if user%2==0 else 'B',exposed=user!=0,status=status,
                source_kind='simulacao_autoral'))
    return rows


def binomial_p(successes,n):
    """Teste bilateral exato de moeda justa, para o exemplo sequencial simulado."""
    if type(n) is not int or type(successes) is not int or not 0<=successes<=n or n<1:
        raise ValueError('Contagens inválidas')
    tail=sum(math.comb(n,i) for i in range(min(successes,n-successes)+1))/2**n
    return min(1.0,2*tail)


def sequential_simulation(runs=1000,seed=1203):
    rng=random.Random(seed);rows=[];looks=(20,40,60,80,100)
    for trial in range(runs):
        wins=0;ps=[]
        for n in range(1,101):
            wins+=rng.randrange(2)
            if n in looks:ps.append(binomial_p(wins,n))
        rows.append(dict(trial=trial,p_values=ps,fixed=ps[-1]<=.05,
                         peek=any(p<=.05 for p in ps),bonferroni=any(p<=.01 for p in ps)))
    return rows


def summarize(rows,naive_rows,online,sequential):
    naive_result=[]
    for variant in ('anterior','nova'):
        group=[r for r in naive_rows if r['variant']==variant]
        naive_result.append(dict(variant=variant,admitted=len(group),correct=sum(r['correct'] for r in group),
            measured_calls=sum(r['retrieval_calls']+r['generation_calls'] for r in group),
            including_warmup=sum(r['retrieval_calls']+r['generation_calls']+r['warmup_calls'] for r in group)))
    online_result=[]
    for variant in ('A','B'):
        group=[r for r in online if r['assigned']==variant]
        completed=sum(r['status']=='concluido' for r in group);observed=sum(r['exposed'] for r in group)
        online_result.append(dict(variant=variant,assigned=len(group),exposed=observed,completed=completed,
            task_completion=completed/len(group),selected_completion=completed/observed))
    return dict(observations=len(rows),tasks=len({r['query_id'] for r in rows}),effects=effects(rows),naive=naive_result,
        retrieval_calls=sum(r['retrieval_calls'] for r in rows),warmup_calls=sum(r['warmup_calls'] for r in rows),
        generation_calls=sum(r['generation_calls'] for r in rows),online_simulation=online_result,
        mixed_teams_alternating=sum(len({r['alternating_assignment'] for r in online if r['team']==t})>1 for t in range(12)),
        mixed_teams_cluster=sum(len({r['assigned'] for r in online if r['team']==t})>1 for t in range(12)),
        sequential=dict(runs=len(sequential),fixed=sum(r['fixed'] for r in sequential),
            peek=sum(r['peek'] for r in sequential),bonferroni=sum(r['bonferroni'] for r in sequential)))


def capture(folder):
    folder.mkdir();rows=factorial();nr=naive();online=online_simulation();seq=sequential_simulation()
    write(folder/'randomization.json',dict(seed_tasks=1201,allocation=plan(),scheme='quatro rotações cíclicas por tarefa e cache'))
    lines(folder/'factorial_runs.jsonl',rows);lines(folder/'naive_runs.jsonl',nr)
    lines(folder/'online_simulation.jsonl',online);lines(folder/'sequential_simulation.jsonl',seq)
    summary=summarize(rows,nr,online,seq);write(folder/'summary.json',summary)
    table(folder/'effects.csv',summary['effects']['cell_means'])
    (folder/'experiment_plan.md').write_text(
        '# L12-1.0\n\nOito tarefas públicas, contexto k=1/2, geradores primeiro/compor, '
        'cache frio/quente e quatro rotações. Cache novo em cada observação; aquecimento contabilizado. '
        '256 observações; quatro repetições de execução não criam novas tarefas. '
        'Qualidade é calculada contra os átomos do corpus; tempo local observado não é benchmark remoto. '
        'As simulações online e sequencial são dados distintos, sem pessoas ou exposição real. '
        'A simulação de moeda usa 1.000 sequências nulas, cinco análises fixadas e semente 1203. '
        'Bonferroni divide 0,05 por cinco; o exemplo não implementa inferência sequencial arbitrária.\n',encoding='utf8')
    return summary
