"""New immutable campaign: real SGD, HTTP, drift interventions; no API costs."""
from pathlib import Path
import argparse,copy,json,os,platform,random,shutil,statistics,sys,threading,time
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import psutil
from laboratorios.parte_i.common import ROOT,load,save,seal,digest,child,wait_file
from laboratorios.parte_iv.core import generate,preprocessor,fit,predictions,identity,promote,features
from laboratorios.parte_iv.calibration import fit_calibrator,calibrate,conformal

def run(out):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    plan=load(ROOT/'materiais/parte_iv/plano.json');save(out/'plan.json',plan)
    for p in Path(__file__).parent.glob('*.py'):
        (out/'code').mkdir(exist_ok=True);shutil.copyfile(p,out/'code'/p.name)
    shutil.copyfile(ROOT/'laboratorios/parte_i/common.py',out/'code/common_shared.py')
    start=time.perf_counter();cpu=time.process_time();rss=[];stop=threading.Event()
    def sample():
        process=psutil.Process()
        while not stop.wait(.02):
            rss.append(process.memory_info().rss)
    thread=threading.Thread(target=sample,daemon=True);thread.start()
    try:
        data={name:generate(n,plan['seed_data']+i,name,i*10000, name.startswith('adapt') or name=='future')
              for i,(name,n) in enumerate(plan['partitions'].items())}
        save(out/'data.json',data);prep=preprocessor(data['train'])
        models={};tuning={};fits=[]
        for l2 in plan['l2']:
            for seed in plan['seeds']:
                key=f'l2_{l2}_seed_{seed}'
                model=fit(data['train'],prep,seed,plan['epochs'],plan['rate'],l2,plan['batch'])
                models[key]=model;tuning[key]=predictions(model,data['tune']);fits.append(key)
        from laboratorios.parte_iv.core import metrics
        losses={str(l2):statistics.mean(metrics(data['tune'],tuning[f'l2_{l2}_seed_{s}'])['brier'] for s in plan['seeds']) for l2 in plan['l2']}
        chosen=min(plan['l2'],key=lambda v:(losses[str(v)],v));key=f'l2_{chosen}_seed_{plan["deployment_seed"]}'
        model=models[key];selection={'validation_brier':losses,'key':key,'identity':identity(model),'seed_preselected':13}
        save(out/'selection.json',selection);save(out/'tuning.json',tuning)
        tests={k:predictions(m,data['test']) for k,m in models.items()}
        # Deliberately leaky diagnostic, never eligible for selection or registration.
        models['leaky']=fit(data['train'],prep,future=True);fits.append('leaky')
        tests['leaky']=predictions(models['leaky'],data['test'])
        models['adapted']=fit(data['adapt_train'],prep,initial=model['weights']);fits.append('adapted')
        models['retrained']=fit(data['adapt_train'],preprocessor(data['adapt_train']));fits.append('retrained')
        noisy=copy.deepcopy(data['adapt_train'])
        # Asymmetric measurement errors, explicitly separate from latent synthetic truth.
        for i,r in enumerate(noisy):
            if r['group']=='vip' and i%2==0:r['y']=1-r['y']
        models['noisy_retrained']=fit(noisy,preprocessor(noisy));fits.append('noisy_retrained')
        save(out/'noisy_training.json',noisy)
        save(out/'models.json',models);save(out/'test_predictions.json',tests)
        registered=promote(model,identity(model),['train','tune']);swapped=copy.deepcopy(model);swapped['weights'][0]+=.1
        attacks={}
        for kind,m,access in [('swapped',swapped,['train','tune']),('test_access',model,['train','tune','test'])]:
            try:promote(m,identity(model),access);attacks[kind]='NOT_REJECTED'
            except ValueError as e:attacks[kind]=str(e)
        save(out/'promotion.json',{'registration':registered,'attacks':attacks,'scope':'local integrity guard; access log is cooperative, not a security boundary'})
        save(out/'selected_model.json',model)
        requests=[];admissions=[]
        with child('laboratorios.parte_iv.server',['--model',out/'selected_model.json','--out',out/'http'],out/'server_process') as proc:
            wait_file(out/'http/ready.json',proc);ready=load(out/'http/ready.json')
            for mode in plan['http_modes']:
                for i,original in enumerate(data['test'][:plan['http_cases']]):
                    r=copy.deepcopy(original)
                    if mode.startswith('unit'):
                        r['unit']='minute'
                        if r['age'] is not None:r['age']*=60
                    if mode=='category_guard':r['channel']='chat'
                    # Serving never receives the target or its availability metadata.
                    r.pop('y');r.pop('label_available')
                    attempt=f'{mode}-{i:03d}';payload={'attempt':attempt,'mode':mode,'row':r}
                    admissions.append({'attempt':attempt,'id':r['id'],'mode':mode})
                    request=Request(f'http://127.0.0.1:{ready["port"]}/predict',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
                    t=time.perf_counter()
                    try:
                        with urlopen(request,timeout=10) as response:status=response.status;raw=response.read()
                    except HTTPError as e:status=e.code;raw=e.read();e.close()
                    requests.append({'attempt':attempt,'id':r['id'],'mode':mode,'status':status,'response':json.loads(raw),'seconds':time.perf_counter()-t})
        save(out/'http_admissions.json',admissions);save(out/'http_observed.json',requests)
        save(out/'processes.json',{'server_pid':ready['pid'],'parent_pid':os.getpid(),'server_exit_code':proc.returncode,'alive_after':psutil.pid_exists(ready['pid'])})
        probraw=predictions(model,data['probcal']);cal=fit_calibrator(probraw,data['probcal'])
        confraw=predictions(model,data['confcal']);conf=conformal(calibrate(confraw,cal),data['confcal'],plan['alpha'])
        confgroups={g:conformal([o for o in calibrate(confraw,cal) if o['group']==g],[r for r in data['confcal'] if r['group']==g],plan['alpha']) for g in ['vip','regular']}
        save(out/'calibration.json',{'prob_raw':probraw,'calibrator':cal,'conf_raw':confraw,'conformal':conf,'group_conformal':confgroups})
        domains={'reference':copy.deepcopy(data['test'])}
        for kind in ['benign','concept_same_x','covariate']:
            rows=copy.deepcopy(data['test'])
            for r in rows:
                if kind=='benign':r['telemetry']+=5
                elif kind=='concept_same_x':r['y']=1-r['y']
                else:
                    # Selection from existing IDs would change support; generate fresh below.
                    pass
            if kind=='covariate':
                pool=generate(4000,1401,'covariate',80000)
                rows=[r for r in pool if r['age'] is not None and r['age']>36][:400]
            domains[kind]=rows
        pool=generate(4000,1402,'labelshift',130000)
        domains['label_shift']=[r for r in pool if r['y']==1][:320]+[r for r in pool if r['y']==0][:80]
        random.Random(1403).shuffle(domains['label_shift'])
        # Holdout is a new temporal cohort, disjoint from all intervention fitting.
        domains['future']=data['future'];save(out/'domains.json',domains)
        outputs={k:predictions(model,r) for k,r in domains.items()};save(out/'domain_predictions.json',outputs)
        interventions={'old':outputs['future']}
        for name in ['adapted','retrained','noisy_retrained']:
            interventions[name]=predictions(models[name],data['future'])
        old_adapt=predictions(model,data['adapt_cal']);recal=fit_calibrator(old_adapt,data['adapt_cal'])
        interventions['recalibrated']=calibrate(interventions['old'],recal)
        # Retention of previous capacity is measured separately from new-domain gain.
        retention={name:predictions(models[name],data['test']) for name in ['adapted','retrained','noisy_retrained']}
        save(out/'interventions.json',{'recalibrator':recal,'calibration_raw':old_adapt,'future':interventions,'retention':retention})
        # Bounding box on monitored telemetry is deliberately weak and transparent.
        detector={'feature':'telemetry','low':min(r['telemetry'] for r in data['train']),'high':max(r['telemetry'] for r in data['train'])}
        save(out/'detector.json',detector)
        from laboratorios.parte_iv.verify import analyze
        save(out/'results.json',analyze(out))
        save(out/'resources.json',{'fit_count':len(fits),'fits':fits,'fit_seconds':sum(models[k]['seconds'] for k in fits),
            'seconds':time.perf_counter()-start,'parent_cpu_seconds':time.process_time()-cpu,'parent_rss_peak_sampled':max(rss,default=psutil.Process().memory_info().rss),
            'rss_scope':'parent sampled every 20ms; child not included; short peaks may be missed',
            'python':platform.python_version(),'platform':platform.platform(),'psutil':psutil.__version__,
            'hardware':platform.processor(),'cpu_logical':os.cpu_count(),'paid_api_calls':0,'llm_calls':0,'human_judgments':0})
    finally:stop.set();thread.join(timeout=2)
    seal(out,'parte_iv_complete')
    print(json.dumps({'out':str(out),'fits':len(fits),'http':len(requests)},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();run(a.out)
