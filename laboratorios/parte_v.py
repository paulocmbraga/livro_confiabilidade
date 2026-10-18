"""Captura íntegra de L17 a L20, sem sobrescrever campanhas anteriores."""
import argparse
import csv
from datetime import datetime,timezone
import json
from pathlib import Path
import platform
import time
from . import observacao17,monitoramento18,capacidade19,economia20
from .dados_ii import write,sha,readlines

PROJECT=Path(__file__).resolve().parents[1]
SOURCES=('dados_ii.py','observacao17.py','monitoramento18.py','capacidade19.py','economia20.py','parte_v.py')


def capture(folder):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=False)
    start=time.perf_counter()
    try:
        result={name:module.capture(folder/name) for name,module in
                (('L17',observacao17),('L18',monitoramento18),('L19',capacidade19),('L20',economia20))}
        write(folder/'summary.json',result)
        write(folder/'manifesto.json',dict(version='parte-V-1.0',utc=datetime.now(timezone.utc).isoformat(),
            python=platform.python_version(),platform=platform.platform(),
            duration_seconds=time.perf_counter()-start,model_calls=0,human_participants=0,
            sources={n:sha(PROJECT/'laboratorios'/n) for n in SOURCES},
            artifacts={p.relative_to(folder).as_posix():sha(p) for p in folder.rglob('*') if p.is_file()}))
    except Exception as exc:
        write(folder/'incomplete.json',dict(error=repr(exc)));raise
    return verify(folder)


def verify(folder):
    folder=Path(folder);manifest=json.loads((folder/'manifesto.json').read_text(encoding='utf8'))
    for name,digest in manifest['sources'].items():
        if sha(PROJECT/'laboratorios'/name)!=digest:raise ValueError('Código divergente: '+name)
    for name,digest in manifest['artifacts'].items():
        if sha(folder/name)!=digest:raise ValueError('Artefato divergente: '+name)
    saved=json.loads((folder/'summary.json').read_text(encoding='utf8'))
    for profile in observacao17.PROFILES:
        ledger=readlines(folder/f'L17/{profile}_ledger.jsonl')
        events=readlines(folder/f'L17/{profile}_collector.jsonl')
        if {r['task'] for r in ledger}!={r['task'] for r in observacao17.cases()} or len(ledger)!=12:
            raise ValueError('L17: população incompleta')
        result=observacao17.audit(ledger,events);result.pop('rows')
        result['secret_exposed']=observacao17.SECRET in json.dumps(events)
        if result!=saved['L17'][profile]:raise ValueError('L17: agregação divergente')
    rows=readlines(folder/'L18/fixture_truth.jsonl');selected=monitoramento18.select_audit(rows)
    if rows!=monitoramento18.stream():raise ValueError('L18: fluxo divergente')
    if monitoramento18.summarize(rows,selected)!=saved['L18']['cohorts']:raise ValueError('L18: agregação')
    if monitoramento18.monitor(rows,selected)!=readlines(folder/'L18/alert_decisions.jsonl'):raise ValueError('L18: alertas')
    for summary in saved['L19']:
        prefix=f"{summary['policy']}_{summary['repetition']}"
        rows=readlines(folder/f'L19/{prefix}_tasks.jsonl');calls=readlines(folder/f'L19/{prefix}_calls.jsonl')
        if len(rows)!=33 or {r['task'] for r in rows}!={r['task'] for r in capacidade19.profile()}:
            raise ValueError('L19: população')
        actual=capacidade19.summarize(rows,calls)
        if any(summary[k]!=v for k,v in actual.items()):raise ValueError('L19: agregação')
        if sum(r['attempts'] for r in rows)!=len(calls):raise ValueError('L19: tentativas')
        if any(r['useful'] and r['finished']>r['deadline'] for r in rows):raise ValueError('L19: prazo')
        if summary['remaining']!=0:raise ValueError('L19: trabalho remanescente')
    for policy in economia20.POLICIES:
        rows,ledger=economia20.run(policy)
        if economia20.aggregate(rows,ledger)!=saved['L20']['policies'][policy]:raise ValueError('L20: agregação')
    return dict(artifacts=len(manifest['artifacts']),labs=['L17','L18','L19','L20'],
                manifest_sha256=sha(folder/'manifesto.json'),model_calls=0,human_participants=0,
                replay='Reconciliação dos registros; sem repetir HTTP ou ensaio de carga')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--saida',type=Path,required=True)
    p.add_argument('--conferir',action='store_true');a=p.parse_args()
    print(json.dumps(verify(a.saida) if a.conferir else capture(a.saida),ensure_ascii=False))
