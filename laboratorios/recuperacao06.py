"""L06: busca real sobre corpus pequeno; vetores de conceitos manuais, sem embeddings."""
import math
import time
from .dados_ii import corpus, allowed, tokens, write, lines, table

CONCEPTS = [
    {'troca','trocar','substituir','substituicao'},
    {'personalizado','personalizados','customizado','sobmedida'},
    {'reembolso','reembolsar','ressarcimento','dinheiro'},
    {'frete','entrega','chegar','encomenda'},
    {'chat','atendimento','conversar'},
    {'rastreio','rastreamento','rastrear','codigo'},
    {'desconto','ouro','abatimento'},
    {'credito','cortesia'},
]
STOP = {'a','o','de','da','do','em','e','que','qual','por','para','no','na','os','as','um','uma'}


def queries():
    specs = [
        ('R01','Troca de produto intacto personalizado por preferência','troca',True,
         {'troca_personalizado':'não admitida por preferência'}, {'D01':1,'D02':3}),
        ('R02','Prazo e meio do reembolso aprovado','reembolso',False,
         {'reembolso_prazo':'5 dias úteis','reembolso_meio':'pagamento original'}, {'D03':3,'D11':3}),
        ('R03','Quantos dias demora o frete padrão?','frete',False,
         {'frete_prazo':'7 dias úteis'}, {'D04':3}),
        ('R04','Quando posso conversar com alguém?','chat',False,
         {'chat_horario':'9 às 18 horas em dias úteis'}, {'D08':3}),
        ('R05','Como faço para rastrear minha encomenda?','rastreio',False,
         {'rastreio_requisito':'código de envio'}, {'D09':3}),
        ('R06','Prazo de troca de produto comum intacto','troca',False,
         {'troca_comum':'30 dias'}, {'D01':3}),
        ('R07','Desconto ouro interno','desconto',False, {}, {}),
        ('R08','Quanto vale o crédito de cortesia?','credito',False, {}, {'D10':2,'D12':2}),
    ]
    eligible=[d['doc_id'] for d in corpus() if allowed(d)]
    return [dict(query_id=i, question=q, topic=t, custom=c, expected=e,
                 qrels={doc_id:qr.get(doc_id,0) for doc_id in eligible},
                 identity='suporte', day='2026-09-30', answerable=bool(e),
                 reason='conflito' if i=='R08' else 'acesso' if i=='R07' else 'respondível')
            for i,q,t,c,e,qr in specs]


def vector(text):
    words=set(tokens(text)); return [float(len(words & concept)) for concept in CONCEPTS]


def cosine(a,b):
    denominator=math.sqrt(sum(x*x for x in a)*sum(y*y for y in b))
    return sum(x*y for x,y in zip(a,b))/denominator if denominator else 0.0


def rank(query, method='lexical', documents=None):
    docs=[d for d in (corpus() if documents is None else documents)
          if allowed(d,query['identity'],query['day'])]
    words=set(tokens(query['question']))-STOP
    lexical={d['doc_id']:len(words & (set(tokens(d['text']))-STOP)) for d in docs}
    vectors={d['doc_id']:cosine(vector(query['question']),vector(d['text'])) for d in docs}
    order=lambda scores: sorted((i for i,v in scores.items() if v>0),key=lambda i:(-scores[i],i))
    lr,vr=order(lexical),order(vectors)
    if method=='lexical': scores=lexical
    elif method=='vetor_manual': scores=vectors
    elif method in ('hibrida','rerank'):
        scores={i:sum(1/(60+ranking.index(i)+1) for ranking in (lr,vr) if i in ranking)
                for i in set(lr+vr)}
        if method=='rerank' and query['custom']:
            for d in docs:
                if 'troca_personalizado' in d['facts'] and d['doc_id'] in scores:
                    scores[d['doc_id']]+=1.0
    else: raise ValueError('Método desconhecido')
    return order(scores)


def retrieval_metrics(ranking,qrels,k=2):
    if len(ranking)!=len(set(ranking)):raise ValueError('Ranking contém duplicatas')
    if k<1:raise ValueError('k deve ser positivo')
    relevant={d for d,g in qrels.items() if g>0}
    gain=lambda grade:2**grade-1
    dcg=sum(gain(qrels.get(d,0))/math.log2(i+2) for i,d in enumerate(ranking[:k]))
    ideal=sum(gain(g)/math.log2(i+2) for i,g in enumerate(sorted(qrels.values(),reverse=True)[:k]))
    return dict(recall=len(set(ranking[:k])&relevant)/len(relevant) if relevant else None,
                ndcg=dcg/ideal if ideal else None,
                judged=sum(d in qrels for d in ranking[:k]),returned=len(ranking[:k]))


def generate(query, docs, mode='compor'):
    """Gerador por regras: recebe pergunta e documentos, nunca expected/qrels."""
    if mode not in ('primeiro','compor'):raise ValueError('Gerador desconhecido')
    selected=docs[:1] if mode=='primeiro' else docs
    facts={}
    for d in selected:
        for key,value in d['facts'].items():facts.setdefault(key,set()).add(value)
    if any(len(v)>1 for v in facts.values()):return {}
    if query['topic']=='troca':
        # Baseline ignora o campo custom; a compositora preserva a exceção.
        key='troca_personalizado' if query['custom'] and mode=='compor' else 'troca_comum'
        keys=[key]
    else:keys=[k for k in facts if k.startswith(query['topic']+'_') or k==query['topic']]
    return {k:next(iter(facts[k])) for k in keys if k in facts}


def public_query(q):
    return {k:q[k] for k in ('query_id','question','topic','custom','identity','day')}


def compare(query, method, mode, documents=None):
    docs=corpus() if documents is None else documents; index={d['doc_id']:d for d in docs}
    public=public_query(query); start=time.perf_counter_ns(); ranking=rank(public,method,docs)
    retrieval_us=(time.perf_counter_ns()-start)/1000
    selected=[index[i] for i in ranking[:2]]
    reference=[index[i] for i,g in query['qrels'].items() if g>0 and allowed(index[i],query['identity'],query['day'])]
    actual=generate(public,selected,mode); ideal=generate(public,reference,mode)
    good=actual==query['expected']; ideal_good=ideal==query['expected']
    # Desfecho da resposta condicionado aos controles; não prova causalidade única.
    origin=('sem_falha' if good else 'geracao_ou_contrato' if not ideal_good else 'recuperacao_contexto')
    if not query['answerable'] and good:origin='abstencao_adequada'
    return dict(query_id=query['query_id'],method=method,generator=mode,ranking=ranking,
        selected=[d['doc_id'] for d in selected],reference=[d['doc_id'] for d in reference],
        response=actual,reference_response=ideal,correct=good,reference_correct=ideal_good,
        answerable=query['answerable'],origin=origin,leaks=sum(not allowed(d,query['identity'],query['day']) for d in selected),
        retrieval_us=retrieval_us,**retrieval_metrics(ranking,query['qrels']))


def summarize(rows):
    result=[]
    for method in ('lexical','vetor_manual','hibrida','rerank'):
        for generator in ('primeiro','compor'):
            group=[r for r in rows if r['method']==method and r['generator']==generator]
            rec=[r['recall'] for r in group if r['recall'] is not None]
            nd=[r['ndcg'] for r in group if r['ndcg'] is not None]
            result.append(dict(method=method,generator=generator,tasks=len(group),
                correct=sum(r['correct'] for r in group),reference_correct=sum(r['reference_correct'] for r in group),
                recall_mean=sum(rec)/len(rec),ndcg_mean=sum(nd)/len(nd),ranking_denominator=len(rec),
                leaks=sum(r['leaks'] for r in group)))
    return result


def capture(folder):
    folder.mkdir(); rows=[compare(q,m,g) for q in queries()
        for m in ('lexical','vetor_manual','hibrida','rerank') for g in ('primeiro','compor')]
    write(folder/'corpus.json',corpus()); lines(folder/'queries.jsonl',queries())
    lines(folder/'qrels.jsonl',[dict(query_id=q['query_id'],grades=q['qrels'],
        annotation='Juízos autorais completos no universo elegível; ausência significa grau zero.') for q in queries()])
    lines(folder/'retrieval_runs.jsonl',rows)
    table(folder/'matriz_origem_erro.csv',[{k:r[k] for k in
        ('query_id','method','generator','correct','reference_correct','origin','recall','ndcg','leaks','retrieval_us')} for r in rows])
    summary=summarize(rows); write(folder/'summary.json',summary)
    return summary
