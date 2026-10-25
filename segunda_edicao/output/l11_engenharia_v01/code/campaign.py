"""400 inferências sem retry; saída bruta, código, plano e contabilização preservados."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,shutil,time
from .core import ROOT,MATERIALS,JUDGES,load,save,sha,schedule,request,parse,summarize
from .runtime import server,http

def run(out,runtime,smoke=False):
    out.mkdir(parents=True,exist_ok=False);(out/'raw').mkdir()
    shutil.copytree(MATERIALS,out/'materials')
    shutil.copytree(Path(__file__).parent,out/'code',ignore=shutil.ignore_patterns('__pycache__'))
    pairs=load(out/'materials/pares.json');plan=load(out/'materials/plano.json')
    lock=load(out/'materials/modelos.lock.json');rubric=(out/'materials/rubrica.txt').read_text(encoding='utf-8')
    trials=schedule(pairs,smoke);save(out/'schedule.json',trials)
    state={'started_utc':datetime.now(timezone.utc).isoformat(),'status':'running','smoke':smoke,'planned':len(trials)}
    save(out/'state.json',state);rows=[];start=time.perf_counter()
    try:
        for judge in JUDGES:
            with server(runtime,judge,lock,out,plan) as url:
                for trial in [t for t in trials if t['judge']==judge]:
                    if time.perf_counter()-start>plan['max_seconds']:raise TimeoutError('orçamento total')
                    pair=next(p for p in pairs if p['id']==trial['pair']);req=request(pair,trial,rubric)
                    before=time.perf_counter();response=None;error=None
                    try:response=http(url+'/v1/chat/completions',req,plan['request_timeout_seconds'])
                    except Exception as exc:error={'type':type(exc).__name__,'detail':str(exc)}
                    row={'trial':trial,'request':req,'response':response,'error':error,
                         'seconds':round(time.perf_counter()-before,6),
                         'parsed':parse(response,trial['order'],error)}
                    save(out/'raw'/(trial['id']+'.json'),row);rows.append(row)
                    if len(rows)%20==0 or smoke:print(f'{len(rows)}/{len(trials)} {trial["id"]}',flush=True)
        if not smoke:save(out/'summary.json',summarize(rows,pairs))
        state.update(status='complete',finished_utc=datetime.now(timezone.utc).isoformat(),
                     completed=len(rows),elapsed_seconds=round(time.perf_counter()-start,3))
        save(out/'state.json',state)
        files={p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
        save(out/'manifesto.json',{'version':'L11-1.0','files':files})
        print('Captura selada:',out,flush=True)
    except BaseException as exc:
        state.update(status='incomplete',completed=len(rows),error=type(exc).__name__+': '+str(exc));save(out/'state.json',state)
        raise

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True,type=Path)
    p.add_argument('--runtime',type=Path,default=ROOT/'.modelos/l11');p.add_argument('--smoke',action='store_true');a=p.parse_args()
    run(a.out.resolve(),a.runtime.resolve(),a.smoke)

if __name__=='__main__':main()
