"""Campanha congelada: material, treino, inferência, HTTP e dados brutos."""
from pathlib import Path
import argparse,os,shutil,time,tracemalloc
from laboratorios.parte_i.common import ROOT,load,save,seal,child,wait_file
from . import l05,l07,l08,stats


def run(out):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    start=time.perf_counter();tracemalloc.start()
    shutil.copytree(ROOT/'materiais/parte_ii',out/'materials')
    shutil.copytree(Path(__file__).parent,out/'code',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(ROOT/'laboratorios/parte_i/common.py',out/'shared_common.py')
    import platform,sys
    save(out/'environment.json',{'python':sys.version,'platform':platform.platform(),
        'cpu_logical':os.cpu_count(),'dependencies':'standard library only',
        'model':'Own logistic training in CPU Python float; no downloaded weights',
        'scope':'Local Windows; synthetic data; no people, paid API or production traffic'})
    p=load(out/'materials/plano.json')
    save(out/'l05.json',l05.run(load(out/'materials/catalog.json')))
    cov=stats.coverage(**p['l06']);save(out/'l06/coverage.json',cov)
    groups=[[1.]*5]*16+[[0.]*5]*4
    save(out/'l06/bootstrap.json',{'group':stats.bootstrap_groups(groups),
        'naive_rows':stats.bootstrap_groups([[x] for g in groups for x in g]),
        'zero_failures_30_upper':stats.zero_upper(30),'zero_failures_1pct_n':stats.minimum_zero_sample(.01),
        'missing_80_10_10':stats.missing_bounds(80,10,10)})
    cfg=p['l07'];d=out/'l07';d.mkdir()
    train=l07.dataset(cfg['train_seed'],cfg['train_groups'],cfg['rows_per_group'],'D')
    test=l07.dataset(cfg['test_seed'],cfg['test_groups'],cfg['rows_per_group'],'T')
    save(d/'train.json',train);save(d/'test.json',test)
    admitted=l07.schedule(test,cfg);save(d/'admitted.json',admitted)
    models={};training=[];warmups=[]
    for kind in cfg['candidates']:
        begin=time.perf_counter();model=l07.fit(train,kind,cfg['epochs'],cfg['learning_rate'],cfg['l2'])
        training.append({'candidate':kind,'seconds':time.perf_counter()-begin})
        models[kind]=model;save(d/'models'/(kind+'.json'),model)
        for i in range(cfg['warmups_each']):
            begin=time.perf_counter_ns();raw=l07.predict(model,train[i]['x'])
            warmups.append({'candidate':kind,'case':train[i]['id'],'raw':raw,
                            'seconds':(time.perf_counter_ns()-begin)/1e9})
    save(d/'training.json',training);save(d/'warmups.json',warmups)
    observations=l07.infer(models,test,admitted);save(d/'observations.json',observations)
    save(d/'summary.json',l07.analyze(test,observations,cfg))
    d=out/'l08';d.mkdir();rows=l08.cases();save(d/'cases.json',rows)
    jobs=l08.plan_requests(rows,p['l08']['order_seed']);save(d/'admitted.json',jobs)
    observations=[]
    with child('laboratorios.parte_ii.l08',['--root',d,'--ready',d/'ready.json'],d/'process') as proc:
        wait_file(d/'ready.json',proc);ready=load(d/'ready.json')
        for job in jobs:
            begin=time.perf_counter();status,response=l08.request('http://127.0.0.1:'+str(ready['port']),job)
            observations.append({'request':job,'status':status,'response':response,
                                 'seconds':time.perf_counter()-begin,'client_pid':os.getpid()})
    save(d/'process_exit.json',{'pid':proc.pid,'exit_code':proc.returncode})
    save(d/'observations.json',observations);save(d/'summary.json',l08.analyze(rows,observations))
    cfg=p['l08'];seq=stats.sequential(cfg['sequential_seed'],cfg['trials'],cfg['looks'],cfg['alpha'])
    save(d/'sequential.json',seq)
    save(d/'exposure.json',l08.exposure(cfg['exposure_seed'],cfg['exposure_groups'],cfg['users_per_group']))
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    save(out/'execution.json',{'elapsed_seconds_before_seal':time.perf_counter()-start,
        'parent_python_allocation_peak_bytes':peak,'memory_excludes_child_and_native':True,
        'disk_bytes_before_execution_record':sum(f.stat().st_size for f in out.rglob('*') if f.is_file()),
        'test_predictions':len(admitted),'warmup_predictions':len(warmups),
        'http_requests':len(jobs),'paid_calls':0,'human_reviews':0})
    seal(out,'parte_ii_computational_capture',True)
    print({'out':str(out),'predictions':len(admitted),'http':len(jobs)})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();run(a.out)
