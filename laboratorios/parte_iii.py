"""Executa L09-L12 e reconstrói a análise de uma captura identificada por hashes."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys
import time
from . import oraculos09, anotacao10, juizes11, experimentos12
from .dados_ii import write, sha, readlines

PROJECT=Path(__file__).resolve().parents[1]
SOURCES=('dados_ii.py','recuperacao06.py','oraculos09.py','anotacao10.py','juizes11.py','experimentos12.py','parte_iii.py')


def unique(rows,keys,expected):
    actual=[tuple(row[k] for k in keys) for row in rows]
    if len(actual)!=len(set(actual)) or set(actual)!=set(expected):
        raise ValueError('Identidades incompletas ou duplicadas: '+str(keys))


def capture(folder):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=False);start=time.perf_counter()
    summaries={}
    for name,module in (('L09',oraculos09),('L10',anotacao10),('L11',juizes11),('L12',experimentos12)):
        summaries[name]=module.capture(folder/name)
    write(folder/'summary.json',summaries)
    write(folder/'manifesto.json',dict(version='parte-III-1.0',utc=datetime.now(timezone.utc).isoformat(),
        python=platform.python_version(),isolated=sys.prefix!=sys.base_prefix,
        duration_seconds=round(time.perf_counter()-start,3),track='D',model_calls=0,human_participants=0,
        sources={name:sha(PROJECT/'laboratorios'/name) for name in SOURCES},
        artifacts={p.relative_to(folder).as_posix():sha(p) for p in folder.rglob('*') if p.is_file()},
        limits='Casos autorais, juízes por regras e simulações declaradas; não mede LLMs ou pessoas.'))
    return verify(folder)


def verify(folder):
    folder=Path(folder);manifest=json.loads((folder/'manifesto.json').read_text(encoding='utf8'))
    for name,h in manifest['sources'].items():
        if sha(PROJECT/'laboratorios'/name)!=h:raise ValueError('Código mudou: '+name)
    for name,h in manifest['artifacts'].items():
        if sha(folder/name)!=h:raise ValueError('Artefato mudou: '+name)
    summary=json.loads((folder/'summary.json').read_text(encoding='utf8'));reconstructed={}
    cases=readlines(folder/'L09/mutations.jsonl');rows=readlines(folder/'L09/evaluator_trials.jsonl')
    if rows!=oraculos09.trials(cases):raise ValueError('L09: resultados divergentes')
    unique(cases,('case_id',),[(c['case_id'],) for c in oraculos09.cases()])
    reconstructed['L09']=oraculos09.summarize(rows)
    rows=readlines(folder/'L10/annotations.jsonl')
    unique(rows,('annotation_id',),[(r['annotation_id'],) for r in anotacao10.annotations()])
    ids={r['annotation_id'] for r in rows}
    for decision in readlines(folder/'L10/adjudication_log.jsonl'):
        if not set(decision['annotation_ids'])<=ids:raise ValueError('L10: origem de adjudicação ausente')
    reconstructed['L10']=anotacao10.summarize(rows)
    rows=readlines(folder/'L11/judge_trials.jsonl')
    expected=[(c['case_id'],j,p,r) for c in juizes11.cases() for j in juizes11.JUDGES
              for p in juizes11.PERTURBATIONS for r in (False,True)]
    unique(rows,('case_id','judge','perturbation','reverse'),expected)
    for row in rows:
        if juizes11.parse(row['raw'],row['request'])!=row['parsed']:raise ValueError('L11: parsing divergente')
        if 'reference' in row['request']:raise ValueError('L11: vazamento de referência')
    reconstructed['L11']=juizes11.summarize(rows)
    rows=readlines(folder/'L12/factorial_runs.jsonl')
    unique(rows,('run_id',),[(p['run_id'],) for p in experimentos12.plan()])
    plan={p['run_id']:p for p in experimentos12.plan()}
    for row in rows:
        if any(row[k]!=v for k,v in plan[row['run_id']].items()):raise ValueError('L12: alocação alterada')
    nr=readlines(folder/'L12/naive_runs.jsonl');online=readlines(folder/'L12/online_simulation.jsonl')
    seq=readlines(folder/'L12/sequential_simulation.jsonl')
    unique(seq,('trial',),[(n,) for n in range(1000)])
    reconstructed['L12']=experimentos12.summarize(rows,nr,online,seq)
    if reconstructed!=summary:raise ValueError('Agregação diverge do relatório')
    return dict(artifacts=len(manifest['artifacts']),labs=list(reconstructed),model_calls=0,human_participants=0,
                manifest_sha256=sha(folder/'manifesto.json'),replay='análise local dos registros')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--saida',type=Path,required=True)
    parser.add_argument('--conferir',action='store_true');args=parser.parse_args()
    print(json.dumps(verify(args.saida) if args.conferir else capture(args.saida),ensure_ascii=False))
