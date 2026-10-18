"""Captura e reconciliação da Parte VI. Mantém campanhas anteriores intactas."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import platform
import sqlite3
import time
from . import liberacao21,incidente22,assistente23,operacoes24,piloto15
from .dados_ii import sha,write,readlines
from .evidencia_vi import verify_index

PROJECT=Path(__file__).resolve().parents[1]
SOURCES=('dados_ii.py','recuperacao06.py','efeitos15.py','piloto15.py','coordenacao16.py',
    'evidencia_vi.py','liberacao21.py','incidente22.py','assistente23.py','operacoes24.py','parte_vi.py')
PRIOR=('parte_ii_v03','piloto15_v02','parte_iv_v02','parte_v_v01')


def read(path):return json.loads(Path(path).read_text(encoding='utf8'))


def capture(folder):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=False)
    start=time.perf_counter()
    try:
        result={name:module.capture(folder/name) for name,module in
            (('L21',liberacao21),('L22',incidente22),('L23',assistente23),('L24',operacoes24))}
        write(folder/'summary.json',result)
        write(folder/'prior_evidence.json',dict(references={f'output/{p}/manifesto.json':sha(PROJECT/f'output/{p}/manifesto.json') for p in PRIOR},
            role='Dependências históricas identificadas; L24 executa nova campanha operacional em bancos próprios. Populações não foram somadas.'))
        write(folder/'manifesto.json',dict(version='parte-VI-1.0',utc=datetime.now(timezone.utc).isoformat(),
            python=platform.python_version(),platform=platform.platform(),duration_seconds=time.perf_counter()-start,
            model_calls=0,human_participants=0,provider_spend=0,
            sources={n:sha(PROJECT/'laboratorios'/n) for n in SOURCES},
            artifacts={p.relative_to(folder).as_posix():sha(p) for p in folder.rglob('*') if p.is_file()}))
    except Exception as exc:
        write(folder/'incomplete.json',dict(error=repr(exc)));raise
    return verify(folder)


def verify(folder):
    folder=Path(folder);m=read(folder/'manifesto.json');summary=read(folder/'summary.json')
    for name,h in m['sources'].items():
        if sha(PROJECT/'laboratorios'/name)!=h:raise ValueError('Código divergente: '+name)
    actual={p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and p.name!='manifesto.json'}
    if actual!=set(m['artifacts']):raise ValueError('Inventário de artefatos divergente')
    for name,h in m['artifacts'].items():
        if sha(folder/name)!=h:raise ValueError('Artefato divergente: '+name)
    for name,h in read(folder/'prior_evidence.json')['references'].items():
        if sha(PROJECT/name)!=h:raise ValueError('Referência anterior alterada')
    f=folder/'L21';packages=read(f/'packages.json');gates=read(f/'gate_results.json')
    if {k:liberacao21.gate(v) for k,v in packages.items()}!=gates:raise ValueError('Gates divergentes')
    for suffix,key in (('safe','safe'),('unsafe','unsafe')):
        db=sqlite3.connect((f/f'rollout_{suffix}.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
        try:count=db.execute('SELECT COUNT(*) FROM effects').fetchone()[0]
        finally:db.close()
        if count!=read(f/'rollout.json')[key]['effects']:raise ValueError('Efeitos de rollout')
    f=folder/'L22'
    for policy in ('availability','controlled'):
        expected=incidente22.run(policy)
        if expected['tasks']!=readlines(f/f'{policy}_tasks.jsonl'):raise ValueError('Tarefas de incidente')
        if expected['timeline']!=readlines(f/f'{policy}_timeline.jsonl'):raise ValueError('Cronologia')
        if expected['summary']!=summary['L22'][policy]:raise ValueError('Resumo de incidente')
    f=folder/'L23';ids=[q['query_id'] for q in readlines(f/'reserved_queries.jsonl')]
    verify_index(f,read(f/'evidence_index.json'),assistente23.CLAIMS)
    mapping={'reserved':'reserved_runs.jsonl','incident':'incident_runs.jsonl','repaired':'repaired_runs.jsonl'}
    for key,path in mapping.items():
        if assistente23.aggregate(readlines(f/path),ids)!=summary['L23'][key]:raise ValueError('Agregação A: '+key)
    dev=readlines(f/'development_runs.jsonl')
    if assistente23.select(dev)!=summary['L23']['selected']:raise ValueError('Seleção A')
    rows=readlines(f/'update_runs.jsonl')
    for cache in ('ingenuo','versionado'):
        if assistente23.aggregate([r for r in rows if r['cache']==cache],ids)!=summary['L23']['updates'][cache]:raise ValueError('Atualização A')
    f=folder/'L24';verify_index(f,read(f/'evidence_index.json'),operacoes24.CLAIMS)
    reports=read(f/'fault_reports.json')
    for report in reports:
        case=next(c for c in piloto15.CASES if c[0]==report['case'])
        data=read(f/case[0]/'evidence.json');current=piloto15.oracle(f/case[0]/'destination.sqlite')
        if current!=data['final_oracle'] or len(current['effects'])!=case[2]:raise ValueError('Oráculo B')
        db=sqlite3.connect((f/case[0]/'client.sqlite').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
        try:states=[dict(r) for r in db.execute('SELECT * FROM operations ORDER BY intent')]
        finally:db.close()
        if states!=data['final_client'] or sum(r['state']=='unknown' for r in states)!=report['unknown']:raise ValueError('Estado B')
    selected=operacoes24.choose(readlines(f/'architecture_runs.jsonl'))
    decision=operacoes24.decide(reports,read(f/'delegation/evidence.json'),read(f/'review_capacity.json')['capacity_1'],selected)
    if decision!=read(f/'decision_B.json'):raise ValueError('Decisão B')
    return dict(artifacts=len(m['artifacts']),labs=['L21','L22','L23','L24'],manifest_sha256=sha(folder/'manifesto.json'),
        model_calls=0,human_participants=0,replay='Leitura e reconciliação; sem repetir HTTP ou efeitos')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--saida',type=Path,required=True)
    p.add_argument('--conferir',action='store_true');a=p.parse_args()
    print(json.dumps(verify(a.saida) if a.conferir else capture(a.saida),ensure_ascii=False))
