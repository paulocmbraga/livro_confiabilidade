"""Executa L05–L08 e confere capturas sem reenviar operações."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys
import time
from . import respostas05, recuperacao06, memoria07, agentes08, destino08
from .dados_ii import write, sha, readlines

PROJECT=Path(__file__).resolve().parents[1]
SOURCES=('dados_ii.py','respostas05.py','recuperacao06.py','memoria07.py','destino08.py','agentes08.py','parte_ii.py')


def capture(folder):
    folder=Path(folder).resolve(); folder.mkdir(parents=True,exist_ok=False);start=time.perf_counter()
    summaries={}
    for name,module in (('L05',respostas05),('L06',recuperacao06),('L07',memoria07),('L08',agentes08)):
        summaries[name]=module.capture(folder/name)
    write(folder/'summary.json',summaries)
    write(folder/'manifesto.json',dict(version='parte-II-1.0',utc=datetime.now(timezone.utc).isoformat(),
        python=platform.python_version(),isolated=sys.prefix!=sys.base_prefix,
        duration_seconds=round(time.perf_counter()-start,3),track='D',model_calls=0,
        sources={name:sha(PROJECT/'laboratorios'/name) for name in SOURCES},
        artifacts={p.relative_to(folder).as_posix():sha(p) for p in folder.rglob('*') if p.is_file()},
        limits='Fixtures públicas; não é campanha de modelos, estudo humano ou benchmark de produção.'))
    return verify(folder)


def verify(folder):
    folder=Path(folder);manifest=json.loads((folder/'manifesto.json').read_text(encoding='utf8'))
    for name,h in manifest['sources'].items():
        if sha(PROJECT/'laboratorios'/name)!=h:raise ValueError('Código mudou: '+name)
    for name,h in manifest['artifacts'].items():
        if sha(folder/name)!=h:raise ValueError('Artefato mudou: '+name)
    summary=json.loads((folder/'summary.json').read_text(encoding='utf8'))
    rows=readlines(folder/'L05/outcomes.jsonl')
    reconstructed=[dict(threshold=t,**respostas05.aggregate([r for r in rows if r['threshold']==t])) for t in (0,.6,.8,1)]
    if reconstructed!=summary['L05']:raise ValueError('Resumo L05 divergente')
    rows=readlines(folder/'L06/retrieval_runs.jsonl')
    if recuperacao06.summarize(rows)!=summary['L06']:raise ValueError('Resumo L06 divergente')
    rows=readlines(folder/'L07/outcomes.jsonl')
    if memoria07.summarize(rows)!=summary['L07']:raise ValueError('Resumo L07 divergente')
    rows=readlines(folder/'L08/trajectories.jsonl')
    if agentes08.summarize(rows)!=summary['L08']:raise ValueError('Resumo L08 divergente')
    expected={(s,v,a) for s in agentes08.SCENARIOS for v in ('workflow','agente_d') for a in (1,2,3)}
    keys=[(r['scenario'],r['variant'],r['attempt']) for r in rows]
    if len(keys)!=len(set(keys)) or set(keys)!=expected:raise ValueError('Tentativas incompletas/duplicadas')
    snapshots=json.loads((folder/'L08/destination_snapshots.json').read_text(encoding='utf8'))
    for r in rows:
        key=f"{r['scenario']}_{r['variant']}_{r['attempt']}"
        # Consulta de leitura em SQLite; não inicia serviço nem altera os destinos.
        import sqlite3
        path=(folder/'L08/destinos'/(key+'.sqlite')).resolve()
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            for name in ('reservations','tickets','stock','events'):
                actual=[dict(x) for x in db.execute('SELECT * FROM '+name)]
                if actual!=snapshots[key][name]:raise ValueError('Snapshot diverge do destino: '+key)
        verdict=agentes08.oracle(snapshots[key],r['narrative'],r['scenario'],r['history'])
        if any(r[k]!=v for k,v in verdict.items()):raise ValueError('Oráculo divergente')
    return dict(artifacts=len(manifest['artifacts']),labs=['L05','L06','L07','L08'],
                model_calls=0,manifest_sha256=sha(folder/'manifesto.json'),replay='somente leitura')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--saida',type=Path,required=True)
    parser.add_argument('--conferir',action='store_true');args=parser.parse_args()
    print(json.dumps(verify(args.saida) if args.conferir else capture(args.saida),ensure_ascii=False))
