"""Plano pequeno congelado: serviço mutante, fixture humana e campanha L12 real."""
from pathlib import Path
from contextlib import ExitStack
import argparse,shutil,sys,time,platform
from laboratorios.parte_i.common import ROOT,load,save,seal,sha,digest,child,wait_file
from laboratorios.l11.runtime import http,server
from . import l09,l10,l12

def service(stack,role,folder,config):
    folder.mkdir();p=stack.enter_context(child('laboratorios.parte_iii.l12',[role,'--folder',folder,'--config',config],folder/'process'))
    wait_file(folder/'ready.json',p);return 'http://127.0.0.1:'+str(load(folder/'ready.json')['port'])

def run_l09(out):
    out.mkdir();ops=l09.operations();save(out/'operations.json',ops);summaries={}
    for variant in l09.VARIANTS:
        folder=out/variant;folder.mkdir();rows=[]
        with child('laboratorios.parte_iii.l09',['--folder',folder,'--variant',variant],folder/'process') as p:
            wait_file(folder/'ready.json',p);url='http://127.0.0.1:'+str(load(folder/'ready.json')['port'])
            for request in ops:
                observed=http(url+'/apply',request);state=http(url+'/state')
                rows.append({'request':request,'observed':observed,'state':state})
        save(folder/'observations.json',rows)
        summaries[variant]={'independent':l09.analyze(rows),'shared_rounding':l09.analyze(rows,True),
                            'self_consistency_only':all(r['observed']['balance']==r['state']['balance'] for r in rows)}
    save(out/'summary.json',summaries);return summaries

def run_l12(out,runtime,plan):
    out.mkdir();lock=load(ROOT/'materiais/l11/modelos.lock.json');save(out/'lock.json',lock)
    identity=digest({'weights':lock['downloads'][0]['sha256'],'runtime':lock['server_sha256'],
                     'request_code':sha(Path(l12.__file__)),'plan':plan})
    cases=l12.cases();save(out/'private_cases.json',cases)
    budget=l12.Budget(plan['calls_budget'])
    for case in cases:
        if budget.reserve(case['id'])!='reserved':raise RuntimeError('budget before admission')
    refusal=budget.reserve('T09')
    if refusal!='quota_rejected':raise RuntimeError('ninth request should not be admitted')
    save(out/'budget.json',{'limit':budget.limit,'events':budget.events})
    expected=[{'attempt':r['id']+'-1','case':r['id'],'candidate':identity,'judge':'exact-v1'} for r in cases]
    expected.append({'attempt':'T07-2','case':'T07','candidate':identity,'judge':'exact-v1'})
    save(out/'collector_config.json',{'expected':expected});save(out/'evaluator_config.json',{'cases':cases})
    save(out/'admitted.json',expected);save(out/'not_admitted.json',{'case':'T09','reason':refusal,'calls_reserved':len(budget.reservations)})
    starts=[];began=time.perf_counter()
    with ExitStack() as stack:
        collector=service(stack,'collector',out/'collector',out/'collector_config.json')
        evaluator=service(stack,'evaluator',out/'evaluator',out/'evaluator_config.json')
        url=stack.enter_context(server(runtime,'qwen',lock,out,plan))
        for case in cases:
            if time.perf_counter()-began>plan['max_seconds']:raise TimeoutError('campaign admission deadline')
            folder=out/case['id'];folder.mkdir();mode=plan['faults'][case['id']]
            config={'folder':str(folder),'model_url':url,'collector_url':collector,'evaluator_url':evaluator,
                    'mode':mode,'expected':next(e for e in expected if e['attempt']==case['id']+'-1'),'request':l12.request_for(case)}
            save(folder/'config.json',config)
            with child('laboratorios.parte_iii.l12',['worker','--config',folder/'config.json'],folder/'process1') as p:
                code=p.wait(timeout=120);starts.append({'case':case['id'],'attempt':config['expected']['attempt'],'exit_code':code,'pid':p.pid,'resume':False})
            if mode in ('crash_before_inference','crash_after_raw'):
                required=86 if mode=='crash_before_inference' else 87
                if code!=required:raise RuntimeError('fault point not reached')
                if mode=='crash_before_inference':config['expected']=next(e for e in expected if e['attempt']=='T07-2')
                save(folder/'resume_config.json',config)
                with child('laboratorios.parte_iii.l12',['worker','--config',folder/'resume_config.json','--resume'],folder/'process2') as p:
                    rc=p.wait(timeout=120);starts.append({'case':case['id'],'attempt':config['expected']['attempt'],'exit_code':rc,'pid':p.pid,'resume':True})
                    if rc!=0:raise RuntimeError('resume failed')
            elif code!=0:raise RuntimeError('worker failure')
            print('L12',case['id'],mode,flush=True)
        save(out/'before_close.json',http(collector+'/state'))
        save(out/'closure.json',http(collector+'/close',{}))
        save(out/'late_delivery.json',http(collector+'/callback',load(out/'T03/callback.json')))
        final=http(collector+'/state');save(out/'final_collector.json',final)
    save(out/'processes.json',starts)
    received=final['received'];states={}
    for row in cases:
        found=[p for p in received.values() if p['case']==row['id']]
        states[row['id']]='evaluated' if found and found[0]['valid'] else 'invalid' if found else 'unknown'
    report={'identity':identity,'created':100,'expires':plan['expiry_logical'],'tasks':states,'human_semantic_qualification':False,
            'accepted_correct':sum(p['correct'] for p in received.values()),'accepted_callbacks':len(received),
            'attempts':len(expected),'inference_requests':len(list(out.glob('T*/raw.json'))),'worker_starts':len(starts),
            'unknown_is_not_failure_rate':True,'attempt_states':l12.attempt_states(expected,received)}
    report['release_now']=l12.release(report,150,identity);report['release_later']=l12.release(report,201,identity)
    save(out/'report.json',report);return report

def run(out,runtime):
    out.mkdir(parents=True,exist_ok=False);start=time.perf_counter()
    shutil.copytree(ROOT/'materiais/parte_iii',out/'materials')
    shutil.copytree(Path(__file__).parent,out/'code',ignore=shutil.ignore_patterns('__pycache__'))
    shared=out/'shared';shared.mkdir()
    for rel in ['laboratorios/parte_i/common.py','laboratorios/l11/runtime.py','laboratorios/l11/core.py']:
        shutil.copy2(ROOT/rel,shared/(rel.replace('/','_')))
    save(out/'environment.json',{'python':platform.python_version(),'platform':platform.platform(),'dependencies':'psutil 7.1.0 and Python stdlib; model/runtime identified separately','profile':'D/O L09, D and pending H L10, historical M L11, new M/O L12'})
    a=run_l09(out/'l09');save(out/'l10_fixture.json',l10.fixture())
    plan=load(out/'materials/plano.json');b=run_l12(out/'l12',runtime,plan['L12'])
    save(out/'historical_l11.json',plan['L11'])
    save(out/'execution.json',{'seconds':time.perf_counter()-start,'new_llm_calls':b['inference_requests'],'L09_apply_requests':200,'L09_state_requests':200,'human_judgments':0,'historical_l11_not_reexecuted':True})
    seal(out,'parte-iii-principal');print('Capture sealed',out,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--runtime',type=Path,default=ROOT/'.modelos/l11');a=p.parse_args();run(a.out.resolve(),a.runtime.resolve())
