"""L23: caso integrado de conhecimento; busca real e gerador por regras de L06."""
from copy import deepcopy
from pathlib import Path
import time
from .dados_ii import corpus,document,allowed,write,lines,table,sha
from . import recuperacao06 as rag
from .evidencia_vi import digest,index,verify_index

VARIANTS={'baseline':('lexical','primeiro'),'compositor':('rerank','compor')}
CLAIMS=('selecao','avaliacao_reservada','atualizacao','incidente','decisao')


def documents():
    return corpus()+[
        document('H01','Garantia de equipamento: prazo de 12 meses.',{'garantia_prazo':'12 meses'}),
        document('H02','Garantia de equipamento antiga: prazo de 6 meses.',{'garantia_prazo':'6 meses'},start='2025-01-01',end='2025-12-31'),
        document('H03','Retirada de mercadoria: prazo de 2 dias úteis.',{'retirada_prazo':'2 dias úteis'}),
        document('H04','Fatura interna: conta restrita 0042.',{'fatura_conta':'0042'},group='financeiro'),
        document('H05','Cancelamento comunicado A: prazo de 24 horas.',{'cancelamento_prazo':'24 horas'}),
        document('H06','Cancelamento comunicado B: prazo de 72 horas.',{'cancelamento_prazo':'72 horas'}),
        document('H07','Instalação de equipamento: agendamento obrigatório.',{'instalacao_regra':'agendamento obrigatório'}),
        document('H08','Senha do portal: redefinição por link.',{'senha_regra':'redefinição por link'}),
        document('H09','Manutenção: atendimento nas segundas-feiras.',{'manutencao_dia':'segunda-feira'}),
    ]


def reserved():
    specs=[('A01','garantia','Prazo da garantia do equipamento',{'garantia_prazo':'12 meses'}),
           ('A02','retirada','Prazo para retirada de mercadoria',{'retirada_prazo':'2 dias úteis'}),
           ('A03','fatura','Qual a conta da fatura interna',{}),
           ('A04','cancelamento','Prazo para cancelamento',{}),
           ('A05','instalacao','Como solicitar instalação de equipamento',{'instalacao_regra':'agendamento obrigatório'}),
           ('A06','senha','Como redefinir senha do portal',{'senha_regra':'redefinição por link'}),
           ('A07','boleto','Qual a multa de boleto atrasado',{}),
           ('A08','manutencao','Dia de atendimento da manutenção',{'manutencao_dia':'segunda-feira'})]
    return [dict(query_id=i,topic=t,question=q,expected=e,identity='suporte',day='2026-09-30',
                 custom=False,family=t,answerable=bool(e)) for i,t,q,e in specs]


def public(q):
    return {k:q[k] for k in ('query_id','topic','question','identity','day','custom')}


def answer(q,variant,docs,quarantine=()):
    method,mode=VARIANTS[variant]
    start=time.perf_counter_ns()
    candidates=[d for d in docs if d['doc_id'] not in quarantine]
    ranking=rag.rank(public(q),method,candidates)
    lookup={d['doc_id']:d for d in candidates};selected=[lookup[i] for i in ranking[:2]]
    result=rag.generate(public(q),selected,mode)
    # Citam-se apenas documentos que sustentam os fatos efetivamente emitidos.
    cites=sorted({d['doc_id'] for d in selected for k,v in result.items() if d['facts'].get(k)==v})
    return dict(query_id=q['query_id'],variant=variant,response=result,citations=cites,
        context=[d['doc_id'] for d in selected],corpus_id=digest(docs),
        elapsed_us=(time.perf_counter_ns()-start)/1000,
        work_units=len(candidates)+len(selected)+len(result))


def judge(q,row,docs):
    lookup={d['doc_id']:d for d in docs}
    leaks=sum(i not in lookup or not allowed(lookup[i],q['identity'],q['day']) for i in row['context'])
    supported=all(any(i in lookup and lookup[i]['facts'].get(k)==v
        and allowed(lookup[i],q['identity'],q['day']) for i in row['citations']) for k,v in row['response'].items())
    return dict(**row,correct=row['response']==q['expected'] and supported and leaks==0,
                supported=supported,access_violations=leaks,answerable=q['answerable'],
                answered=bool(row['response']),family=q.get('family',q['topic']),
                snapshot_current=row['corpus_id']==digest(docs))


def aggregate(rows,expected_ids):
    ids=[r['query_id'] for r in rows]
    if len(ids)!=len(set(ids)) or set(ids)!=set(expected_ids):raise ValueError('População incompleta')
    n=len(rows);answerable=[r for r in rows if r['answerable']]
    return dict(tasks=n,correct=sum(r['correct'] for r in rows),
        served=sum(r['answered'] for r in rows),answerable=len(answerable),
        answerable_correct=sum(r['correct'] for r in answerable),
        access_violations=sum(r['access_violations'] for r in rows),
        stale_snapshots=sum(not r['snapshot_current'] for r in rows),
        work_units=sum(r['work_units'] for r in rows),
        mean_local_us=sum(r['elapsed_us'] for r in rows)/n)


def select(dev):
    # A seleção não recebe a população reservada nem suas referências.
    scores={v:(sum(r['correct'] for r in dev if r['variant']==v),
               -sum(r['work_units'] for r in dev if r['variant']==v)) for v in VARIANTS}
    return max(VARIANTS,key=lambda v:(scores[v],v=='baseline'))


def updated(docs):
    out=deepcopy(docs)
    for d in out:
        if d['doc_id']=='H01':
            d.update(revision=2,text='Garantia de equipamento: prazo de 24 meses.',facts={'garantia_prazo':'24 meses'})
        if d['doc_id']=='H03':d.update(revision=2,group='logistica')
    return out


class Cache:
    def __init__(self,safe=True):self.safe=safe;self.values={}
    def get(self,q,variant,docs):
        start=time.perf_counter_ns()
        identity=(q['question'],q['identity'],q['day'],variant,digest(docs)) if self.safe else q['question']
        hit=identity in self.values
        if identity not in self.values:self.values[identity]=answer(q,variant,docs)
        row=deepcopy(self.values[identity]);row['cache_hit']=hit
        row['work_units']=1 if hit else 1+row['work_units']
        row['elapsed_us']=(time.perf_counter_ns()-start)/1000
        return row


def capture(folder):
    folder.mkdir();docs=documents();devq=rag.queries()
    dev=[judge(q,answer(q,v,docs),docs) for v in VARIANTS for q in devq]
    chosen=select(dev)
    components=dict(corpus=digest(docs),variant=chosen,model='gerador_por_regras_sem_LLM',
        policy='allowed-v1',config='top-k-2',sources={n:sha(Path(__file__).parent/n)
        for n in ('assistente23.py','recuperacao06.py','dados_ii.py')})
    freeze=dict(variant=chosen,components=components,release_id=digest(components),
        dev_ids=[q['query_id'] for q in devq],reserved_ids=[q['query_id'] for q in reserved()],
        reservation='Partição lógica publicada; não é teste secreto após a distribuição.')
    write(folder/'candidate_frozen.json',freeze)
    held=reserved();rows=[judge(q,answer(q,chosen,docs),docs) for q in held]
    newdocs=updated(docs);newq=deepcopy(held)
    newq[0].update(expected={'garantia_prazo':'24 meses'})
    newq[1].update(expected={},answerable=False)
    changes=[]
    for safe in (False,True):
        cache=Cache(safe)
        for q in held:cache.get(q,chosen,docs)
        for q in newq:
            row=judge(q,cache.get(q,chosen,newdocs),newdocs)
            changes.append(dict(**row,cache='versionado' if safe else 'ingenuo'))
    broken=[d for d in newdocs if d['doc_id']!='H07']
    incident=[judge(q,answer(q,chosen,broken),newdocs) for q in newq]
    repaired=[judge(q,answer(q,chosen,newdocs),newdocs) for q in newq]
    ids=[q['query_id'] for q in held]
    summary=dict(selected=chosen,development={v:aggregate([r for r in dev if r['variant']==v],[q['query_id'] for q in devq]) for v in VARIANTS},
        reserved=aggregate(rows,ids),updates={c:aggregate([r for r in changes if r['cache']==c],ids) for c in ('ingenuo','versionado')},
        incident=aggregate(incident,ids),repaired=aggregate(repaired,ids))
    write(folder/'corpus_v1.json',docs);write(folder/'corpus_v2.json',newdocs)
    lines(folder/'development_queries.jsonl',devq);lines(folder/'reserved_queries.jsonl',held)
    lines(folder/'updated_queries.jsonl',newq);lines(folder/'development_runs.jsonl',dev)
    lines(folder/'reserved_runs.jsonl',rows);lines(folder/'update_runs.jsonl',changes)
    lines(folder/'incident_runs.jsonl',incident);lines(folder/'repaired_runs.jsonl',repaired)
    write(folder/'summary.json',summary)
    decision=dict(status='liberar_ensaio_local_delimitado',variant=chosen,
        corpus=digest(docs),scope='Oito famílias preparadas; respostas por regras; leitura apenas.',
        operational_conditions=['cache versionado','checagem de acesso antes de servir','teste de reindexação'],
        external_deployment=False,pending=['avaliação de modelo','referência humana','carga sustentada','ameaças da integração real'])
    write(folder/'decision_A.json',decision)
    (folder/'dossie_A.md').write_text('Sistema A: assistente de conhecimento da Horizonte. O candidato é escolhido '
        'somente nos oito casos de desenvolvimento de L06 e congelado antes dos oito casos reservados de novas famílias. '
        'Busca e composição são executadas, mas fatos são anotações autorais e o gerador é uma regra. '
        'O controle de cache por pergunta perde vigência e acesso; o cache versionado conserva as novas condições. '
        'A reindexação incompleta remove H07, e a suíte detecta a omissão. A decisão permite apenas continuar '
        'o ensaio local de leitura. Os números não medem capacidade semântica de LLM nem generalização.',encoding='utf8')
    idx=index(folder,{'selecao':['development_runs.jsonl','candidate_frozen.json'],
        'avaliacao_reservada':['reserved_queries.jsonl','reserved_runs.jsonl'],
        'atualizacao':['corpus_v2.json','updated_queries.jsonl','update_runs.jsonl'],
        'incidente':['incident_runs.jsonl','repaired_runs.jsonl'],
        'decisao':['decision_A.json','summary.json']})
    verify_index(folder,idx,CLAIMS)
    return summary
