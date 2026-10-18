"""L13, L14 e L16 novos; L15 vinculado à captura preservada do piloto."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sqlite3
import time
from . import guardrails13, autoridade14, coordenacao16, piloto15
from .dados_ii import write,sha,readlines

PROJECT=Path(__file__).resolve().parents[1]
SOURCES=('dados_ii.py','guardrails13.py','autoridade14.py','coordenacao16.py','parte_iv.py',
         'efeitos15.py','piloto15.py')

def capture(folder):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=False);start=time.perf_counter()
    try:
        result={k:m.capture(folder/k) for k,m in (('L13',guardrails13),('L14',autoridade14),('L16',coordenacao16))}
        result['L15']=piloto15.verify(PROJECT/'output/piloto15_v02')
        write(folder/'pilot_reference.json',dict(path='output/piloto15_v02',**result['L15']))
        write(folder/'summary.json',result)
        write(folder/'manifesto.json',dict(version='parte-IV-1.0',utc=datetime.now(timezone.utc).isoformat(),
            python=platform.python_version(),duration_seconds=round(time.perf_counter()-start,3),
            model_calls=0,human_participants=0,track='D e O local; L16 usa tempo lógico',
            sources={n:sha(PROJECT/'laboratorios'/n) for n in SOURCES},
            artifacts={p.relative_to(folder).as_posix():sha(p) for p in folder.rglob('*') if p.is_file()}))
    except Exception as exc:
        write(folder/'incomplete.json',dict(error=repr(exc)));raise
    return verify(folder)

def unique(rows,keys,expected):
    ids=[tuple(r[k] for k in keys) for r in rows]
    if len(ids)!=len(set(ids)) or set(ids)!=set(expected):raise ValueError('Identidades incompletas ou duplicadas')

def verify(folder):
    folder=Path(folder);m=json.loads((folder/'manifesto.json').read_text(encoding='utf8'))
    for n,h in m['sources'].items():
        if sha(PROJECT/'laboratorios'/n)!=h:raise ValueError('Código divergente: '+n)
    for n,h in m['artifacts'].items():
        if sha(folder/n)!=h:raise ValueError('Artefato divergente: '+n)
    rows=readlines(folder/'L13/control_trials.jsonl')
    unique(rows,('case_id','profile'),[(c['case_id'],p) for c in guardrails13.cases() for p in guardrails13.PROFILES])
    for r in rows:
        db=sqlite3.connect((folder/'L13'/r['database']).resolve().as_uri()+'?mode=ro',uri=True)
        try:
            effects=[dict(action=a,resource=b) for a,b in db.execute('SELECT * FROM effects')]
            states=dict(db.execute('SELECT * FROM tickets'))
        finally:db.close()
        if effects!=r['effects'] or states!=r['states']:raise ValueError('L13: destino diverge')
        c=next(c for c in guardrails13.cases() if c['case_id']==r['case_id'])
        if r['violation']!=any(not c['benign'] or e!=c['proposal'] for e in effects):raise ValueError('L13: oráculo')
    result={'L13':guardrails13.summarize(rows)}
    rows=readlines(folder/'L14/permission_trials.jsonl')
    unique(rows,('case_id','transport'),[(c['case_id'],t) for c in autoridade14.cases() for t in autoridade14.TRANSPORTS])
    for r in rows:
        place=folder/'L14'/(r['case_id']+'_'+r['transport'])
        state=autoridade14.snapshot(place/'destination.sqlite')
        if state!=json.loads((place/'snapshot.json').read_text(encoding='utf8')):raise ValueError('L14: destino diverge')
        if len(state['receipts'])!=r['effects'] or r['effects']!=r['expected_effects']:raise ValueError('L14: efeitos')
        if r['pid']==r['client_pid']:raise ValueError('L14: processos não separados')
    result['L14']=autoridade14.summarize(rows)
    rows=readlines(folder/'L16/delegation_traces.jsonl')
    expected=[coordenacao16.run(c,v) for c in coordenacao16.cases() for v in coordenacao16.VARIANTS]
    if rows!=expected:raise ValueError('L16: reprodução diverge')
    result['L16']=coordenacao16.summarize(rows)
    result['L15']=piloto15.verify(PROJECT/'output/piloto15_v02')
    if result!=json.loads((folder/'summary.json').read_text(encoding='utf8')):raise ValueError('Agregação divergente')
    return dict(artifacts=len(m['artifacts']),labs=['L13','L14','L15','L16'],
        model_calls=0,human_participants=0,manifest_sha256=sha(folder/'manifesto.json'),
        pilot_manifest_sha256=result['L15']['manifest_sha256'],replay='Bancos somente em leitura e simulação local; sem novos envios HTTP')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--saida',type=Path,required=True);p.add_argument('--conferir',action='store_true')
    a=p.parse_args();print(json.dumps(verify(a.saida) if a.conferir else capture(a.saida),ensure_ascii=False))
