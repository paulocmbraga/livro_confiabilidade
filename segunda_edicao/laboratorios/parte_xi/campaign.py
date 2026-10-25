"""Campanha exclusiva; captura bruta, hashes e tempo de parede."""
from pathlib import Path
import argparse,asyncio,platform,time,sys
from importlib.metadata import version
from laboratorios.parte_ix.runtime import server
from .core import *
from .cases import run41,run42,run44
from .operations import run43
ROOT=Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--runtime',type=Path,default=Path('.modelos/l11'));a=p.parse_args()
    a.out=a.out.resolve();a.runtime=a.runtime.resolve();a.out.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter();epoch=time.time();lock=load(ROOT/'materiais/l11/modelos.lock.json')
    inputs=[*sorted((ROOT/'laboratorios/parte_xi').glob('*.py')),*sorted((ROOT/'laboratorios/parte_iv').glob('*.py')),
        ROOT/'laboratorios/parte_i/common.py',ROOT/'laboratorios/parte_ix/runtime.py',ROOT/'laboratorios/parte_ix/core.py',
        ROOT/'laboratorios/parte_vii/protocol_server.py',ROOT/'laboratorios/parte_vii/protocol_campaign.py',ROOT/'laboratorios/parte_vii/core.py',
        ROOT/'laboratorios/parte_x/service.py',ROOT/'laboratorios/parte_x/core.py',ROOT/'requirements-parte-xi.lock.txt',ROOT/'materiais/l11/modelos.lock.json']
    save(a.out/'inputs.json',{str(f.relative_to(ROOT)):sha(f) for f in inputs})
    save(a.out/'plan.json',dict(synthetic=True,l41=dict(train=600,calibration=160,reserve=200,shift_train=300,shift_calibration=100,shift_reserve=100,fn_cost=8,fp_cost=1,brier_gate=.23),l42=dict(families=4,phases=6,update_delay_seconds=.05),l43=dict(demands=6,modes=3,faults=1),l44=dict(epochs=5,tasks_per_case_per_epoch=3,clock='accelerated logical epochs; measured wall seconds separately'),human='pending',independent_reader='pending'))
    try:
        models=run41(a.out/'l41')
        with server(a.runtime,'qwen',lock,a.out/'runtime_qwen') as url:
            run42(a.out/'l42',url,'qwen');asyncio.run(run43(a.out/'l43',url,'qwen'))
            run44(a.out/'l44',url,'qwen',models,[0,1,2])
        with server(a.runtime,'smol',lock,a.out/'runtime_smol') as url:
            run44(a.out/'l44',url,'smol',models,[3,4])
        save(a.out/'environment.json',dict(python=platform.python_version(),platform=platform.platform(),dependencies={n:version(n) for n in ['mcp','a2a-sdk','psutil','uvicorn','httpx','httpx2']},started_epoch=epoch,seconds=time.perf_counter()-started,loopback_only=True,paid_api_calls=0,human_participants=0))
        seal(a.out,'parte-xi',True)
    except BaseException as e:
        save(a.out/'failure.json',dict(type=type(e).__name__,message=str(e),seconds=time.perf_counter()-started));seal(a.out,'parte-xi',False);raise
    print(str(a.out))
if __name__=='__main__':main()
