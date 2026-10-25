"""Campanha exclusiva e selada da Parte X."""
from pathlib import Path
import argparse,platform,sqlite3,time
from .core import *
from . import monitor,operations
ROOT=Path(__file__).resolve().parents[2]


def run(out):
    out=out.resolve();out.mkdir(parents=True,exist_ok=False)
    sources=list((ROOT/'laboratorios/parte_x').glob('*.py'))+[ROOT/'laboratorios/parte_i/common.py',
        ROOT/'requirements-parte-x.lock.txt',ROOT/'testes/test_parte_x.py']
    save(out/'inputs.json',{p.relative_to(ROOT).as_posix():sha(p) for p in sources})
    save(out/'plan.json',dict(version=1,created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        l37=dict(seed=3701,cohorts=120,tasks_per_cohort=20,maturity=10,window=5,error_threshold=.15,
            consecutive=2,train_baseline=600,train_candidate_cohorts=[40,50],reserve_cohorts=[50,55],
            candidate_promotion=65,drift_z=20,concept_change=40,alias_change=[75,90]),
        l38=dict(paired=20,canary_every=4,critical_index=8,max_error=.1,critical_tolerance=0,
            negative_control='Canário intencional apesar de gate reprovado, somente efeitos sintéticos locais.'),
        l39=dict(queue_capacity=3,offered=8,crash='worker after commit before response',human='pending'),
        l40=dict(now_logical=20,cases=12,required_open_tasks=0),
        scope='Local CPU; modelo stump treinado; nenhum LLM, serviço pago, pessoa simulada ou efeito externo.'))
    save(out/'environment.json',dict(python=platform.python_version(),platform=platform.platform(),sqlite=sqlite3.sqlite_version,
        dependencies='standard library',clock='perf_counter elapsed; synthetic cohorts only in L37; synthetic validity clock in L40'))
    complete=False
    try:
        results={'l37':monitor.run(out/'l37')};models=load(out/'l37/models.json')
        results['l38']=operations.release(out/'l38',models)
        results['l39']=operations.incident(out/'l39',models['baseline'])
        results['l40']=operations.assurance(out/'l40')
        save(out/'results.json',results);complete=True
    finally:seal(out,'parte-x-local-experiments',complete)
    return results


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['run','verify']);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.action=='run':r=run(a.out)
    else:
        from .verify import verify
        r=verify(a.out)
    import json;print(json.dumps(r,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
