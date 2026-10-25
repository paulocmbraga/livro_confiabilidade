"""Contratos compartilhados; somente recursos criados pela campanha."""
from contextlib import contextmanager
from pathlib import Path
import json, os, random, subprocess, time, uuid
import psycopg
from psycopg.rows import dict_row
import redis
from laboratorios.parte_i.common import save, load, sha, digest, seal, check_manifest

ROOT=Path(__file__).resolve().parents[2]
PG='postgres@sha256:1ffbf339f5b8e78c394cfaad3711ef6dbc4e14546bf70428e0bb30cba66e8e4d'
REDIS='redis@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99'
FLAGS=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0

def command(args, **kw):
    return subprocess.run(args,check=True,capture_output=True,**kw)

def wait(fn, seconds=40):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            value=fn()
            if value:return value
        except (psycopg.OperationalError,redis.ConnectionError):pass
        time.sleep(.05)
    raise TimeoutError('condition_not_observed')

def connect(cfg, database='source', **kwargs):
    return psycopg.connect(host='127.0.0.1',port=cfg['pg'],user='postgres',
        dbname=database,row_factory=dict_row,connect_timeout=4,**kwargs)

def broker(cfg):
    return redis.Redis(host='127.0.0.1',port=cfg['redis'],decode_responses=True,
                       socket_timeout=4,socket_connect_timeout=4)

@contextmanager
def infrastructure(folder):
    names=[];cfg={};record=[]
    try:
        for key,image,port,extra in [
            ('pg',PG,5432,['-e','POSTGRES_HOST_AUTH_METHOD=trust']),
            ('clean',PG,5432,['-e','POSTGRES_HOST_AUTH_METHOD=trust']),
            ('redis',REDIS,6379,[])]:
            name='livro-viii-'+uuid.uuid4().hex[:12];names.append(name)
            args=['docker','run','-d','--name',name,'--label','book.lab=parte-viii',
                  '-p',f'127.0.0.1::{port}',*extra,image]
            if key=='redis':args+=['redis-server','--appendonly','yes','--appendfsync','always']
            command(args)
            info=json.loads(command(['docker','inspect',name]).stdout)[0]
            cfg[key]=int(info['NetworkSettings']['Ports'][f'{port}/tcp'][0]['HostPort'])
            cfg[key+'_container']=name
            record.append(dict(role=key,name=name,image=info['Image'],host_port=cfg[key]))
        wait(lambda:connect(cfg,'postgres').close() is None)
        wait(lambda:connect({'pg':cfg['clean']},'postgres').close() is None)
        wait(lambda:broker(cfg).ping())
        for db in ['source','destination']:
            command(['docker','exec',cfg['pg_container'],'createdb','-U','postgres',db])
        save(folder/'infra.json',record)
        save(folder/'versions.json',dict(postgresql=command(['docker','exec',cfg['pg_container'],
            'postgres','--version']).stdout.decode().strip(),redis=broker(cfg).info()['redis_version']))
        yield cfg
    finally:
        removed=[]
        for name in reversed(names):
            result=subprocess.run(['docker','rm','-f','-v',name],capture_output=True)
            removed.append(dict(name=name,returncode=result.returncode))
        save(folder/'cleanup.json',removed)

def initialize(cfg):
    with connect(cfg) as c:
        c.execute('CREATE TABLE jobs(id text PRIMARY KEY, status text NOT NULL, version int NOT NULL DEFAULT 1)')
        c.execute('CREATE TABLE outbox(id text PRIMARY KEY, sent boolean NOT NULL DEFAULT false)')
        c.execute('CREATE TABLE checkpoints(id text PRIMARY KEY, schema_version int NOT NULL, step int NOT NULL)')
        c.execute('CREATE TABLE lease(id text PRIMARY KEY, token bigint NOT NULL, expires timestamptz NOT NULL)')
        c.execute("INSERT INTO lease VALUES('resource',1,clock_timestamp()+interval '200 milliseconds')")
    with connect(cfg,'destination') as c:
        c.execute('CREATE TABLE effects(id text PRIMARY KEY, value text NOT NULL, created timestamptz DEFAULT clock_timestamp())')
        c.execute('CREATE TABLE inbox(event text PRIMARY KEY, body_hash text NOT NULL)')
        c.execute('CREATE TABLE resource(id text PRIMARY KEY, token bigint NOT NULL, value text NOT NULL)')
        c.execute("INSERT INTO resource VALUES('r',0,'initial')")

def effect(cfg, intent, value='accepted'):
    with connect(cfg,'destination') as c:
        row=c.execute('INSERT INTO effects(id,value) VALUES(%s,%s) ON CONFLICT DO NOTHING RETURNING id',
                      (intent,value)).fetchone()
        existing=c.execute('SELECT value FROM effects WHERE id=%s',(intent,)).fetchone()
        if existing['value']!=value:raise ValueError('intent_payload_conflict')
        return 'applied' if row else 'receipt'

def accept_event(cfg,event,value='accepted'):
    body=digest(dict(id=event,value=value))
    with connect(cfg,'destination') as c:
        inserted=c.execute('INSERT INTO inbox VALUES(%s,%s) ON CONFLICT DO NOTHING RETURNING event',
                           (event,body)).fetchone()
        current=c.execute('SELECT body_hash FROM inbox WHERE event=%s',(event,)).fetchone()
        if current['body_hash']!=body:raise ValueError('event_payload_conflict')
        if inserted:c.execute('INSERT INTO effects(id,value) VALUES(%s,%s)',(event,value))
        return 'applied' if inserted else 'duplicate'

def fenced_write(cfg,token,value,guard=True):
    with connect(cfg,'destination') as c:
        if guard:
            row=c.execute('UPDATE resource SET token=%s,value=%s WHERE id=%s AND token<%s RETURNING *',
                          (token,value,'r',token)).fetchone()
        else:row=c.execute("UPDATE resource SET token=%s,value=%s WHERE id='r' RETURNING *",(token,value)).fetchone()
        return 'accepted' if row else 'stale'

ADMIT="""
if redis.call('XLEN',KEYS[1])>=tonumber(ARGV[1]) then return false end
return redis.call('XADD',KEYS[1],'*','intent',ARGV[2],'kind',ARGV[3],'at',ARGV[4])
"""
ACK="""
local n=redis.call('XACK',KEYS[1],ARGV[1],ARGV[2])
if n==1 then redis.call('XDEL',KEYS[1],ARGV[2]) end
return n
"""
DEAD="""
local n=redis.call('XACK',KEYS[1],ARGV[1],ARGV[2])
if n==1 then
 redis.call('XADD',KEYS[2],'*','intent',ARGV[3],'reason','poison')
 redis.call('XDEL',KEYS[1],ARGV[2])
end
return n
"""

def remaining(deadline,now,reserve=0):
    return max(0.,deadline-now-reserve)

def jitter(attempt,seed,base=.01,cap=.1):
    if attempt<0:raise ValueError('attempt')
    return random.Random(seed+attempt).uniform(0,min(cap,base*2**attempt))

def migrate(state):
    version=state.get('schema_version')
    if type(version) is not int:raise ValueError('schema_type')
    if version==1:return dict(schema_version=2,step=state['step'],receipt=None)
    if version==2:return dict(state)
    raise ValueError('unsupported_schema')

def validate_backup(path,expected):
    if sha(path)!=expected:raise ValueError('backup_hash_mismatch')
    return True
