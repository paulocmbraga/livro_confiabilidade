"""Uma campanha local completa; pastas novas, originais conservados."""
from contextlib import ExitStack,closing
from pathlib import Path
import argparse, json, os, shutil, sqlite3, subprocess, sys, time
from .common import ROOT, FLAGS, load, save, sha, seal, environment, child, wait_file
from . import l01,l02,l03,l04

def observer(module,db,out):
    r=subprocess.run([sys.executable,'-m',module,'observe','--db',str(db),'--out',str(out)],
                     cwd=ROOT,capture_output=True,text=True,timeout=15,creationflags=FLAGS)
    if r.returncode:raise RuntimeError(r.stderr)

def run_service(root, cases, modes):
    root.mkdir(); module='laboratorios.parte_i.l03'; observations=[]
    with child(module,['collector','--ready',root/'collector_ready.json'],root/'collector') as collector:
        wait_file(root/'collector_ready.json',collector)
        url='http://127.0.0.1:'+str(load(root/'collector_ready.json')['port'])
        for mode in modes:
            d=root/mode;d.mkdir();db=d/'state.sqlite'
            with child(module,['service','--mode',mode,'--db',db,'--collector',url,
                       '--ready',d/'ready.json'],d/'service') as service:
                wait_file(d/'ready.json',service);ready=load(d/'ready.json')
                endpoint='http://127.0.0.1:'+str(ready['port'])
                for case in cases:
                    start=time.perf_counter();status,body=l03.request(endpoint,case)
                    out=d/(case['id']+'_observed.json');observer(module,db,out)
                    row={'mode':mode,'case':case['id'],'request':case,'http':status,'response':body,
                         'elapsed_seconds':time.perf_counter()-start,'service_pid':ready['pid'],
                         'observation':out.relative_to(root).as_posix()}
                    observations.append(row)
                status,health=l03.request(endpoint)
                save(d/'health_after.json',{'status':status,'health':health})
            save(d/'process_exit.json',{'pid':service.pid,'exit_code':service.returncode})
    save(root/'collector_exit.json',{'pid':collector.pid,'exit_code':collector.returncode})
    save(root/'requests.json',observations)

def run_workers(root, plan):
    root.mkdir();db=root/'journal.sqlite';l04.initialize(db,plan)
    for case in plan['cases']:save(root/'cases'/(case['id']+'.json'),case)
    module='laboratorios.parte_i.l04'; lifecycle=[]
    with ExitStack() as stack:
        workers={}
        for case in plan['cases']:
            aid=l04.admit(db,case['id'],1);d=root/'attempts'/aid;d.mkdir(parents=True)
            args=['worker','--db',db,'--root',root,'--folder',d,
                  '--case',root/'cases'/(case['id']+'.json'),'--attempt',aid]
            if case['id']==plan['kill_after_raw']:args+=['--after-raw']
            proc=stack.enter_context(child(module,args,d/'process'));workers[case['id']]=(aid,d,proc)
        for aid,d,proc in workers.values():wait_file(d/'ready.json',proc)
        # A barreira prova sobreposição: todos vivos antes de qualquer liberação.
        save(root/'barrier.json',{'at':time.time(),'pids':[p.pid for _,_,p in workers.values()],
                                 'all_alive':all(p.poll() is None for _,_,p in workers.values())})
        for cid,(aid,d,proc) in workers.items():
            if cid==plan['kill_before_raw']:proc.kill();proc.wait(timeout=5)
            else:save(d/'release.json',{'released_at':time.time()})
        aid,d,p=workers[plan['kill_after_raw']];wait_file(d/'after_raw.json',p);p.kill();p.wait(timeout=5)
        for cid,(aid,d,proc) in workers.items():
            proc.wait(timeout=15);lifecycle.append({'attempt':aid,'pid':proc.pid,'exit_code':proc.returncode})
    # Captura parcial é autossuficiente, anterior ao fechamento das tentativas mortas.
    partial=root/'partial';partial.mkdir()
    shutil.copytree(root/'attempts',partial/'attempts');shutil.copytree(root/'cases',partial/'cases')
    with closing(sqlite3.connect(db)) as src, closing(sqlite3.connect(partial/'journal.sqlite')) as dst:src.backup(dst)
    observer(module,partial/'journal.sqlite',partial/'observed.json')
    save(partial/'plan.json',plan);seal(partial,'l04_partial',False)
    for cid in (plan['kill_before_raw'],plan['kill_after_raw']):
        l04.conclude(db,workers[cid][0],'interrupted')
        aid=l04.admit(db,cid,2);d=root/'attempts'/aid;d.mkdir(parents=True)
        args=['worker','--db',db,'--root',root,'--folder',d,'--case',root/'cases'/(cid+'.json'),'--attempt',aid]
        with child(module,args,d/'process') as proc:
            wait_file(d/'ready.json',proc);save(d/'release.json',{'released_at':time.time()})
            proc.wait(timeout=15);lifecycle.append({'attempt':aid,'pid':proc.pid,'exit_code':proc.returncode})
            if proc.returncode:raise RuntimeError('Retomada falhou')
    observer(module,db,root/'observed.json')
    save(root/'processes.json',lifecycle)

def run(out):
    out=out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.perf_counter()
    materials=ROOT/'materiais/parte_i';shutil.copytree(materials,out/'materials')
    shutil.copytree(Path(__file__).parent,out/'code',ignore=shutil.ignore_patterns('__pycache__'))
    save(out/'environment.json',environment());plan=load(out/'materials/plano.json')
    save(out/'l01.json',l01.summarize(load(out/'materials/l01_cases.json')))
    sim=[]
    for scenario in plan['l02']['scenarios']:
        q,r=scenario['q'],scenario['r']
        sim.append({'scenario':scenario,'analytic':l02.analytic(q,r),
                    'enumeration':l02.enumerate_states(q,r),
                    'replicates':[l02.simulate(q,r,plan['l02']['n'],s) for s in plan['l02']['seeds']]})
    save(out/'l02.json',sim)
    run_service(out/'l03',load(out/'materials/l03_cases.json'),plan['l03']['modes'])
    run_workers(out/'l04',plan['l04'])
    save(out/'execution.json',{'elapsed_seconds':time.perf_counter()-start,'completed_at_epoch':time.time(),
        'controller_pid':os.getpid(),'paid_calls':0,'model_inferences':0,
        'disk_bytes_before_manifest':sum(p.stat().st_size for p in out.rglob('*') if p.is_file()),
        'memory_peak':'not instrumented; no minimum RAM claim','resources_cleanup':'owned child contexts exited'})
    seal(out,'parte_i');print(json.dumps({'capture':str(out),'seconds':time.perf_counter()-start}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);run(p.parse_args().out)
