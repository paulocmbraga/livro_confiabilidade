"""Campanha local D/O: processos reais, injeções determinísticas e oráculo independente."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import time
from .efeitos15 import (approve, canonical, connect, http_json, initialize,
                        init_ledger, record, request_for)

PROJECT = Path(__file__).resolve().parents[1]
CASES = [
 ('S01','normal',1,8,['confirmed']),
 ('S02','drop_reply',1,8,['confirmed']),
 ('S03','baseline',2,6,['confirmed']),
 ('S04','before_commit',1,8,['confirmed']),
 ('S05','after_commit',1,8,['confirmed']),
 ('S06','before_send',1,8,['confirmed']),
 ('S07','after_receive',1,8,['confirmed']),
 ('S08','same_key',1,8,['confirmed']),
 ('S09','stale_version',1,8,['confirmed','rejected']),
 ('S10','payload_mismatch',1,8,['confirmed']),
 ('S11','expired_retention',1,8,['unknown']),
 ('S12','no_lookup',1,8,['unknown']),
 ('S13','unavailable_lookup',1,8,['unknown']),
 ('S14','compensate',2,10,['confirmed','confirmed']),
 ('S15','irreversible',1,8,['confirmed','rejected']),
 ('S16','revoked_approval',0,10,['rejected']),
 ('S17','insufficient_stock',0,10,['rejected']),
 ('S18','expired_approval',0,10,['rejected']),
]


def write_json(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Bench:
    def __init__(self, folder):
        self.folder=folder;self.target=folder/'destination.sqlite';self.client=folder/'client.sqlite'
        self.server=None;self.children=[];self.events=[];self.serial=0
        initialize(self.target)

    def spawn(self,args):
        proc=subprocess.Popen([sys.executable,'-m','laboratorios.efeitos15',*args],
            cwd=PROJECT,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.children.append(proc)
        return proc

    def start(self,fault='none',now=100,lookup='yes',legacy=False):
        self.stop();self.serial+=1
        ready=self.folder/f'ready_{self.serial}.txt'
        args=['serve','--db',str(self.target),'--ready',str(ready),'--fault',fault,
              '--now',str(now),'--lookup',lookup]
        if legacy:args.append('--legacy')
        self.server=self.spawn(args)
        limit=time.monotonic()+10
        while True:
            if self.server.poll() is not None or time.monotonic()>limit:
                raise RuntimeError('Destino não iniciou')
            try:
                port=int(ready.read_text(encoding='ascii'))
                if 0 < port < 65536:break
            except (FileNotFoundError,ValueError):
                pass
            time.sleep(.01)
        self.url='http://127.0.0.1:'+str(port)
        self.events.append(dict(event='server_started',pid=self.server.pid,
                                fault=fault,clock=now,lookup=lookup,legacy=legacy))

    def stop(self):
        if self.server:
            if self.server.poll() is None:self.server.terminate()
            self.server.wait(timeout=10)
            self.events.append(dict(event='server_stopped',pid=self.server.pid,exit=self.server.returncode))
            self.server=None

    def worker(self,req,recover=False,fault='none',barrier=None,wait=True):
        args=['work','--db',str(self.client),'--intent',req['intent'],
              '--url',self.url,'--fault',fault]
        if recover:args.append('--recover')
        if barrier:args.extend(['--barrier',str(barrier)])
        proc=self.spawn(args)
        if wait:self.finish(proc,fault)
        return proc

    def finish(self,proc,fault='none'):
        _,stderr=proc.communicate(timeout=15)
        expected={'after_receive':73,'before_send':74}.get(fault,0)
        if proc.returncode!=expected:
            raise RuntimeError(f'Worker {proc.returncode}: {stderr.decode(errors="replace")}')
        self.events.append(dict(event='worker_finished',pid=proc.pid,fault=fault,exit=proc.returncode))

    def concurrent(self,requests):
        barrier=self.folder/'barrier'
        procs=[self.worker(req,barrier=barrier,wait=False) for req in requests]
        limit=time.monotonic()+10
        while len(list(self.folder.glob('barrier.*.ready')))!=len(procs):
            if time.monotonic()>limit:raise TimeoutError('Barreira dos workers')
            time.sleep(.01)
        barrier.touch()
        for proc in procs:self.finish(proc)

    def states(self):
        with connect(self.client) as db:
            return [dict(r) for r in db.execute('SELECT * FROM operations ORDER BY intent')]

    def close(self):
        self.stop()
        for proc in self.children:
            if proc.poll() is None:proc.kill();proc.wait(timeout=10)
            if proc.stderr and not proc.stderr.closed:proc.stderr.close()


def oracle(path):
    # Leitura do verificador, nunca usada pelo cliente para decidir recuperação.
    db=sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    try:
        return {table:[dict(row) for row in db.execute('SELECT * FROM '+table)]
                for table in ('stock','reservations','effects','receipts')}
    finally:db.close()


def run_case(folder,case):
    ident,kind,n_effects,available,expected_states=case
    folder.mkdir()
    b=Bench(folder);req=request_for();recovery_ms=None;observations=[];blocked=0
    try:
        if kind=='insufficient_stock':req['quantity']=11
        approve(b.target,req,until=90 if kind=='expired_approval' else 200,
                revoked=kind=='revoked_approval')
        init_ledger(b.client,req)
        fault=kind if kind in ('drop_reply','before_commit','after_commit') else 'none'
        if kind in ('baseline','expired_retention','no_lookup','unavailable_lookup'):fault='drop_reply'
        b.start(fault=fault,legacy=kind=='baseline')
        if kind=='baseline':
            record(b.client,req['intent'],'unknown','before_network')
            try:http_json(b.url+'/',req)
            except (OSError, __import__('http.client').client.HTTPException):pass
            observations.append(dict(phase='lost_response',states=b.states()))
            code,reply=http_json(b.url+'/',req)
            assert code==200
            record(b.client,req['intent'],'confirmed','naive_retry',reply)
        elif kind in ('same_key','stale_version'):
            other=req
            if kind=='stale_version':
                other=request_for('pedido-2','chave-2')
                approve(b.target,other);init_ledger(b.client,other)
            b.concurrent([req,other])
        else:
            b.worker(req,fault=kind if kind in ('before_send','after_receive') else 'none')
            observations.append(dict(phase='after_first_attempt',states=b.states()))
            if kind in ('drop_reply','before_commit','after_commit','before_send','after_receive',
                         'expired_retention','no_lookup','unavailable_lookup'):
                assert b.states()[0]['state']=='unknown'
                b.stop()
                observations.append(dict(phase='before_recovery',oracle=oracle(b.target)))
                b.start(now=160 if kind=='expired_retention' else 100,
                        lookup={'no_lookup':'no','unavailable_lookup':'unavailable'}.get(kind,'yes'))
                start=time.perf_counter();b.worker(req,recover=True)
                recovery_ms=round((time.perf_counter()-start)*1000,3)
            if kind=='payload_mismatch':
                changed=dict(req,quantity=3)
                code,reply=http_json(b.url+'/',changed)
                assert code==409 and reply['error']=='key_payload_mismatch'
                observations.append(dict(phase='mismatched_payload',status=code,reply=reply));blocked=1
            if kind in ('compensate','irreversible'):
                rid=json.loads(b.states()[0]['receipt'])['reservation']
                b.stop()
                if kind=='irreversible':
                    # Expedição é uma fixture externa explicitamente registrada.
                    with connect(b.target) as db:
                        db.execute("UPDATE reservations SET state='shipped',version=1 WHERE id=?",(rid,))
                    observations.append(dict(phase='fixture_shipment',reservation=rid))
                comp=request_for('reparacao-1','chave-comp')
                comp.update(action='release',reservation=rid)
                approve(b.target,comp);init_ledger(b.client,comp)
                b.start(fault='drop_reply' if kind=='compensate' else 'none')
                b.worker(comp)
                if kind=='compensate':
                    assert b.states()[1]['state']=='unknown'
                    start=time.perf_counter();b.worker(comp,recover=True)
                    recovery_ms=round((time.perf_counter()-start)*1000,3)
        b.stop()
        final=oracle(b.target);states=b.states()
        assert len(final['effects'])==n_effects,(ident,final)
        assert final['stock'][0]['available']==available,(ident,final)
        assert sorted(r['state'] for r in states)==sorted(expected_states),(ident,states)
        held=sum(r['quantity'] for r in final['reservations'] if r['state'] in ('reserved','shipped'))
        assert available+held==10
        reservations=[e for e in final['effects'] if e['action']=='reserve']
        duplicate=len(reservations)-len({e['intent'] for e in reservations})
        blocked+=sum(r['state']=='rejected' for r in states)
        report=dict(case=ident,scenario=kind,operations=len(states),effects=n_effects,
                    duplicates=duplicate,unknown=sum(r['state']=='unknown' for r in states),
                    blocked=blocked,available=available,reconciliation_ms=recovery_ms,passed=True)
        write_json(folder/'evidence.json',dict(report=report,observations=observations,
                                             final_oracle=final,final_client=states,processes=b.events))
        with connect(b.client) as db:
            events=[dict(r) for r in db.execute('SELECT * FROM events ORDER BY seq')]
        return report,[dict(case=ident,**r) for r in events]
    finally:b.close()


def capture(folder):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=False)
    write_json(folder/'fault_schedule.json',{
        'protocol':'L15-1.0','clock':'logical seconds, initial 100; retention 50; deadline 150',
        'unit':'isolated scenario with its own databases; not a traffic sample',
        'admitted':len(CASES),'cases':[dict(id=c[0],fault=c[1],expected_effects=c[2],
            expected_stock=c[3],expected_states=c[4]) for c in CASES]})
    rows=[];ledger=[]
    try:
        for case in CASES:
            row,events=run_case(folder/case[0],case);rows.append(row);ledger.extend(events)
    except Exception as exc:
        write_json(folder/'incomplete.json',{'completed':len(rows),'error':repr(exc)})
        raise
    with (folder/'reconciliation_report.csv').open('w',encoding='utf8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (folder/'operation_ledger.jsonl').write_text(''.join(canonical(e)+'\n' for e in ledger),encoding='utf8')
    write_json(folder/'summary.json',{'admitted':len(CASES),'completed':len(rows),
        'passed':sum(r['passed'] for r in rows),'scenarios':rows,
        'limits':['Local HTTP and SQLite; no real supplier, LLM or authentication',
                  'Process termination and reply loss; no power loss or network partition',
                  'One execution per scenario; elapsed time is not an SLO estimate']})
    artifacts={str(p.relative_to(folder)).replace('\\','/'):sha(p) for p in folder.rglob('*')
               if p.is_file()}
    source={str(p.relative_to(PROJECT)).replace('\\','/'):sha(p)
            for p in (Path(__file__),PROJECT/'laboratorios/efeitos15.py')}
    write_json(folder/'manifesto.json',{'protocol':'L15-1.0','python':platform.python_version(),
        'platform':platform.platform(),'sqlite':sqlite3.sqlite_version,'artifacts':artifacts,'source':source})
    return verify(folder)


def verify(folder):
    folder=Path(folder);manifest=json.loads((folder/'manifesto.json').read_text(encoding='utf8'))
    for relative,expected in manifest['artifacts'].items():
        if sha(folder/relative)!=expected:raise ValueError('Artefato divergente: '+relative)
    for relative,expected in manifest['source'].items():
        if sha(PROJECT/relative)!=expected:raise ValueError('Código divergente: '+relative)
    summary=json.loads((folder/'summary.json').read_text(encoding='utf8'))
    if summary['admitted']!=len(CASES) or summary['completed']!=len(CASES):
        raise ValueError('Campanha incompleta')
    for case in CASES:
        data=json.loads((folder/case[0]/'evidence.json').read_text(encoding='utf8'))
        current=oracle(folder/case[0]/'destination.sqlite')
        if current!=data['final_oracle']:raise ValueError('Oráculo divergente')
        if len(current['effects'])!=case[2] or current['stock'][0]['available']!=case[3]:
            raise ValueError('Invariante violada')
        with connect(folder/case[0]/'client.sqlite') as db:
            states=[dict(r) for r in db.execute('SELECT * FROM operations ORDER BY intent')]
        if states!=data['final_client'] or sorted(r['state'] for r in states)!=sorted(case[4]):
            raise ValueError('Estado do cliente divergente')
    return dict(verified=len(CASES),artifacts=len(manifest['artifacts']),
                mode='saved evidence; no new HTTP execution',manifest_sha256=sha(folder/'manifesto.json'))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--saida',type=Path,required=True)
    parser.add_argument('--conferir',action='store_true');args=parser.parse_args()
    print(json.dumps(verify(args.saida) if args.conferir else capture(args.saida),ensure_ascii=False))


if __name__=='__main__':main()
