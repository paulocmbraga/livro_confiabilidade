"""L03: executor serial com registro transacional, orçamento e adaptador CLI.

Uma única instância por campanha; timeout encerra o processo local, sem
prometer cancelamento em provedor remoto. Retomada não reenvia desconhecidos.
"""
import argparse
from contextlib import contextmanager
import csv
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

PROJECT=Path(__file__).resolve().parents[1]


def canonical(obj):return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def hash_value(obj):return hashlib.sha256(canonical(obj).encode()).hexdigest()


@contextmanager
def db_at(path):
    db=sqlite3.connect(path,timeout=10,isolation_level=None);db.row_factory=sqlite3.Row
    db.execute('PRAGMA synchronous=FULL')
    try:yield db
    finally:db.close()


@contextmanager
def exclusive(folder):
    stream=(Path(folder)/'executor.lock').open('a+b')
    if stream.tell()==0:stream.write(b'0');stream.flush()
    stream.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        stream.close();raise RuntimeError('Já existe um executor nesta campanha')
    try:yield
    finally:
        stream.seek(0)
        if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
        else:fcntl.flock(stream,fcntl.LOCK_UN)
        stream.close()


def tasks():
    # Referências são usadas só pelo avaliador; não entram no adaptador.
    return [dict(task_id=f'T{i:02}',pergunta=f'Pergunta didática {i}',
                 referencia=f'Resposta preparada: T{i:02}') for i in range(1,7)]


def public_input(task):return {k:task[k] for k in ('task_id','pergunta')}


def initialize(folder,limit=12,adapter=None,model=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    if type(limit) is not int or limit<3:raise ValueError('Orçamento inteiro mínimo: 3')
    if adapter is not None and (not isinstance(adapter,list) or not adapter
                                or not all(isinstance(v,str) for v in adapter)):
        raise ValueError('Adaptador deve ser uma lista de argumentos sem shell')
    if adapter is not None and not model:raise ValueError('Declare modelo, revisão e parâmetros em --modelo-json')
    config=dict(version='L03-1.0',adapter='fixture' if adapter is None else 'comando_externo',
                command=adapter,limit=limit,reserve_per_call=3,timeout_s=3,
                admitted=[t['task_id'] for t in tasks()],public_fields=['task_id','pergunta'],
                model='nenhum' if adapter is None else model,
                unit='unidades didáticas' if adapter is None else 'unidades definidas pelo adaptador',
                source={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in (Path(__file__),PROJECT/'laboratorios/worker03.py')})
    with db_at(folder/'campaign.sqlite') as db:
        db.executescript('''
        CREATE TABLE meta(config TEXT,hash TEXT,halt INTEGER DEFAULT 0);
        CREATE TABLE attempts(task_id TEXT PRIMARY KEY,attempt_id TEXT UNIQUE,
          state TEXT,reserved INTEGER,used INTEGER,result TEXT);
        CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,event TEXT,detail TEXT);
        ''')
        db.execute('INSERT INTO meta(config,hash) VALUES(?,?)',(canonical(config),hash_value(config)))
        for t in tasks():
            db.execute('INSERT INTO attempts VALUES(?,?,?,0,NULL,NULL)',(t['task_id'],t['task_id']+':1','pending'))
    (folder/'run_manifest.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf8')


def event(db,task,name,detail=''):
    db.execute('INSERT INTO events(task_id,event,detail) VALUES(?,?,?)',(task,name,detail))


def load_config(folder,db):
    row=db.execute('SELECT * FROM meta').fetchone();cfg=json.loads(row['config'])
    external=json.loads((folder/'run_manifest.json').read_text(encoding='utf8'))
    if hash_value(cfg)!=row['hash'] or external!=cfg:raise ValueError('Configuração divergente')
    for name,h in cfg['source'].items():
        if hashlib.sha256((PROJECT/'laboratorios'/name).read_bytes()).hexdigest()!=h:
            raise ValueError('Código alterado desde a admissão')
    return cfg


def exposure(db):
    return db.execute('SELECT coalesce(sum(coalesce(used,reserved)),0) FROM attempts').fetchone()[0]


def valid_output(response,task,cap):
    return (isinstance(response,dict) and response.get('task_id')==task['task_id']
            and isinstance(response.get('texto'),str) and type(response.get('uso')) is int
            and 0<=response['uso']<=cap
            and response.get('estado') in ('respondida','rejeitada_antes_inferencia')
            and (response['estado']!='rejeitada_antes_inferencia' or response['uso']==0))


def run(folder,crash_after=None):
    folder=Path(folder).resolve()
    with exclusive(folder),db_at(folder/'campaign.sqlite') as db:
        cfg=load_config(folder,db)
        db.execute('BEGIN IMMEDIATE')
        for r in db.execute("SELECT task_id FROM attempts WHERE state='running'").fetchall():
            db.execute("UPDATE attempts SET state='unknown' WHERE task_id=?",(r['task_id'],))
            event(db,r['task_id'],'reconciled_unknown','Não reenviar automaticamente')
        db.commit()
        for task in tasks():
            tid=task['task_id'];db.execute('BEGIN IMMEDIATE')
            state=db.execute('SELECT state FROM attempts WHERE task_id=?',(tid,)).fetchone()[0]
            if state!='pending':db.rollback();continue
            halted=db.execute('SELECT halt FROM meta').fetchone()[0]
            if halted or exposure(db)+cfg['reserve_per_call']>cfg['limit']:
                reason='not_started_contract' if halted else 'not_started_budget'
                db.execute('UPDATE attempts SET state=? WHERE task_id=?',(reason,tid))
                event(db,tid,reason);db.commit();continue
            db.execute("UPDATE attempts SET state='running',reserved=? WHERE task_id=?",(cfg['reserve_per_call'],tid))
            event(db,tid,'dispatch',canonical(public_input(task)));db.commit()
            command=cfg['command'] or [sys.executable,'-m','laboratorios.worker03']
            start=time.perf_counter();result=None;used=None;new_state='unknown';detail=''
            try:
                proc=subprocess.run(command,input=canonical(public_input(task)),capture_output=True,text=True,
                    encoding='utf8',timeout=cfg['timeout_s'],cwd=PROJECT,shell=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                if proc.returncode:detail='adapter_exit_nonzero'
                else:
                    parsed=json.loads(proc.stdout)
                    if valid_output(parsed,task,cfg['reserve_per_call']):
                        result=parsed;used=parsed['uso']
                        new_state='completed' if parsed['estado']=='respondida' else 'failed'
                        detail='response_validated'
                    else:
                        detail='output_contract_violation'
                        if isinstance(parsed,dict) and type(parsed.get('uso')) is int and parsed['uso']>cfg['reserve_per_call']:
                            used=parsed['uso'];detail='usage_exceeded_reservation'
            except subprocess.TimeoutExpired:detail='local_timeout'
            except (ValueError,OSError):detail='invalid_or_missing_response'
            if tid==crash_after and result is not None:os._exit(83)
            # Resultado, contabilização e evento persistem na mesma transação.
            db.execute('BEGIN IMMEDIATE')
            if detail=='usage_exceeded_reservation':db.execute('UPDATE meta SET halt=1')
            db.execute('UPDATE attempts SET state=?,used=?,result=? WHERE task_id=?',
                       (new_state,used,canonical(result) if result else None,tid))
            event(db,tid,new_state,canonical(dict(reason=detail,elapsed_ms=round((time.perf_counter()-start)*1000,3))))
            db.commit()
    return export(folder)


def export(folder):
    folder=Path(folder)
    with db_at(folder/'campaign.sqlite') as db:
        cfg=load_config(folder,db)
        rows=[dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY task_id')]
        events=[dict(r) for r in db.execute('SELECT * FROM events ORDER BY seq')]
    if [r['task_id'] for r in rows]!=cfg['admitted']:raise ValueError('Denominador alterado')
    out=[]
    for r in rows:
        response=json.loads(r['result']) if r['result'] else None
        reference=next(t['referencia'] for t in tasks() if t['task_id']==r['task_id'])
        # Igualdade literal é apenas o juiz das fixtures; não é rubrica semântica.
        out.append(dict(r,adequado_fixture=r['state']=='completed' and response['texto']==reference))
    for name,data in [('outcomes.jsonl',out),('events.jsonl',events)]:
        (folder/name).write_text(''.join(canonical(r)+'\n' for r in data),encoding='utf8')
    with (folder/'ledger.csv').open('w',encoding='utf8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['task_id','attempt_id','state','reserved','used'])
        writer.writeheader();writer.writerows({k:r[k] for k in writer.fieldnames} for r in rows)
    summary=dict(admitted=len(rows),accounted=len(out),completed=sum(r['state']=='completed' for r in rows),
                 unknown=sum(r['state']=='unknown' for r in rows),
                 not_started=sum(r['state'].startswith('not_started_') for r in rows),
                 failed=sum(r['state']=='failed' for r in rows),
                 known_usage=sum(r['used'] or 0 for r in rows),
                 uncertain_reserved=sum(r['reserved'] for r in rows if r['used'] is None),
                 dispatches=len([e for e in events if e['event']=='dispatch']),
                 conclusion='Campanha contabilizada; estados desconhecidos não resolvidos')
    (folder/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    return summary


def main():
    p=argparse.ArgumentParser();p.add_argument('--saida',type=Path,required=True)
    p.add_argument('--iniciar',action='store_true');p.add_argument('--limite',type=int,default=12)
    p.add_argument('--crash-after');p.add_argument('--replay',action='store_true')
    p.add_argument('--comando-json',type=Path)
    p.add_argument('--modelo-json',type=Path)
    args=p.parse_args()
    if args.iniciar:
        command=json.loads(args.comando_json.read_text(encoding='utf8')) if args.comando_json else None
        model=json.loads(args.modelo_json.read_text(encoding='utf8')) if args.modelo_json else None
        if command and (not isinstance(model,dict) or not {'id','revision','parameters'}<=model.keys()):
            raise ValueError('Modelo exige id, revision e parameters')
        initialize(args.saida,args.limite,command,model)
    elif args.comando_json:raise ValueError('Não alterar adaptador em campanha admitida')
    print(json.dumps(export(args.saida) if args.replay else run(args.saida,args.crash_after),ensure_ascii=False))


if __name__=='__main__':main()
