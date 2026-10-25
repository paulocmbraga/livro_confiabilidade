"""python -m laboratorios.apendices.campaign --out output/minha_consulta_v01"""
from pathlib import Path
import argparse,json,platform,time
from hashlib import sha256
from .core import (wilson,zero_failure_n,grouped_bootstrap,outcome_bounds,
                   validate_case,Receipts,reconcile,burn,assess,unit_cost)

def run(out):
    out.mkdir(parents=True,exist_ok=False)
    start=time.perf_counter()
    case=dict(id='t-1',family='f-1',event_at='2026-10-01T10:00:00+00:00',
              available_at='2026-10-01T10:01:00+00:00',predict_at='2026-10-01T10:02:00+00:00',
              unit='hour',value=2)
    validate_case(case)
    db=Receipts(out/'destino.sqlite');r1=db.commit('intent-1',{'units':1});db.close()
    # Reabertura de conexão após commit; não injeta morte de processo.
    db=Receipts(out/'destino.sqlite');r2=db.commit('intent-1',{'units':1})
    same=db.lookup('intent-1')==r1==r2
    count=db.db.execute('SELECT COUNT(*) FROM effects').fetchone()[0];db.close()
    events=[{'id':f't-{n}','state':'good' if n<80 else 'bad'} for n in range(90)]
    events+=events[:5]
    evidence=dict(identity_ok=True,population_ok=True,semantic_review=None,
                  recovery_ok=True,valid_until='2026-11-01T00:00:00+00:00')
    results=dict(wilson_3_200=wilson(3,200),zero_failure_n=zero_failure_n(.01),
      bootstrap=grouped_bootstrap({'f1':[0,1],'f2':[-1,0],'f3':[1,1],'f4':[0,0]}),
      bounds=outcome_bounds(80,10,10),case=case,
      receipts=dict(same=same,count=count,receipt=r1),
      telemetry=reconcile([f't-{n}' for n in range(100)],events),
      burn=burn(4,200,.99),decision=assess(evidence,'2026-10-25T00:00:00+00:00'),
      cost=unit_cost(20,60,10,30))
    files={'resultados.json':results,'evidencia.json':evidence,'eventos.json':events,
           'environment.json':dict(python=platform.python_version(),platform=platform.platform(),
             wall_seconds=time.perf_counter()-start,profile='stdlib; local SQLite; synthetic data',
             real_inference=False,human_collection=False)}
    for name,obj in files.items():
        (out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    root=Path(__file__).resolve().parents[2]
    sources={p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
    (out/'inputs.json').write_text(json.dumps(sources,indent=2)+'\n',encoding='utf-8')
    manifest={p.name:sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir()) if p.is_file()}
    (out/'manifesto.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return results

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    print(json.dumps(run(p.parse_args().out),ensure_ascii=False,indent=2))
