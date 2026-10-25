"""Contratos de composição, recuperação lexical e métricas independentes."""
import math,re,json,unicodedata
from collections import Counter
from laboratorios.parte_i.common import save,load,sha,digest,seal,check_manifest

def tokens(text):
    return re.findall(r'\w+',unicodedata.normalize('NFKD',text.lower()).encode('ascii','ignore').decode())

def corpus(version):
    if version not in ('v1','v2'):raise ValueError('corpus version')
    docs=[]
    for i,name in enumerate(['viagem','hospedagem','alimentacao','taxi','material','internet']):
        amount=250+10*i if version=='v1' else 120+10*i
        docs.append(dict(id=f'{name}-{version}',family=name,version=version,limit=amount,
            text=f'Politica {name} da Horizonte. Limite autorizado: {amount} reais. A excecao anterior esta '+('vigente.' if version=='v1' else 'revogada.')))
    return docs

def retrieve(docs,query):
    bags=[Counter(tokens(d['text'])) for d in docs];avg=sum(map(lambda b:sum(b.values()),bags))/len(bags)
    scores=[]
    for d,b in zip(docs,bags):
        score=0.
        for t in set(tokens(query)):
            df=sum(t in x for x in bags);idf=math.log(1+(len(bags)-df+.5)/(df+.5))
            f=b[t];score+=idf*f*2.2/(f+1.2*(.25+.75*sum(b.values())/avg)) if f else 0.
        scores.append(dict(document=d,score=score))
    return sorted(scores,key=lambda r:(-r['score'],r['document']['id']))

def bound(bundle,current):
    return len({bundle[k] for k in ('corpus','index','cache','prompt')})==1 and bundle['corpus']==current

def parse(text):
    try:return json.loads(text)
    except (json.JSONDecodeError,TypeError):return None

def answer_signal(text,doc):
    data=parse(text)
    return isinstance(data,dict) and type(data.get('limite')) is int and data['limite']==doc['limit'] and data.get('fonte')==doc['id']

def proposal(text,request):
    data=parse(text)
    ok=isinstance(data,dict) and data.get('action')=='reserve' and type(data.get('quantity')) is int and data['quantity']==request['quantity']==1 and request['authorized']
    return dict(accepted=bool(ok),data=data,reason='bounded_proposal' if ok else 'review_required')

def cost(rows,outputs,threshold=1/9):
    if [r['id'] for r in rows]!=[r['id'] for r in outputs]:raise ValueError('identity')
    fp=sum(r['y']==0 and o['p']>=threshold for r,o in zip(rows,outputs))
    fn=sum(r['y']==1 and o['p']<threshold for r,o in zip(rows,outputs))
    return dict(n=len(rows),fp=fp,fn=fn,cost=fp+8*fn,threshold=threshold)

def release_gate(metric,unit_ok,temporal_ok):
    return dict(allowed=unit_ok and temporal_ok and metric['brier']<=.23,
        quality=metric['brier']<=.23,unit_ok=unit_ok,temporal_ok=temporal_ok)

def evidence_reuse(old,new):
    keys=('data','model','judge','dependency','contract')
    return dict(reusable=all(old[k]==new[k] for k in keys),changed=[k for k in keys if old[k]!=new[k]])
