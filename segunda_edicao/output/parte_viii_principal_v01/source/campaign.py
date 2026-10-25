"""L29-L32: plano fixado, processos reais, observação e restauração limpa."""
import argparse,json,platform,shutil,subprocess,sys,time
from importlib.metadata import version
from pathlib import Path
from .core import *
from . import http_lab
from laboratorios.parte_i.common import child,wait_file

def spawn(role,cfg,out,extra=()):
    return child('laboratorios.parte_viii.worker',[role,'--config',cfg,'--out',out,*extra],out/'process')

def source_snapshot(cfg):
    with connect(cfg) as c:
        return {t:c.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall() for t in ['jobs','outbox','checkpoints']}

def destination_snapshot(cfg):
    with connect(cfg,'destination') as c:
        return dict(effects=[dict(id=x['id'],value=x['value']) for x in c.execute('SELECT * FROM effects ORDER BY id')],
                    inbox=c.execute('SELECT * FROM inbox ORDER BY event').fetchall(),
                    resource=c.execute('SELECT * FROM resource ORDER BY id').fetchall())

def queue_lab(cfg,path):
    path.mkdir();config=path/'config.json';save(config,cfg);r=broker(cfg)
    r.xgroup_create('work','g',id='0',mkstream=True)
    with spawn('producer',config,path/'producer') as p:assert p.wait(15)==0
    save(path/'before.json',dict(length=r.xlen('work'),pending=r.xpending('work','g')))
    with spawn('consumer',config,path/'crashed',['--crash']) as p:
        wait_file(path/'crashed/after_effect.json',p)
        save(path/'inflight.json',dict(length=r.xlen('work'),pending=r.xpending('work','g'),destination=destination_snapshot(cfg)))
        p.terminate();p.wait(5);save(path/'crash.json',dict(pid=p.pid,returncode=p.returncode))
    with spawn('consumer',config,path/'recovered',['--name','successor']) as p:assert p.wait(20)==0
    save(path/'after.json',dict(length=r.xlen('work'),pending=r.xpending('work','g'),
        dead=r.xrange('dead'),destination=destination_snapshot(cfg)))
    # Justiça do escalonador, sob duas filas já carregadas e serviços de custo igual.
    fair=[]
    for mode in ['strict','round_robin']:
        for tenant in ['a','b']:
            key=mode+tenant
            for i in range(6 if tenant=='a' else 2):r.xadd(key,{'job':f'{tenant}{i}'})
        order=[]
        while len(order)<8:
            tenants=['a','b'] if mode=='round_robin' else ['a' if r.xlen(mode+'a') else 'b']
            for tenant in tenants:
                rows=r.xrange(mode+tenant,count=1)
                if rows:
                    mid,body=rows[0];order.append(body['job']);r.xdel(mode+tenant,mid)
        fair.append(dict(policy=mode,order=order,first_b_position=next(i+1 for i,x in enumerate(order) if x[0]=='b')))
    save(path/'fairness.json',fair)

def durable_lab(cfg,path):
    path.mkdir();config=path/'config.json';save(config,cfg)
    # Falha antes do commit prova atomicidade local job/outbox.
    try:
        with connect(cfg) as c:
            c.execute("INSERT INTO jobs VALUES('rollback','ready',1)")
            c.execute("INSERT INTO outbox(id) VALUES('rollback')")
            raise RuntimeError('injected_before_commit')
    except RuntimeError:pass
    with connect(cfg) as c:
        for i in range(3):
            intent=f'E{i}';c.execute('INSERT INTO jobs VALUES(%s,%s,1)',(intent,'ready'))
            c.execute('INSERT INTO outbox(id) VALUES(%s)',(intent,))
    save(path/'before.json',source_snapshot(cfg))
    with spawn('dispatch',config,path/'crashed',['--crash']) as p:
        wait_file(path/'crashed/after_effect.json',p)
        save(path/'uncertain.json',dict(source=source_snapshot(cfg),destination=destination_snapshot(cfg)))
        p.terminate();p.wait(5);save(path/'crash.json',dict(pid=p.pid,returncode=p.returncode))
    with spawn('dispatch',config,path/'resumed') as p:assert p.wait(15)==0
    fence=[]
    for guard in [False,True]:
        with connect(cfg,'destination') as c:c.execute("UPDATE resource SET token=0,value='initial'")
        with connect(cfg) as c:c.execute("UPDATE lease SET token=1,expires=clock_timestamp()+interval '250 milliseconds'")
        d=path/('guarded' if guard else 'unsafe')
        with spawn('stale',config,d,[] if guard else ['--unsafe']) as p:
            wait_file(d/'paused.json',p)
            def expired():
                with connect(cfg) as c:return c.execute('SELECT expires<clock_timestamp() AS expired FROM lease').fetchone()['expired']
            wait(expired)
            with connect(cfg) as c:token=c.execute("UPDATE lease SET token=token+1,expires=clock_timestamp()+interval '1 second' RETURNING token").fetchone()['token']
            newer=fenced_write(cfg,token,'new',guard);save(d/'resume.json',dict(lease_expired=True,new_token=token))
            assert p.wait(10)==0
            with connect(cfg,'destination') as c:state=c.execute('SELECT * FROM resource').fetchone()
            fence.append(dict(guard=guard,newer=newer,old=load(d/'result.json'),final=state))
    # Duas conexões, duas versões lidas; a segunda escrita condicional deve falhar.
    with connect(cfg) as a,connect(cfg) as b:
        v1=a.execute("SELECT version FROM jobs WHERE id='E0'").fetchone()['version']
        v2=b.execute("SELECT version FROM jobs WHERE id='E0'").fetchone()['version']
        first=a.execute("UPDATE jobs SET version=version+1 WHERE id='E0' AND version=%s",(v1,)).rowcount;a.commit()
        second=b.execute("UPDATE jobs SET version=version+1 WHERE id='E0' AND version=%s",(v2,)).rowcount
    reads=[]
    for isolation in ['READ COMMITTED','REPEATABLE READ']:
        with connect(cfg) as a,connect(cfg) as b:
            a.execute('SET TRANSACTION ISOLATION LEVEL '+isolation)
            before=a.execute("SELECT version FROM jobs WHERE id='E1'").fetchone()['version']
            b.execute("UPDATE jobs SET version=version+1 WHERE id='E1'");b.commit()
            after=a.execute("SELECT version FROM jobs WHERE id='E1'").fetchone()['version']
        reads.append(dict(isolation=isolation,before=before,after=after))
    # Replay com nova identidade, controle negativo explícito.
    effect(cfg,'E0-replay-control')
    conflict=False
    try:accept_event(cfg,'E0','different')
    except ValueError:conflict=True
    save(path/'after.json',dict(source=source_snapshot(cfg),destination=destination_snapshot(cfg),fencing=fence,
        optimistic=dict(first=first,second=second),reads=reads,event_conflict_rejected=conflict,
        migration=migrate(dict(schema_version=1,step=2))))

def recovery_lab(cfg,path):
    path.mkdir();r=broker(cfg)
    # Recuperação do estado de aplicação, separado dos recibos no destino.
    with connect(cfg) as c:
        c.execute("INSERT INTO checkpoints VALUES('flow',1,3)")
    before=source_snapshot(cfg);save(path/'before.json',before)
    index={row['id']:row['status'] for row in before['jobs']};save(path/'index.json',index)
    boundary=time.time();dump=command(['docker','exec',cfg['pg_container'],'pg_dump','-U','postgres','-Fc','source']).stdout
    (path/'source.dump').write_bytes(dump);expected=sha(path/'source.dump')
    # O diário está fora do backup; é uma dependência declarada da reconciliação.
    journal=[]
    for i in range(2):
        intent=f'R{i}';admitted=time.time()
        with connect(cfg) as c:c.execute('INSERT INTO jobs VALUES(%s,%s,1)',(intent,'ready'))
        effect(cfg,intent)
        journal.append(dict(id=intent,admitted_at=admitted,receipt=intent))
    save(path/'admission_journal.json',journal)
    for intent in ['E0','R0','R1']:r.xadd('restore-backlog',{'intent':intent})
    save(path/'backlog_before.json',r.xrange('restore-backlog'))
    bad=path/'corrupted.dump';bad.write_bytes(dump[:128]);corrupt_rejected=False
    try:validate_backup(bad,expected)
    except ValueError:corrupt_rejected=True
    save(path/'catalog.json',dict(database_hash=expected,index_hash=sha(path/'index.json'),
        snapshot_lower_bound_epoch=boundary,checkpoint_schema=1,backlog='restore-backlog',
        destination='survives outside restored database',journal='admission_journal.json',secrets='none; isolated trust mode'))
    # Destruição limitada ao banco source do contêiner recém-criado.
    start=time.perf_counter();incident=time.time()
    command(['docker','exec',cfg['pg_container'],'dropdb','-U','postgres','source'])
    validate_backup(path/'source.dump',expected)
    command(['docker','exec',cfg['clean_container'],'createdb','-U','postgres','source'])
    restore=command(['docker','exec','-i',cfg['clean_container'],'pg_restore','-U','postgres',
        '-d','source','--exit-on-error','--single-transaction'],input=dump)
    (path/'restore_stderr.txt').write_bytes(restore.stderr)
    clean={**cfg,'pg':cfg['clean']};restored=source_snapshot(clean);db_done=time.perf_counter()
    save(path/'restored_before_reconcile.json',restored)
    lost=sorted(set(x['id'] for x in journal)-set(x['id'] for x in restored['jobs']))
    actions=[]
    for mid,body in r.xrange('restore-backlog'):
        intent=body['intent']
        with connect(cfg,'destination') as c:receipt=c.execute('SELECT id,value FROM effects WHERE id=%s',(intent,)).fetchone()
        if not receipt:raise RuntimeError('manual_reconciliation_required')
        with connect(clean) as c:
            c.execute("INSERT INTO jobs VALUES(%s,'confirmed',1) ON CONFLICT(id) DO UPDATE SET status='confirmed'",(intent,))
        actions.append(dict(message_id=mid,intent=intent,action='receipt_only'));r.xdel('restore-backlog',mid)
    with connect(clean) as c:
        row=c.execute('SELECT schema_version,step FROM checkpoints').fetchone();up=migrate(row)
        c.execute('UPDATE checkpoints SET schema_version=%s,step=%s',(up['schema_version'],up['step']))
    final=source_snapshot(clean);rebuilt={x['id']:x['status'] for x in final['jobs']}
    save(path/'rebuilt_index.json',rebuilt)
    assert len(final['jobs'])==5 and all(x['status']=='confirmed' for x in final['jobs'])
    # Sonda local de leitura; não inclui front-end, DNS, IAM nem tráfego de usuários.
    with connect(clean) as c:assert c.execute('SELECT count(*) AS n FROM jobs').fetchone()['n']==5
    end=time.perf_counter()
    save(path/'after.json',dict(source=final,destination=destination_snapshot(cfg),lost_before_reconcile=lost,
        actions=actions,backlog=r.xrange('restore-backlog'),corrupt_rejected=corrupt_rejected,
        rto_database_seconds=db_done-start,rto_validated_seconds=end-start,
        backup_age_upper_bound_seconds=incident-boundary,missing_admission_times=[x['admitted_at'] for x in journal],
        rpo_count_before=2,rpo_count_after=0,index_entries_before=len(index),index_entries_after=len(rebuilt)))

def run(out):
    out.mkdir(parents=True,exist_ok=False)
    save(out/'plan.json',dict(version=1,labs=['L29','L30','L31','L32'],seed=29,
        http_faults=6,http_policies=2,queue_capacity=8,queue_offers=10,poison_delivery_limit=3,
        scope='local operational infrastructure; no model inference; no human quality claim'))
    inputs={}
    for path in sorted((ROOT/'laboratorios/parte_viii').glob('*.py')):
        rel=path.relative_to(ROOT).as_posix();inputs[rel]=sha(path)
        target=out/'source'/path.name;target.parent.mkdir(exist_ok=True);shutil.copyfile(path,target)
    inputs['requirements-parte-viii.lock.txt']=sha(ROOT/'requirements-parte-viii.lock.txt')
    save(out/'inputs.json',inputs)
    save(out/'environment.json',dict(python=sys.version,platform=platform.platform(),psycopg=version('psycopg'),redis=version('redis')))
    complete=False
    try:
        http_lab.run(out/'l29')
        with infrastructure(out) as cfg:
            initialize(cfg);queue_lab(cfg,out/'l30');durable_lab(cfg,out/'l31');recovery_lab(cfg,out/'l32')
        complete=True
    finally:seal(out,'parte-viii-v1',complete)
    print(json.dumps(dict(output=str(out),complete=complete)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);run(p.parse_args().out.resolve())
