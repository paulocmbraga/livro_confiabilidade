"""Admissão, geração e reconciliação. Nenhuma repetição silenciosa de falhas."""
from pathlib import Path
from collections import defaultdict
import argparse,json,random,shutil,time
from datetime import datetime,timezone
from .core import SCHEMA,assemble,messages,parse_response,observe,ranking_metrics,mean,clustered_difference,sha,digest
from .models import ROOT,write,http,retrieve,server

def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))

def plan_jobs(queries,plan):
    jobs=[]
    for q in queries:
        for retriever in plan['primary']['retrievers']:
            for policy in plan['primary']['contexts']:
                for rep,seed in enumerate(plan['primary_seeds']):
                    jobs.append({'id':f"{q['id']}_{retriever}_{policy}_{rep}",'query_id':q['id'],'family':q['family'],
                                 'phase':'primary','retriever':retriever,'policy':policy,'repeat':rep,'seed':seed})
        for policy in ['reference','empty']:
            jobs.append({'id':f"{q['id']}_diagnostic_{policy}_0",'query_id':q['id'],'family':q['family'],
                         'phase':'diagnostic','retriever':'diagnostic','policy':policy,'repeat':0,'seed':plan['primary_seeds'][0]})
    random.Random(plan['order_seed']).shuffle(jobs)
    return jobs

def summarize(rows,retrieval,refs,queries):
    grouped=defaultdict(list)
    for row in rows:grouped[row['retriever']+'/'+row['policy']].append(row)
    summary={}
    for variant,items in sorted(grouped.items()):
        lat=sorted(r['seconds'] for r in items)
        summary[variant]={'calls':len(items),'errors':sum(r['error'] is not None for r in items),
            'signals':{k:mean(r['observed'][k] for r in items) for k in items[0]['observed']},
            'tokens_input':sum(r.get('response',{}).get('usage',{}).get('prompt_tokens',0) for r in items),
            'tokens_output':sum(r.get('response',{}).get('usage',{}).get('completion_tokens',0) for r in items),
            'usage_unknown_calls':sum('usage' not in r.get('response',{}) for r in items),
            'latency_seconds':{'median':lat[len(lat)//2],'p95_nearest_rank':lat[max(0,__import__('math').ceil(.95*len(lat))-1)]}}
    ranks={}
    for variant in ['bm25','dense','hybrid_rerank']:
        ms=[ranking_metrics([x['id'] for x in r[variant]],refs[r['query_id']]['required_ids']) for r in retrieval]
        ranks[variant]={'answerable_or_conflicted_queries':sum(m['recall'] is not None for m in ms),
                        'recall_at_3':mean(m['recall'] for m in ms),'ndcg_at_3':mean(m['ndcg'] for m in ms)}
    return {'variants':summary,'retrieval':ranks,'clustered_contrasts':{
        'hybrid_minus_bm25_top3':clustered_difference(rows,'bm25/top3','hybrid_rerank/top3','automatic_contract_signal'),
        'top3_minus_top1_hybrid':clustered_difference(rows,'hybrid_rerank/top1','hybrid_rerank/top3','automatic_contract_signal')},
        'semantic_approval':False,'human_validation':'pending','independent_replication':'pending',
        'interpretation':'automatic_contract_signal é proxy lexical/estrutural; não mede suporte semântico nem qualidade validada.'}

def seal(out):
    write(out/'manifesto.json',{'files':{p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*'))
          if p.is_file() and p.name!='manifesto.json'},'sealed_at':datetime.now(timezone.utc).isoformat()})

def run(out,cache,runtime,smoke=False):
    if out.exists():raise FileExistsError('Captura existente; escolha pasta nova')
    out.mkdir(parents=True);(out/'fontes').mkdir();(out/'raw').mkdir()
    for path in (ROOT/'materiais/l23').glob('*.json'):shutil.copyfile(path,out/'fontes'/path.name)
    shutil.copytree(Path(__file__).parent,out/'codigo',ignore=shutil.ignore_patterns('__pycache__'))
    corpus=load(out/'fontes/corpus.json')['documents'];queries=load(out/'fontes/consultas.json')
    refs=load(out/'fontes/referencias.json');plan=load(out/'fontes/plano.json');lock=load(out/'fontes/modelos.lock.json')
    if smoke:
        # Distinct engineering fixture; never call this a reserved assessment.
        corpus=[dict(id='DEV',family='dev',title='DEV',tenant='alpha',version='dev',valid_from='2026-01-01',valid_until=None,
                     text='A sala Aurora comporta 8 pessoas.',source_text='A sala Aurora comporta 8 pessoas.')]
        queries=[dict(id='DEVQ',family='dev',question='Quantas pessoas cabem na sala Aurora?',tenant='alpha',as_of='2026-10-23')]
        refs={'DEVQ':dict(required_ids=['DEV'],answer_needles=['8'],expected_abstain=False)}
        write(out/'fontes/corpus.json',{'documents':corpus});write(out/'fontes/consultas.json',queries);write(out/'fontes/referencias.json',refs)
        plan['primary_seeds']=[23];write(out/'fontes/plano.json',plan)
    jobs=plan_jobs(queries,plan);write(out/'admissions.json',jobs)
    write(out/'state.json',{'status':'started','expected_calls':len(jobs),'smoke':smoke,'started_at':datetime.now(timezone.utc).isoformat()})
    docs={d['id']:d for d in corpus};qmap={q['id']:q for q in queries};rows=[];started=time.monotonic()
    try:
        ranking=retrieve(corpus,queries,cache,out,lock);rmap={r['query_id']:r for r in ranking}
        print('Recuperação concluída; iniciando geração',flush=True)
        with server(runtime,out,lock) as url:
            token_cache={}
            def count_tokens(text):
                if text not in token_cache:token_cache[text]=len(http(url+'/tokenize',{'content':text,'add_special':False})['tokens'])
                return token_cache[text]
            for job in jobs:
                if time.monotonic()-started>plan['max_campaign_seconds']:raise TimeoutError('Orçamento global de novas admissões esgotado')
                q=qmap[job['query_id']];policy=job['policy'];reference=refs[q['id']]
                if policy=='reference':ids=reference['required_ids'];limit=len(ids)
                elif policy=='empty':ids=[];limit=0
                else:ids=[r['id'] for r in rmap[q['id']][job['retriever']]];limit=1 if policy=='top1' else 3
                context=assemble(ids,docs,limit,plan['context_token_budget'],count_tokens,source=policy=='reference')
                request={'model':'l23-qwen-q4','messages':messages(q['question'],context['text']),
                    'temperature':plan['temperature'],'top_p':plan['top_p'],'seed':job['seed'],'max_tokens':plan['max_output_tokens'],
                    'stream':False,'cache_prompt':False,'response_format':{'type':'json_schema','json_schema':{'name':'answer','strict':True,'schema':SCHEMA}}}
                row={**job,'context':context,'request':request,'prompt_sha256':digest(request),'real_inference':True,
                     'parsed':None,'error':None,'admitted_at':datetime.now(timezone.utc).isoformat()}
                # Write admission before the call: crash leaves an explicit unresolved request.
                write(out/'raw'/f"{job['id']}.pending.json",row)
                tick=time.monotonic()
                transport=False
                try:
                    row['response']=http(url+'/v1/chat/completions',request,timeout=plan['timeout_seconds'])
                    row['parsed']=parse_response(row['response'])
                except (ValueError,KeyError,IndexError,TypeError) as e:row['error']=type(e).__name__+': '+str(e)
                except OSError as e:row['error']=type(e).__name__+': '+str(e);transport=True
                row['seconds']=round(time.monotonic()-tick,5)
                row['observed']=observe(row,reference,docs);rows.append(row)
                write(out/'raw'/f"{job['id']}.json",row)
                (out/'raw'/f"{job['id']}.pending.json").unlink()
                if len(rows)%24==0:print(f'{len(rows)}/{len(jobs)} gerações; {time.monotonic()-started:.1f}s',flush=True)
                if transport:raise RuntimeError('Transporte incerto; campanha interrompida sem repetir a chamada')
            write(out/'token_counts.json',token_cache)
        report=summarize(rows,ranking,refs,queries)
        write(out/'results.json',report)
        write(out/'state.json',{'status':'complete','expected_calls':len(jobs),'observed_calls':len(rows),'smoke':smoke,
                              'elapsed_seconds':round(time.monotonic()-started,3),'semantic_approval':False})
    except BaseException as e:
        write(out/'state.json',{'status':'incomplete','expected_calls':len(jobs),'observed_calls':len(rows),
                              'error':type(e).__name__+': '+str(e),'elapsed_seconds':round(time.monotonic()-started,3)})
        raise
    finally:seal(out)
    print(json.dumps({'capture':str(out),'calls':len(rows),'semantic_approval':False}),flush=True)

def verify(out):
    import math
    def same_rank(a,b,tolerance=1e-12):
        # Somar termos em ordens distintas muda os últimos bits entre processos.
        # Identidades e ordem continuam exatas; tolerância não reordena candidatos.
        return len(a)==len(b) and all(x['id']==y['id'] and math.isfinite(x['score']) and
            math.isclose(x['score'],y['score'],rel_tol=tolerance,abs_tol=tolerance) for x,y in zip(a,b))
    manifest=load(out/'manifesto.json')
    for rel,expected in manifest['files'].items():
        if sha(out/rel)!=expected:raise ValueError('Hash divergente: '+rel)
    actual={p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file() and p.name!='manifesto.json'}
    if actual!=set(manifest['files']):raise ValueError('Arquivo extra ou ausente')
    state=load(out/'state.json')
    if state['status']!='complete':raise ValueError('Campanha incompleta')
    queries=load(out/'fontes/consultas.json');plan=load(out/'fontes/plano.json');jobs=plan_jobs(queries,plan)
    if load(out/'admissions.json')!=jobs:raise ValueError('Admissões não correspondem ao plano')
    rows=[load(out/'raw'/f"{j['id']}.json") for j in jobs]
    rawpaths=list((out/'raw').glob('*.json'))
    if len(rawpaths)!=len(jobs) or len(rows)!=state['observed_calls']:raise ValueError('Denominador divergente')
    refs=load(out/'fontes/referencias.json');docs={d['id']:d for d in load(out/'fontes/corpus.json')['documents']}
    qmap={q['id']:q for q in queries}
    from .core import bm25,rrf,eligible
    import numpy as np
    retrieval=load(out/'retrieval.json');rmap={r['query_id']:r for r in retrieval}
    if set(rmap)!=set(qmap) or len(retrieval)!=len(queries):raise ValueError('Consulta ausente ou duplicada no ranking')
    vectors=np.load(out/'document_vectors.npy',allow_pickle=False)
    qvectors=np.load(out/'query_vectors.npy',allow_pickle=False)
    if vectors.shape!=(len(docs),384) or qvectors.shape!=(len(queries),384):raise ValueError('Dimensão dos embeddings inválida')
    if not np.isfinite(vectors).all() or not np.isfinite(qvectors).all():raise ValueError('Embedding não finito')
    if not np.allclose(np.linalg.norm(vectors,axis=1),1,atol=1e-5):raise ValueError('Vetor não normalizado')
    dindex={id:i for i,id in enumerate(docs)}
    for qi,q in enumerate(queries):
        r=rmap[q['id']];allowed=[d for d in docs.values() if eligible(d,q)]
        if r['eligible_ids']!=[d['id'] for d in allowed] or not same_rank(r['bm25'],bm25(q['question'],allowed)):raise ValueError('BM25 ou filtro divergente')
        expected=sorted([{'id':d['id'],'score':float(vectors[dindex[d['id']]]@qvectors[qi])} for d in allowed],key=lambda x:(-x['score'],x['id']))
        if not same_rank(r['dense'],expected,1e-6) or not same_rank(r['rrf_candidates'],rrf([r['bm25'][:8],expected[:8]])[:8]):raise ValueError('Ranking vetorial ou fusão divergente')
        if {x['id'] for x in r['hybrid_rerank']}!={x['id'] for x in r['rrf_candidates']}:raise ValueError('Reranker inventou/perdeu candidato')
        if r['hybrid_rerank']!=sorted(r['hybrid_rerank'],key=lambda x:(-x['score'],x['id'])):raise ValueError('Reranking fora de ordem')
    token_counts=load(out/'token_counts.json')
    for job,row in zip(jobs,rows):
        if any(row[k]!=v for k,v in job.items()):raise ValueError('Identidade de tentativa divergente')
        if digest(row['request'])!=row['prompt_sha256']:raise ValueError('Prompt divergente')
        if row['request']['messages']!=messages(qmap[row['query_id']]['question'],row['context']['text']):raise ValueError('Prompt injeta informação não declarada')
        if row['context']['tokens']>plan['context_token_budget']:raise ValueError('Orçamento de contexto violado')
        if not all(eligible(docs[id],qmap[row['query_id']]) for id in row['context']['ids']):raise ValueError('Contexto inelegível')
        policy=row['policy']
        if policy=='reference':ids=refs[row['query_id']]['required_ids'];limit=len(ids)
        elif policy=='empty':ids=[];limit=0
        else:ids=[r['id'] for r in rmap[row['query_id']][row['retriever']]];limit=1 if policy=='top1' else 3
        expected_context=assemble(ids,docs,limit,plan['context_token_budget'],token_counts.__getitem__,source=policy=='reference')
        if expected_context!=row['context']:raise ValueError('Montagem de contexto divergente')
        parsed=None
        try:parsed=parse_response(row['response'])
        except (ValueError,KeyError,IndexError,TypeError):pass
        if parsed!=row['parsed'] or observe(row,refs[row['query_id']],docs)!=row['observed']:raise ValueError('Observação divergente')
    report=summarize(rows,retrieval,refs,queries)
    if report!=load(out/'results.json'):raise ValueError('Resumo não reconcilia')
    if not load(out/'generation_resources.json')['process_ended']:raise ValueError('Servidor sem encerramento registrado')
    return {'complete':True,'calls':len(rows),'files':len(manifest['files']),'semantic_approval':False}

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['run','verify']);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--models',type=Path,default=ROOT/'.modelos');p.add_argument('--runtime',type=Path,default=ROOT.parent/'tmp/seguranca_m1')
    p.add_argument('--smoke',action='store_true');args=p.parse_args()
    if args.action=='run':run(args.out.resolve(),args.models.resolve(),args.runtime.resolve(),args.smoke)
    else:print(json.dumps(verify(args.out.resolve()),ensure_ascii=False))

if __name__=='__main__':main()
