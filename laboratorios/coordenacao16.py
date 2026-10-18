"""L16: escalonador determinístico de papéis e tempo lógico, não agentes LLM."""
from copy import deepcopy
from .dados_ii import write, lines, table

VARIANTS=('simples','equipe','sem_revisor','consenso')

class Budget:
    def __init__(self,limit):self.limit=limit;self.events=[]
    def take(self,kind):
        if len(self.events)>=self.limit:raise RuntimeError('orcamento')
        self.events.append(kind)

def accept_artifact(store,artifact,task,terminal=False):
    if terminal:return 'tardio'
    if artifact['task']!=task:return 'tarefa'
    key=(artifact['role'],artifact['id'])
    if key in store:return 'duplicado' if store[key]==artifact else 'conflito'
    if any(a['role']==artifact['role'] for a in store.values()):return 'papel_repetido'
    store[key]=deepcopy(artifact);return 'aceito'

def delegate(target,ancestors):
    if target in ancestors:raise ValueError('ciclo')
    return ancestors+[target]

def cases():
    specs=[('C01','normal'),('C02','estoque_insuficiente'),('C03','fonte_vencida'),
           ('C04','mensagem_repetida'),('C05','atraso'),('C06','ciclo'),
           ('C07','autoridade_trocada'),('C08','retry')]
    return [dict(case_id=i,fault=f,quantity=2,stock=1 if f=='estoque_insuficiente' else 5,
        policy_current=f!='fonte_vencida',expected_allow=f not in ('estoque_insuficiente','fonte_vencida','atraso','ciclo','autoridade_trocada'),
        deadline=6,policy_finish=8 if f=='atraso' else 2) for i,f in specs]

def run(case,variant,limit=8):
    if variant not in VARIANTS:raise ValueError(variant)
    budget=Budget(limit);trace=[];store={};decision=None;reason='';wasted=0;logical_time=0
    def event(kind,**kw):trace.append(dict(event=kind,**kw))
    try:
        team=variant!='simples'
        for role in ('stock','policy'):
            if team:
                budget.take('delegate_'+role)
                ancestors=['coordinator',role]
                if case['fault']=='ciclo' and role=='policy':delegate('coordinator',ancestors)
                event('delegated',role=role,ancestors=ancestors)
            elif case['fault']=='ciclo' and role=='policy':raise ValueError('ciclo')
            budget.take('read_'+role)
            if case['fault']=='retry' and role=='policy':
                event('read_failed',role=role);budget.take('retry_'+role)
            finish=1 if role=='stock' else case['policy_finish']
            if not team:finish+=logical_time
            logical_time=max(logical_time,finish)
            artifact=dict(task=case['case_id'],role=role,id=role+'-1',
                value=case['stock'] if role=='stock' else True,
                version='atual' if role=='stock' or case['policy_current'] else 'vencida',
                principal='bruno' if case['fault']=='autoridade_trocada' and role=='policy' else 'ana')
            if finish>case['deadline']:
                event('cancel_requested',role=role,at=case['deadline']);wasted+=1
                event('artifact',role=role,result=accept_artifact(store,artifact,case['case_id'],terminal=True))
                decision=None;reason='prazo';logical_time=case['deadline'];break
            result=accept_artifact(store,artifact,case['case_id']);event('artifact',role=role,result=result)
            if case['fault']=='mensagem_repetida':
                event('artifact',role=role,result=accept_artifact(store,artifact,case['case_id']))
        if not reason:
            if variant in ('simples','equipe'):
                budget.take('review')
                if any(a['version']!='atual' for a in store.values()):reason='evidencia_vencida'
            if variant=='consenso':
                votes=[]
                for copy in range(2):budget.take('copy_policy');votes.append(True)
                event('votes',values=[True]+votes,source='mesma_politica')
            if any(a['principal']!='ana' for a in store.values()):reason='autoridade'
            if not reason:
                budget.take('join')
                if {a['role'] for a in store.values()}!={'stock','policy'}:raise ValueError('dependencia')
                decision=next(a['value'] for a in store.values() if a['role']=='stock')>=case['quantity']
                reason='decisao'
    except (ValueError,RuntimeError) as exc:
        reason=str(exc);decision=None;event('stopped',reason=reason)
    # Estado final do simulador local, não um destino remoto.
    effects=[dict(intent=case['case_id'],principal='ana',quantity=case['quantity'])] if decision else []
    outcome='aplicado' if decision else 'recusado' if decision is False else 'pendente'
    adequate=(decision==case['expected_allow']) if decision is not None else not case['expected_allow']
    return dict(case_id=case['case_id'],variant=variant,budget=limit,cost=len(budget.events),
        charges=budget.events,logical_time=logical_time,wasted=wasted,decision=decision,
        reason=reason,outcome=outcome,effects=effects,violation=bool(effects) and not case['expected_allow'],
        adequate=adequate,trace=trace)

def summarize(rows):
    return [dict(variant=v,tasks=len(g),adequate=sum(r['adequate'] for r in g),
        applied=sum(r['outcome']=='aplicado' for r in g),pending=sum(r['outcome']=='pendente' for r in g),
        violations=sum(r['violation'] for r in g),cost=sum(r['cost'] for r in g),
        wasted=sum(r['wasted'] for r in g),logical_time=sum(r['logical_time'] for r in g))
        for v in VARIANTS for g in [[r for r in rows if r['variant']==v]]]

def capture(folder):
    folder.mkdir();catalog=cases();rows=[run(c,v) for c in catalog for v in VARIANTS]
    lines(folder/'coordination_cases.jsonl',catalog);lines(folder/'delegation_traces.jsonl',rows)
    table(folder/'ablations.csv',summarize(rows))
    write(folder/'budget_probes.json',[run(cases()[0],'equipe',limit=n) for n in (0,3,5,6,8)])
    (folder/'coordination_decision.md').write_text('O workflow e a equipe completa usam as mesmas leituras e revisão. '
        'O paralelismo é simulado com relógio lógico. Custos incluem delegações, leituras, retries, revisão e junção. '
        'Entregas repetidas do mesmo artefato não executam novamente o papel. '
        'Consenso replica uma fonte e não acrescenta evidência independente. '
        'As pendências seguras são separadas de conclusões; não medimos LLM, comunicação de rede ou latência real.',encoding='utf8')
    return summarize(rows)
