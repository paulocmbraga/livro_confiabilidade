"""Campanha finita com capturas brutas; nunca sobrescreve um diretório."""
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
import argparse, json, os, platform, random, shutil, subprocess, sys, time
import numpy as np
from laboratorios.parte_i.common import load, save, sha, seal, wait_file
from laboratorios.l23.core import bm25, rrf, eligible, ranking_metrics, messages, SCHEMA, parse_response, observe
from laboratorios.l23.models import retrieve
from laboratorios.l11.runtime import server, http
from .ingest import parse, chunks, assess, catalog, eligible as eligible_meta
from .retrieval import approximate, ann_recall, judged_metrics, order
from . import store
ROOT=Path(__file__).resolve().parents[2]
FLAGS=getattr(subprocess,'CREATE_NO_WINDOW',0)


def ingest(out, material):
    docs=[(x['id'],parse((material/x['path']).read_text(encoding='utf-8'))) for x in load(material/'inventario.json')]
    reference=load(material/'referencia_ingestao.json')['documents'];rows=[]
    for name,doc in docs:
        for strategy in ['body_only','independent','linked']:
            parts=chunks(doc,strategy)
            rows.append({'document':name,'strategy':strategy,'parsed':doc,'chunks':parts,'audit':assess(parts,reference[name])})
    result={'rows':rows,'catalog':catalog(docs),
        'alpha_current':[n for n,d in docs if eligible_meta(d['metadata'],'alpha','2026-10-24')],
        'release_after_quarantine':catalog([(n,d) for n,d in docs if n!='jantar_v2_conflito'])}
    save(out/'ingestion.json',result);return result


def retrieval(out, plan):
    from sklearn.cluster import KMeans
    from sentence_transformers import SentenceTransformer
    corpus=load(ROOT/'materiais/l23/corpus.json')['documents'];queries=load(ROOT/'materiais/l23/consultas.json')
    refs=load(ROOT/'materiais/l23/referencias.json');lock=load(ROOT/'materiais/l23/modelos.lock.json')
    rankings=retrieve(corpus,queries,ROOT/'.modelos',out,lock)
    vectors=np.load(out/'document_vectors.npy');qvectors=np.load(out/'query_vectors.npy')
    started=time.perf_counter()
    km=KMeans(n_clusters=plan['clusters'],random_state=plan['seed'],n_init=10).fit(vectors)
    np.save(out/'centers.npy',km.cluster_centers_);np.save(out/'labels.npy',km.labels_)
    build_seconds=time.perf_counter()-started;ids=[d['id'] for d in corpus];rows=[]
    for qi,(q,r) in enumerate(zip(queries,rankings)):
        allowed=[i for i,d in enumerate(corpus) if eligible(d,q)]
        exact=[x['id'] for x in r['dense']]
        # Relevância incompleta deliberada: julga necessários e distratores nomeados.
        judgments={d['id']:0 for d in corpus if d['id'].startswith('DIS-')}
        judgments.update({x:2 for x in refs[q['id']]['required_ids']})
        anns={}
        for probe in plan['nprobe']:
            began=time.perf_counter();a=approximate(vectors,qvectors[qi],allowed,ids,km.cluster_centers_,km.labels_,probe)
            a['seconds']=time.perf_counter()-began
            a['recall_exact']=ann_recall([x['id'] for x in a['ranking']],exact)
            a['relevance']=ranking_metrics([x['id'] for x in a['ranking']],refs[q['id']]['required_ids'])
            anns[str(probe)]=a
        rows.append({'query_id':q['id'],'family':q['family'],'ann':anns,'qrels':judgments,
                     'judged':{key:judged_metrics([x['id'] for x in r[key]],judgments) for key in ['bm25','dense','hybrid_rerank']}})
    save(out/'ann.json',{'rows':rows,'build_seconds':build_seconds,'algorithm':'KMeans Euclidean IVF, full float32 vectors, cosine final ranking',
                        'library':'sklearn; not Faiss','training_documents':len(corpus)})
    # Bundles versionados de L24: inferência adicional real dos mesmos pesos.
    encoder=SentenceTransformer(str(ROOT/'.modelos/embedding'),device='cpu',local_files_only=True,trust_remote_code=False)
    bundles=[]
    for version,value in [('v1','90'),('v2','140')]:
        docs=[{'id':'NET','tenant':'alpha','version':version,'text':f'O auxílio mensal para internet é R$ {value}.'},
              {'id':'OTHER','tenant':'beta','version':version,'text':'O auxílio mensal para internet é R$ 900.'}]
        emb=encoder.encode([d['text'] for d in docs],normalize_embeddings=True,convert_to_numpy=True)
        bundle={'id':version,'version':version,'embedding':lock['artifacts'][0]['revision'],'documents':docs,'vectors':emb.tolist()}
        save(out/('bundle_'+version+'.json'),bundle);bundles.append(bundle)
    question='Qual é o auxílio mensal para internet?'
    vector=encoder.encode([question],normalize_embeddings=True,convert_to_numpy=True)[0].tolist()
    save(out/'update_query.json',{'tenant':'alpha','question':question,'vector':vector})
    return corpus,queries,refs,rankings


def run_child(out,args,name):
    log=out/(name+'.stdout.txt');err=out/(name+'.stderr.txt')
    with log.open('xb') as f,err.open('xb') as e:
        p=subprocess.Popen([sys.executable,'-m','laboratorios.parte_vi.store',*map(str,args)],cwd=ROOT,stdout=f,stderr=e,creationflags=FLAGS)
        code=p.wait(timeout=30)
    return {'pid':p.pid,'exit_code':code,'stdout':log.name,'stderr':err.name}


def updates(out):
    db=out/'assistant.sqlite';store.init(db)
    for v in ['v1','v2']:store.stage(db,load(out/('bundle_'+v+'.json')))
    request=load(out/'update_query.json');qargs=(db,request['tenant'],request['question'],request['vector'])
    store.publish(db,'v1');events=[{'step':'first','result':store.query(*qargs)},{'step':'cache_hit','result':store.query(*qargs)}]
    stale=events[0]['result']['response']
    events.append({'step':'crash_before_commit','process':run_child(out,['--db',db,'--action','publish','--bundle','v2','--crash','before_commit'],'crash_before')})
    events.append({'step':'after_failed_publish','result':store.query(*qargs)})
    children=[];handles=[]
    try:
        for mode in ['safe','unsafe']:
            f=(out/(mode+'.stdout.txt')).open('xb');e=(out/(mode+'.stderr.txt')).open('xb');handles.extend([f,e])
            args=[sys.executable,'-m','laboratorios.parte_vi.store','--db',str(db),'--action','read','--input',str(out/'update_query.json'),
                  '--out',str(out/(mode+'_read.json')),'--ready',str(out/(mode+'_ready.json')),'--go',str(out/'go.json')]
            if mode=='unsafe':args.append('--unsafe')
            p=subprocess.Popen(args,cwd=ROOT,stdout=f,stderr=e,creationflags=FLAGS);children.append((mode,p))
            wait_file(out/(mode+'_ready.json'),p,20)
        began=time.perf_counter();store.publish(db,'v2')
        events.append({'step':'publish_v2','seconds':time.perf_counter()-began,'epoch':store.snapshot(db)['epoch']})
        save(out/'go.json',{'released_at':time.time()})
        for mode,p in children:
            rc=p.wait(timeout=30);assert rc==0
            events.append({'step':mode+'_inflight','process':{'pid':p.pid,'exit_code':rc},'result':load(out/(mode+'_read.json'))})
    finally:
        for _,p in children:
            if p.poll() is None:p.terminate();p.wait(5)
        for h in handles:h.close()
    events.append({'step':'current_v2','result':store.query(*qargs)})
    events.append({'step':'naive_query_only_cache','response':stale,'current_epoch':store.snapshot(db)['epoch'],
                   'note':'Counterexample: a deliberately query-only dictionary returns saved v1, without calling safe cache'})
    events.append({'step':'crash_after_commit','process':run_child(out,['--db',db,'--action','publish','--bundle','v1','--crash','after_commit'],'crash_after')})
    events.append({'step':'rollback_confirmed','result':store.query(*qargs)})
    pending=store.candidate(store.snapshot(db),request['tenant'],request['question'],request['vector'])
    store.revoke(db,'NET');events.append({'step':'revoked_inflight','result':store.deliver(db,pending)})
    events.append({'step':'after_revoke','result':store.query(*qargs)})
    store.publish(db,'v2','rollback_or_republish_after_revoke')
    events.append({'step':'revocation_survives_republish','result':store.query(*qargs)})
    with store.connection(db) as c:
        history=list(c.execute('SELECT * FROM history ORDER BY epoch'));c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    save(out/'updates.json',{'events':events,'history':history,'all_child_processes_ended':all(p.poll() is not None for _,p in children),
                           'scope':'Real SQLite/processes and learned vectors; extractive response; scheduled barriers, not a load benchmark'})


def context(ids,docs,restored=False):
    return {'text':'\n\n'.join(f'[{i}] versão {docs[i]["version"]}: '+docs[i]['source_text' if restored else 'text'] for i in ids),
            'ids':ids,'skipped':[],'source_restored':restored}


def generation(out, corpus, queries, refs, rankings, plan):
    docs={d['id']:d for d in corpus};ranking={r['query_id']:r for r in rankings}
    selected=[q for q in queries if q['id'].endswith('Q1')];jobs=[]
    for q in selected:
        for variant in plan['retrievers']+plan['diagnostics']:
            ids=refs[q['id']]['required_ids'] if variant=='reference' else [] if variant=='empty' else [r['id'] for r in ranking[q['id']][variant][:3]]
            ctx=context(ids,docs,variant=='reference')
            for model in plan['models']:
                for seed in plan['seeds']:
                    jobs.append({'id':f'{q["id"]}_{variant}_{model}_{seed}','query_id':q['id'],'family':q['family'],
                        'model':model,'seed':seed,'variant':variant,'question':q['question'],'context':ctx})
    random.Random(plan['order_seed']).shuffle(jobs);save(out/'admissions.json',jobs)
    assert len(jobs)==plan['total_calls'];lock=load(ROOT/'materiais/l11/modelos.lock.json');rows=[]
    started=time.monotonic();(out/'raw').mkdir()
    for model in plan['models']:
        with server(ROOT/'.modelos/l11',model,lock,out,plan) as url:
            for job in [j for j in jobs if j['model']==model]:
                if time.monotonic()-started>plan['max_seconds']:raise TimeoutError('Orçamento global')
                ctx=job['context'];ntokens=len(http(url+'/tokenize',{'content':ctx['text'],'add_special':False})['tokens'])
                if ntokens>plan['document_budget']:raise ValueError('Contexto não cabe; não truncar silenciosamente')
                msgs=messages(job['question'],ctx['text'])
                msgs[0]['content']+=' Em citacoes use apenas IDs como FER-E, sem colchetes, versão ou texto do documento.'
                payload={'model':'l11-'+model,'messages':msgs,'temperature':plan['temperature'],'top_p':plan['top_p'],
                         'seed':job['seed'],'max_tokens':plan['max_tokens'],
                         'response_format':{'type':'json_schema','json_schema':{'name':'response','strict':True,'schema':SCHEMA}}}
                save(out/'raw'/(job['id']+'.request.json'),payload);began=time.perf_counter()
                response=http(url+'/v1/chat/completions',payload,timeout=plan['timeout_seconds']);seconds=time.perf_counter()-began
                save(out/'raw'/(job['id']+'.response.json'),response)
                try:parsed=parse_response(response);error=None
                except (ValueError,KeyError,IndexError,TypeError) as exc:parsed=None;error=str(exc)
                row=dict(job,context=dict(ctx,tokens=ntokens),seconds=seconds,parsed=parsed,error=error)
                row['observed']=observe(row,refs[job['query_id']],docs);rows.append(row)
                save(out/'raw'/(job['id']+'.observation.json'),row)
                if len(rows)%24==0:print(f'Geração {len(rows)}/{len(jobs)}',flush=True)
    save(out/'generation.json',rows)
    group=defaultdict(list)
    for r in rows:group[r['model']+'/'+r['variant']].append(r)
    summary={k:{'calls':len(v),'valid':sum(r['parsed'] is not None for r in v),
                'signal':sum(r['observed']['automatic_contract_signal'] for r in v),
                'with_valid_citation':sum(r['observed']['citations_present'] and r['observed']['citation_ids_valid'] for r in v),
                'seconds_sum':sum(r['seconds'] for r in v)} for k,v in group.items()}
    save(out/'generation_summary.json',summary)
    # Pacote complementar de 24 itens, sem preencher julgamentos humanos.
    sample=[r for r in rows if r['variant']=='reference' and r['seed']==plan['seeds'][0]]
    random.Random(624).shuffle(sample)
    items=[{'item':f'VI-{i+1:02d}','question':r['question'],'context':r['context']['text'],
            'answer':load(out/'raw'/(r['id']+'.response.json'))['choices'][0]['message']['content']} for i,r in enumerate(sample)]
    save(out/'human_items.json',items);save(out/'human_coordinator.json',{x['item']:r['id'] for x,r in zip(items,sample)})
    for reviewer in ['A','B']:
        save(out/('human_'+reviewer+'.json'),[{'item':i['item'],'support':None,'completeness':None,'abstention':None,'notes':None} for i in items])


def run(out):
    if out.exists():raise FileExistsError('Captura existente')
    out.mkdir(parents=True);shutil.copytree(ROOT/'materiais/parte_vi',out/'material')
    shutil.copytree(Path(__file__).parent,out/'code',ignore=shutil.ignore_patterns('__pycache__'))
    shared=['laboratorios/parte_i/common.py','laboratorios/l23/core.py','laboratorios/l23/models.py','laboratorios/l11/core.py','laboratorios/l11/runtime.py']
    save(out/'shared_code.json',{p:sha(ROOT/p) for p in shared})
    plan=load(out/'material/plano.json');started=time.perf_counter()
    save(out/'started.json',{'utc':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),'python':platform.python_version(),'plan_sha256':sha(out/'material/plano.json')})
    ingest(out,out/'material');corpus,queries,refs,ranking=retrieval(out,plan['retrieval'])
    updates(out);generation(out,corpus,queries,refs,ranking,plan['generation'])
    save(out/'complete.json',{'seconds':time.perf_counter()-started,'utc':datetime.now(timezone.utc).isoformat(),
                            'status':'complete','human_judgments':0,'paid_api_calls':0})
    seal(out,'Parte VI: execução de ingestão, embeddings, ANN, reranker, dois geradores e SQLite')
    print({'capture':str(out),'complete':True},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();run(a.out)
