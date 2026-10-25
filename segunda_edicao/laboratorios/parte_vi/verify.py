"""Reconciliação sem novas inferências; os hashes não substituem as relações."""
from pathlib import Path
from collections import defaultdict
import argparse, math, sqlite3, json
import numpy as np
from laboratorios.parte_i.common import load, sha, check_manifest
from laboratorios.l23.core import bm25, rrf, eligible, parse_response, observe, messages, SCHEMA, ranking_metrics
from .ingest import parse, chunks, assess, catalog, eligible as eligible_meta
from .retrieval import approximate, ann_recall, judged_metrics, order
from .campaign import context
ROOT=Path(__file__).resolve().parents[2]


def same_rank(actual, expected, tolerance=1e-6):
    assert [r['id'] for r in actual]==[r['id'] for r in expected]
    assert all(math.isclose(a['score'],b['score'],abs_tol=tolerance,rel_tol=tolerance) for a,b in zip(actual,expected))


def verify(out):
    out=Path(out);manifest=check_manifest(out);assert manifest['complete']
    assert load(out/'complete.json')['status']=='complete'
    plan=load(out/'material/plano.json');assert sha(out/'material/plano.json')==load(out/'started.json')['plan_sha256']
    for name,h in plan['preserved_pilot'].items():assert sha(ROOT/'output'/name/'manifesto.json')==h
    # A fonte histórica congelada é a dependência da nova campanha, não uma cópia corrigida.
    source=ROOT/'output/l23_principal_v01/fontes'
    for name in ['corpus.json','consultas.json','referencias.json']:
        assert sha(source/name)==sha(ROOT/'materiais/l23'/name)
    corpus=load(source/'corpus.json')['documents'];queries=load(source/'consultas.json');refs=load(source/'referencias.json')
    qmap={q['id']:q for q in queries};docs={d['id']:d for d in corpus}
    ingestion=load(out/'ingestion.json');ir=load(out/'material/referencia_ingestao.json')['documents']
    for row in ingestion['rows']:
        parsed=parse((out/'material/fontes'/(row['document']+'.html')).read_text(encoding='utf-8'))
        assert row['parsed']==parsed;parts=chunks(parsed,row['strategy']);assert parts==row['chunks']
        assert row['audit']==assess(parts,ir[row['document']])
    all_docs=[(r['id'],parse((out/'material'/r['path']).read_text(encoding='utf-8'))) for r in load(out/'material/inventario.json')]
    assert ingestion['catalog']==catalog(all_docs)
    assert ingestion['release_after_quarantine']==catalog([(n,d) for n,d in all_docs if n!='jantar_v2_conflito'])
    assert ingestion['alpha_current']==[n for n,d in all_docs if eligible_meta(d['metadata'],'alpha','2026-10-24')]
    vectors=np.load(out/'document_vectors.npy');qvectors=np.load(out/'query_vectors.npy')
    centers=np.load(out/'centers.npy');labels=np.load(out/'labels.npy')
    assert vectors.shape==(30,384) and qvectors.shape==(48,384) and centers.shape==(8,384)
    assert np.isfinite(vectors).all() and np.isfinite(qvectors).all() and np.isfinite(centers).all()
    assert np.allclose(np.linalg.norm(vectors,axis=1),1,atol=1e-5)
    assert np.allclose(np.linalg.norm(qvectors,axis=1),1,atol=1e-5)
    assert labels.tolist()==np.argmin(((vectors[:,None,:]-centers[None,:,:])**2).sum(axis=2),axis=1).tolist()
    ranks=load(out/'retrieval.json');assert [r['query_id'] for r in ranks]==[q['id'] for q in queries]
    ann=load(out/'ann.json');assert [r['query_id'] for r in ann['rows']]==[q['id'] for q in queries]
    ids=[d['id'] for d in corpus]
    for qi,(q,r,a) in enumerate(zip(queries,ranks,ann['rows'])):
        allowed=[d for d in corpus if eligible(d,q)];indices=[i for i,d in enumerate(corpus) if eligible(d,q)]
        assert r['eligible_ids']==[d['id'] for d in allowed]
        same_rank(r['bm25'],bm25(q['question'],allowed));same_rank(r['dense'],order(vectors,qvectors[qi],indices,ids))
        same_rank(r['rrf_candidates'],rrf([r['bm25'][:8],r['dense'][:8]])[:8])
        assert {x['id'] for x in r['hybrid_rerank']}=={x['id'] for x in r['rrf_candidates']}
        assert r['hybrid_rerank']==sorted(r['hybrid_rerank'],key=lambda x:(-x['score'],x['id']))
        judgments={d['id']:0 for d in corpus if d['id'].startswith('DIS-')};judgments.update({x:2 for x in refs[q['id']]['required_ids']})
        assert a['qrels']==judgments
        assert a['judged']=={key:judged_metrics([x['id'] for x in r[key]],judgments) for key in ['bm25','dense','hybrid_rerank']}
        for probe in plan['retrieval']['nprobe']:
            expected=approximate(vectors,qvectors[qi],indices,ids,centers,labels,probe);actual=a['ann'][str(probe)]
            assert actual['cells']==expected['cells'] and actual['scanned']==expected['scanned']
            same_rank(actual['ranking'],expected['ranking'])
            assert actual['recall_exact']==ann_recall([x['id'] for x in expected['ranking']],[x['id'] for x in r['dense']])
            assert actual['relevance']==ranking_metrics([x['id'] for x in expected['ranking']],refs[q['id']]['required_ids'])
        assert a['ann']['8']['recall_exact']==1
    rankings={r['query_id']:r for r in ranks};jobs=load(out/'admissions.json');rows=load(out/'generation.json')
    expected={f'{q["id"]}_{v}_{m}_{s}' for q in queries if q['id'].endswith('Q1') for v in ['bm25','hybrid_rerank','reference','empty'] for m in ['qwen','smol'] for s in [23,41]}
    assert len(jobs)==len(rows)==192 and {j['id'] for j in jobs}=={r['id'] for r in rows}==expected
    jmap={j['id']:j for j in jobs};group=defaultdict(list)
    for r in rows:
        q=qmap[r['query_id']];variant=r['variant'];j=jmap[r['id']]
        needed=refs[q['id']]['required_ids'] if variant=='reference' else [] if variant=='empty' else [x['id'] for x in rankings[q['id']][variant][:3]]
        ctx=context(needed,docs,variant=='reference');assert j['context']==ctx
        assert all(r[k]==v for k,v in j.items() if k!='context')
        assert r['question']==q['question'] and r['family']==q['family']
        assert all(r['context'][k]==v for k,v in ctx.items())
        assert 0<=r['context']['tokens']<=plan['generation']['document_budget']
        req=load(out/'raw'/(r['id']+'.request.json'));response=load(out/'raw'/(r['id']+'.response.json'))
        msgs=messages(q['question'],ctx['text']);msgs[0]['content']+=' Em citacoes use apenas IDs como FER-E, sem colchetes, versão ou texto do documento.'
        assert req=={'model':'l11-'+r['model'],'messages':msgs,'temperature':.2,'top_p':.9,'seed':r['seed'],'max_tokens':128,
                     'response_format':{'type':'json_schema','json_schema':{'name':'response','strict':True,'schema':SCHEMA}}}
        try:parsed=parse_response(response);error=None
        except (ValueError,KeyError,IndexError,TypeError) as exc:parsed=None;error=str(exc)
        assert r['parsed']==parsed and r['error']==error
        assert r['observed']==observe(r,refs[q['id']],docs)
        assert r==load(out/'raw'/(r['id']+'.observation.json'));group[r['model']+'/'+variant].append(r)
    expected_summary={k:{'calls':len(v),'valid':sum(r['parsed'] is not None for r in v),
                        'signal':sum(r['observed']['automatic_contract_signal'] for r in v),
                        'with_valid_citation':sum(r['observed']['citations_present'] and r['observed']['citation_ids_valid'] for r in v),
                        'seconds_sum':sum(r['seconds'] for r in v)} for k,v in group.items()}
    assert load(out/'generation_summary.json')==expected_summary
    lock=load(out/'material/geradores.lock.json')
    for model in ['qwen','smol']:
        resource=load(out/(model+'_resources.json'))
        item=next(x for x in lock['downloads'] if x['id']==model)
        assert resource['process_ended'] and resource['model_sha256']==item['sha256']
        assert resource['runtime_sha256']==lock['server_sha256']
    u=load(out/'updates.json');events={x['step']:x for x in u['events']}
    assert events['crash_before_commit']['process']['exit_code']==events['crash_after_commit']['process']['exit_code']==86
    assert events['after_failed_publish']['result']['response']['epoch']==1
    assert events['safe_inflight']['result']['delivery']['served'] is False
    assert events['unsafe_inflight']['result']['delivery']['response']['epoch']==1
    assert events['current_v2']['result']['response']['epoch']==2
    assert events['rollback_confirmed']['result']['response']['epoch']==3
    assert events['revoked_inflight']['result']['served'] is False
    for step in ['after_revoke','revocation_survives_republish']:
        assert events[step]['result']['response']['answer']=='SEM EVIDÊNCIA'
        assert events[step]['result']['response']['citations']==[]
    assert u['all_child_processes_ended'] and len(u['history'])==4
    db=sqlite3.connect((out/'assistant.sqlite').resolve().as_uri()+'?immutable=1',uri=True)
    try:
        assert [list(r) for r in db.execute('SELECT * FROM history ORDER BY epoch')]==u['history']
        assert db.execute('SELECT bundle,epoch,auth_epoch FROM active').fetchone()==('v2',4,1)
        assert list(db.execute('SELECT doc FROM revoked'))==[('NET',)]
        for version in ['v1','v2']:
            stored=db.execute('SELECT payload FROM bundles WHERE id=?',(version,)).fetchone()[0]
            assert json.loads(stored)==load(out/('bundle_'+version+'.json'))
    finally:db.close()
    items=load(out/'human_items.json');mapping=load(out/'human_coordinator.json')
    assert len(items)==len(mapping)==24
    rmap={r['id']:r for r in rows}
    for item in items:
        r=rmap[mapping[item['item']]]
        assert r['variant']=='reference' and r['seed']==23
        assert item['question']==r['question'] and item['context']==r['context']['text']
        assert item['answer']==load(out/'raw'/(r['id']+'.response.json'))['choices'][0]['message']['content']
    for reviewer in ['A','B']:
        form=load(out/('human_'+reviewer+'.json'));assert len(form)==24
        assert all(all(r[k] is None for k in ['support','completeness','abstention','notes']) for r in form)
    return {'calls':len(rows),'retrieval_queries':len(ranks),'ingestion_variants':len(ingestion['rows']),
            'manifest_files':len(manifest['files']),'process_crashes':2,'human_judgments':0,'all_relations_checked':True}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();print(verify(a.out))
