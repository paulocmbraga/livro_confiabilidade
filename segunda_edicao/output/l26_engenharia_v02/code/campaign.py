"""Campanha isolada e evidência bruta. Cada diretório novo admite exatamente 24 episódios."""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .core import IMAGE, VERSION, admit, connect, digest, initialize, load, request, save, sha

ROOT=Path(__file__).resolve().parents[2]
CASES=[
    ('P01','normal',1,8,['confirmed']),
    ('P02','drop_reply',1,8,['confirmed']),
    ('P03','new_identity_control',2,6,['confirmed','unknown']),
    ('P04','before_commit',1,8,['confirmed']),
    ('P05','after_commit',1,8,['confirmed']),
    ('P06','before_send',1,8,['confirmed']),
    ('P07','after_receive',1,8,['confirmed']),
    ('P08','same_key_concurrent',1,8,['confirmed']),
    ('P09','version_concurrent',1,8,['confirmed','rejected']),
    ('P10','payload_mismatch',1,8,['confirmed','unknown']),
    ('P11','retention_expired',1,8,['unknown']),
    ('P12','no_lookup',1,8,['unknown']),
    ('P13','unavailable_lookup',1,8,['unknown']),
    ('P14','compensation',2,10,['confirmed','confirmed']),
    ('P15','irreversible',1,8,['confirmed','rejected']),
    ('P16','approval_revoked',0,10,['rejected']),
    ('P17','insufficient_stock',0,10,['rejected']),
    ('P18','approval_expired',0,10,['rejected']),
    ('P19','old_worker',1,8,['confirmed']),
    ('P20','outbox_pending',1,8,['confirmed']),
    ('P21','outbox_redelivery',1,8,['confirmed']),
    ('P22','restore_reconcile',1,8,['confirmed']),
    ('P23','compensation_unknown',2,10,['confirmed','unknown']),
    ('P24','restore_unsafe_control',2,6,['confirmed']),
]


def command(args, **kw):
    return subprocess.run(args,check=True,capture_output=True,text=True,encoding='utf-8',**kw).stdout


def wait_for(fn, seconds=18):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        value=fn()
        if value:return value
        time.sleep(.04)
    raise TimeoutError('condition_not_observed')


def snapshot(config):
    result={}
    for side,tables in [('destination',['stock','effects','receipts','fences','approvals']),
                        ('client',['jobs','outbox','attempts','control'])]:
        with connect(config,side,'l26-observer') as db:
            result[side]={table:db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall() for table in tables}
    return result


class Episode:
    def __init__(self,root,case,config):
        self.path=root/case;self.path.mkdir();self.config=config
        self.cfg=self.path/'config.json';save(self.cfg,config)
        self.children=[];self.logs=[];self.server=None;self.server_index=0;self.trace=[]

    def event(self,name,**details):
        self.trace.append({'name':name,'time_ns':time.time_ns(),**details})
        save(self.path/'timeline.json',self.trace)

    def spawn(self,role,**opts):
        args=[sys.executable,'-m','laboratorios.l26.runtime',role,'--config',str(self.cfg),
              '--directory',str(self.path)]
        for k,v in opts.items():
            if v is True:args.append('--'+k)
            elif v is not False:args.extend(['--'+k,str(v)])
        log=(self.path/f'process_{len(self.children)+1:02d}.log').open('w',encoding='utf-8')
        p=subprocess.Popen(args,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        self.children.append(p);self.logs.append(log)
        self.event('spawn',role=role,pid=p.pid,options=opts)
        return p

    def start(self,fault='none'):
        ready=self.path/'server_ready.json'
        if ready.exists():
            ready.rename(self.path/f'server_ready_{self.server_index}.json')
        self.server_index+=1
        self.server=self.spawn('server',fault=fault)
        wait_for(lambda:ready.exists() or self.server.poll() is not None)
        assert ready.exists(),'server_failed'
        self.port=load(ready)['port']

    def stop_server(self):
        if self.server and self.server.poll() is None:
            self.server.terminate();self.server.wait(8)
        if self.server:self.event('server_exit',pid=self.server.pid,code=self.server.returncode)

    def worker(self,attempt,job='job1',mode='execute',fault='none',bypass=False,wait=True):
        p=self.spawn('worker',attempt=attempt,job=job,port=self.port,mode=mode,fault=fault,bypass=bypass)
        if wait:self.join(p)
        return p

    def join(self,p):
        code=p.wait(22);self.event('worker_exit',pid=p.pid,code=code)
        assert code in (0,73,74),f'worker_exit={code}'

    def lease_clear(self,job='job1'):
        def expired():
            with connect(self.config,'client') as db:
                return db.execute('SELECT lease_until IS NULL OR lease_until<clock_timestamp() AS ok FROM jobs WHERE id=%s',(job,)).fetchone()['ok']
        wait_for(expired,5)
        self.event('lease_expiry_observed',job=job)

    def snap(self,name):
        value=snapshot(self.config);save(self.path/(name+'.json'),value);return value

    def close(self):
        for p in self.children:
            if p.poll() is None:p.terminate();p.wait(8)
        for log in self.logs:log.close()
        save(self.path/'processes.json',[{'pid':p.pid,'returncode':p.returncode} for p in self.children])


def run_case(root,case,name,config,container):
    initialize(config)
    e=Episode(root,case,config)
    started=time.perf_counter()
    try:
        body=request(config,quantity=20 if case=='P17' else 2)
        # Snapshot real anterior à admissão. Apenas o schema deste caso, no banco client.
        if case in ('P22','P24'):
            dump=command(['docker','exec',container,'pg_dump','-U','postgres','-d','client',
                          '-n',config['schema'],'--clean','--if-exists','--no-owner','--no-privileges'])
            (e.path/'client_before.sql').write_text(dump,encoding='utf-8')
        admit(config,'job1',body)
        if case in ('P16','P18'):
            with connect(config,'destination') as db:
                query='UPDATE approvals SET enabled=false' if case=='P16' else "UPDATE approvals SET expires=clock_timestamp()-interval '1 second'"
                db.execute(query)
        initial_fault={
            'P02':'drop_reply','P03':'drop_reply','P04':'before_commit','P05':'after_commit',
            'P08':'hold_commit','P09':'hold_commit','P11':'drop_reply','P12':'drop_reply',
            'P13':'drop_reply','P21':'drop_reply'}.get(case,'none')
        e.start(initial_fault)
        e.snap('admitted')
        if case in ('P08','P09'):
            if case=='P09':admit(config,'job2',request(config,intent='pedido-2',key='chave-2'))
            first=e.worker('a1',bypass=True,wait=False)
            wait_for(lambda:(e.path/'commit.ready.json').exists())
            second=e.worker('a2',job='job2' if case=='P09' else 'job1',bypass=True,wait=False)
            def blocked():
                with connect(config,'destination') as db:
                    return db.execute("SELECT pid,application_name,state,wait_event_type,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE datname='destination' AND cardinality(pg_blocking_pids(pid))>0").fetchall()
            observed=wait_for(blocked)
            save(e.path/'overlap.json',observed)
            assert first.poll() is None and second.poll() is None
            e.event('database_block_observed',pids=[first.pid,second.pid],rows=observed)
            (e.path/'commit.release').write_text('release',encoding='ascii')
            e.join(first);e.join(second)
        elif case=='P19':
            first=e.worker('a1',fault='hold_send',wait=False)
            wait_for(lambda:(e.path/'a1.send.ready.json').exists())
            e.lease_clear();e.snap('lease_expired')
            e.worker('a2');e.snap('successor_confirmed')
            (e.path/'a1.send.release').write_text('release',encoding='ascii')
            e.join(first)
        else:
            if case=='P20':
                before=e.snap('outbox_before_dispatch')
                assert not before['destination']['effects'] and before['client']['outbox'][0]['pending']
            e.worker('a1',fault={'P06':'before_send','P07':'after_receive'}.get(case,'none'))
        e.snap('after_first_phase')
        if case in ('P02','P04','P05','P06','P07'):
            if case in ('P04','P05'):e.stop_server();e.start()
            e.lease_clear()
            e.worker('a2',mode='lookup')
            e.snap('after_lookup')
            if case in ('P04','P06'):
                e.lease_clear();e.worker('a3')
        elif case=='P03':
            # Controle defeituoso: a aplicação replaneja a MESMA intenção e cria outra chave.
            new={**body,'key':'chave-nova','expected_version':1}
            admit(config,'job2',new);e.worker('a2',job='job2')
        elif case=='P10':
            admit(config,'job2',{**body,'quantity':3});e.worker('a2',job='job2')
        elif case=='P11':
            with connect(config,'destination') as db:
                db.execute("UPDATE receipts SET expires=clock_timestamp()+interval '0.25 seconds'")
            wait_for(lambda: expired_receipt(config))
            e.event('retention_expiry_observed');e.worker('a2',mode='lookup');e.worker('a3')
        elif case in ('P12','P13'):
            e.stop_server();e.start('no_lookup' if case=='P12' else 'unavailable_lookup')
            e.worker('a2',mode='lookup')
        elif case in ('P14','P15','P23'):
            if case=='P15':
                with connect(config,'destination') as db:db.execute('UPDATE effects SET reversible=false')
            comp=request(config,intent='compensacao-1',key='chave-comp',action='release',original=1)
            admit(config,'job2',comp)
            if case=='P23':e.stop_server();e.start('drop_reply')
            e.worker('a2',job='job2')
            if case=='P23':
                e.stop_server();e.start('unavailable_lookup');e.worker('a3',job='job2',mode='lookup')
        elif case=='P21':
            e.snap('outbox_after_remote_commit');e.worker('a2')
        elif case in ('P22','P24'):
            before=snapshot(config)['destination']
            command(['docker','exec','-i',container,'psql','-U','postgres','-d','client','-v','ON_ERROR_STOP=1'],
                    input=(e.path/'client_before.sql').read_text(encoding='utf-8'))
            e.snap('after_restore')
            assert snapshot(config)['destination']==before,'restore_touched_destination'
            if case=='P22':
                with connect(config,'client') as db:db.execute('UPDATE control SET admission=false')
                try:admit(config,'blocked-new',request(config,key='unsafe',expected_version=1))
                except ValueError as exc:e.event('admission_blocked',reason=str(exc))
                else:raise AssertionError('restored_admission_not_blocked')
                # Reconstrução a partir do envelope persistido fora do backup perdido.
                from psycopg.types.json import Jsonb
                with connect(config,'client') as db:
                    db.execute('INSERT INTO jobs(id,request,state) VALUES(%s,%s,%s)',('job1',Jsonb(body),'unknown'))
                    db.execute('INSERT INTO outbox(id) VALUES(%s)',('job1',))
                e.worker('a2',mode='lookup')
            else:
                admit(config,'job2',{**body,'key':'chave-pos-restore','expected_version':1})
                e.worker('a2',job='job2')
        final=e.snap('final')
        e.event('episode_complete',seconds=time.perf_counter()-started)
        return final
    finally:e.close()


def expired_receipt(config):
    with connect(config,'destination') as db:
        return db.execute('SELECT bool_and(expires<clock_timestamp()) AS ok FROM receipts').fetchone()['ok']


def run(output):
    output.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter();container='livro-l26-'+uuid.uuid4().hex[:10]
    plan={'version':VERSION,'unit':'isolated scheduled episode, one execution each',
          'cases':[dict(id=c,name=n,effects=fx,stock=s,states=st,control=c in ('P03','P24')) for c,n,fx,s,st in CASES]}
    save(output/'plan.json',plan)
    for file in Path(__file__).parent.glob('*.py'):
        (output/'code').mkdir(exist_ok=True);shutil.copy2(file,output/'code'/file.name)
    started_container=False
    try:
        command(['docker','run','-d','--name',container,'--label','book.lab=L26',
                 '-e','POSTGRES_HOST_AUTH_METHOD=trust','-p','127.0.0.1::5432',
                 IMAGE,'-c','fsync=on','-c','synchronous_commit=on'])
        started_container=True
        wait_for(lambda:subprocess.run(['docker','exec',container,'pg_isready','-h','127.0.0.1','-U','postgres'],capture_output=True).returncode==0,35)
        port=int(command(['docker','port',container,'5432/tcp']).strip().rsplit(':',1)[1])
        for db in ('destination','client'):
            command(['docker','exec',container,'createdb','-U','postgres',db])
        environment={'python':sys.version,'platform':platform.platform(),'docker':command(['docker','version','--format','{{.Server.Version}}']).strip(),
                     'image':IMAGE,'port':port,'container':container,'date_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                     'postgres':command(['docker','exec',container,'psql','-U','postgres','-Atc','select version()']).strip()}
        save(output/'environment.json',environment)
        for case,name,*_ in CASES:
            run_case(output,case,name,dict(port=port,schema='l26_'+case.lower()),container)
            print(case+' complete',flush=True)
        (output/'postgres.log').write_text(command(['docker','logs',container]),encoding='utf-8')
        save(output/'resources.json',{'seconds':time.perf_counter()-started,
              'docker_stats_at_end':command(['docker','stats','--no-stream','--format','{{json .}}',container]).strip(),
              'measurement_scope':'elapsed campaign; terminal Docker snapshot, not peak memory; no SLA or inference'})
    except BaseException as exc:
        save(output/'incomplete.json',{'error':type(exc).__name__+': '+str(exc),
             'stdout':getattr(exc,'stdout',None),'stderr':getattr(exc,'stderr',None)});raise
    finally:
        if started_container:
            # Remove apenas o contêiner efêmero criado nesta execução; sem volumes do usuário.
            command(['docker','rm','-f','-v',container])
            save(output/'cleanup.json',{'owned_container_removed':container})
    files={p.relative_to(output).as_posix():sha(p) for p in sorted(output.rglob('*')) if p.is_file()}
    save(output/'manifesto.json',{'version':VERSION,'files':files,'episodes':len(CASES)})


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();run(a.out.resolve())


if __name__=='__main__':main()
