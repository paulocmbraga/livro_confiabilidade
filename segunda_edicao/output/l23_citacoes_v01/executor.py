"""Isola a clareza do contrato de IDs; conserva a campanha principal intacta."""
from pathlib import Path
import argparse,copy,json,random,shutil,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from laboratorios.l23.campaign import load,seal,verify
from laboratorios.l23.core import digest,observe,parse_response,sha
from laboratorios.l23.models import server,http,write

def summarize(rows):
    result={}
    for condition in ['original','explicit_ids']:
        r=[r for r in rows if r['condition']==condition]
        result[condition]={'calls':len(r),'valid':sum(x['parsed'] is not None for x in r),
             'cited_and_ids_valid':sum(x['observed']['citations_present'] and x['observed']['citation_ids_valid'] for x in r),
             'no_citation_among_valid':sum(x['parsed'] is not None and not x['parsed']['citacoes'] for x in r),
             'abstained_among_valid':sum(x['parsed'] is not None and x['parsed']['abster'] for x in r),
             'automatic_contract_signal':sum(x['observed']['automatic_contract_signal'] for x in r),
             'input_tokens':sum(x['response']['usage']['prompt_tokens'] for x in r),
             'output_tokens':sum(x['response']['usage']['completion_tokens'] for x in r)}
    return result

def expected_jobs(source,plan):
    queries=load(source/'fontes/consultas.json');chosen={}
    for q in queries:chosen.setdefault(q['family'],q['id'])
    originals=[load(p) for p in sorted((source/'raw').glob('*.json'))]
    originals=[r for r in originals if r['phase']=='primary' and r['policy']=='top3' and r['repeat']==0 and r['query_id']==chosen[r['family']]]
    jobs=[dict(id=r['id']+'_'+condition,condition=condition,source_id=r['id']) for r in originals for condition in plan['conditions']]
    random.Random(plan['order_seed']).shuffle(jobs)
    return jobs,{r['id']:r for r in originals}

def run(source,out,runtime):
    verify(source)
    if out.exists():raise FileExistsError(out)
    out.mkdir(parents=True);(out/'raw').mkdir()
    shutil.copyfile(ROOT/'materiais/l23_diagnostico_citacoes/plano.json',out/'plano.json')
    shutil.copyfile(__file__,out/'executor.py')
    plan=load(out/'plano.json');jobs,originals=expected_jobs(source,plan)
    write(out/'admissions.json',jobs)
    write(out/'source.json',{'path':str(source.relative_to(ROOT)),'manifest_sha256':sha(source/'manifesto.json')})
    docs={d['id']:d for d in load(source/'fontes/corpus.json')['documents']};refs=load(source/'fontes/referencias.json')
    rows=[];start=time.monotonic()
    try:
        with server(runtime,out,load(source/'fontes/modelos.lock.json')) as url:
            for job in jobs:
                original=originals[job['source_id']];request=copy.deepcopy(original['request'])
                if job['condition']=='explicit_ids':request['messages'][0]['content']+=plan['addition']
                row={**job,'request':request,'prompt_sha256':digest(request),'context':original['context'],'family':original['family'],
                     'query_id':original['query_id'],'parsed':None,'error':None,'real_inference':True}
                write(out/'raw'/f"{job['id']}.pending.json",row);tick=time.monotonic()
                row['response']=http(url+'/v1/chat/completions',request)
                try:row['parsed']=parse_response(row['response'])
                except (ValueError,KeyError,TypeError,IndexError) as e:row['error']=type(e).__name__+': '+str(e)
                row['seconds']=round(time.monotonic()-tick,5);row['observed']=observe(row,refs[row['query_id']],docs)
                write(out/'raw'/f"{job['id']}.json",row);(out/'raw'/f"{job['id']}.pending.json").unlink();rows.append(row)
                if len(rows)%12==0:print(str(len(rows))+'/48 diagnósticos',flush=True)
        write(out/'results.json',summarize(rows));write(out/'state.json',{'status':'complete','calls':len(rows),'elapsed_seconds':round(time.monotonic()-start,3)})
    except BaseException as e:
        write(out/'state.json',{'status':'incomplete','calls':len(rows),'error':str(e)});raise
    finally:seal(out)
    print(json.dumps(summarize(rows),ensure_ascii=False))

def check(source,out):
    manifest=load(out/'manifesto.json')
    assert set(manifest['files'])=={p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file() and p.name!='manifesto.json'}
    for rel,expected in manifest['files'].items():assert sha(out/rel)==expected
    verify(source);assert sha(source/'manifesto.json')==load(out/'source.json')['manifest_sha256']
    plan=load(out/'plano.json');jobs,originals=expected_jobs(source,plan);assert len(jobs)==plan['calls']==48
    assert jobs==load(out/'admissions.json');assert load(out/'state.json')['status']=='complete'
    assert len(list((out/'raw').glob('*.json')))==48
    docs={d['id']:d for d in load(source/'fontes/corpus.json')['documents']};refs=load(source/'fontes/referencias.json');rows=[]
    for j in jobs:
        r=load(out/'raw'/f"{j['id']}.json");original=originals[j['source_id']]
        expected=copy.deepcopy(original['request'])
        if j['condition']=='explicit_ids':expected['messages'][0]['content']+=plan['addition']
        assert all(r[k]==v for k,v in j.items());assert r['request']==expected and r['prompt_sha256']==digest(expected)
        assert r['context']==original['context'];parsed=None
        try:parsed=parse_response(r['response'])
        except (ValueError,KeyError,TypeError,IndexError):pass
        assert parsed==r['parsed'] and (r['error'] is not None)==(parsed is None)
        assert r['observed']==observe(r,refs[r['query_id']],docs);rows.append(r)
    assert summarize(rows)==load(out/'results.json');assert load(out/'generation_resources.json')['process_ended']
    return {'calls':48,'complete':True,'classification':'exploratory','semantic_approval':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['run','verify']);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--source',type=Path,default=ROOT/'output/l23_principal_v01');p.add_argument('--runtime',type=Path,default=ROOT.parent/'tmp/seguranca_m1');a=p.parse_args()
    if a.action=='run':run(a.source.resolve(),a.out.resolve(),a.runtime.resolve())
    else:print(json.dumps(check(a.source.resolve(),a.out.resolve()),ensure_ascii=False))
