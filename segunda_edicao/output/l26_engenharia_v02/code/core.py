"""Contrato, armazenamento e transação de destino. Infraestrutura confiável local."""
import hashlib
import json
import os
import re
import time
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

VERSION = 'L26-1.0'
IMAGE = 'postgres@sha256:1ffbf339f5b8e78c394cfaad3711ef6dbc4e14546bf70428e0bb30cba66e8e4d'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(request):
    # Chave e token de execução não são conteúdo de negócio.
    return hashlib.sha256(canonical({k: v for k, v in request.items()
                                   if k not in ('key', 'token')}).encode()).hexdigest()


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                   default=str) + '\n', encoding='utf-8')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def connect(config, side, application='l26'):
    assert side in ('destination', 'client')
    assert re.fullmatch(r'l26_[a-z0-9_]+', config['schema'])
    db = psycopg.connect(host='127.0.0.1', port=config['port'], user='postgres',
                        dbname=side, connect_timeout=3, row_factory=dict_row,
                        application_name=application)
    db.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(config['schema'])))
    db.execute("SET statement_timeout = '12s'")
    db.execute("SET lock_timeout = '8s'")
    db.commit()
    return db


def initialize(config):
    for side in ('destination', 'client'):
        with connect(config, side) as db:
            db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(config['schema'])))
            if side == 'destination':
                db.execute('''CREATE TABLE stock(id text PRIMARY KEY, available int CHECK(available>=0), version int);
                INSERT INTO stock VALUES ('peca-A',10,0);
                CREATE TABLE receipts(tenant text, key text, hash text NOT NULL,
                    expires timestamptz NOT NULL, body jsonb, PRIMARY KEY(tenant,key));
                CREATE TABLE approvals(hash text PRIMARY KEY, enabled bool NOT NULL, expires timestamptz NOT NULL);
                CREATE TABLE effects(id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    tenant text, intent text, action text, quantity int, original bigint,
                    reversible bool DEFAULT true, created timestamptz DEFAULT clock_timestamp());
                CREATE UNIQUE INDEX one_release ON effects(original) WHERE action='release';
                CREATE TABLE fences(tenant text,intent text,token bigint,PRIMARY KEY(tenant,intent));''')
            else:
                db.execute('''CREATE TABLE jobs(id text PRIMARY KEY, request jsonb NOT NULL,
                    state text NOT NULL DEFAULT 'prepared', receipt jsonb, token bigint NOT NULL DEFAULT 0,
                    lease_until timestamptz, updated timestamptz DEFAULT clock_timestamp());
                CREATE TABLE outbox(id text PRIMARY KEY REFERENCES jobs(id), pending bool NOT NULL DEFAULT true);
                CREATE TABLE attempts(id text PRIMARY KEY, job text, mode text, token bigint,
                    started timestamptz DEFAULT clock_timestamp(), ended timestamptz, outcome text);
                CREATE TABLE control(id int PRIMARY KEY, admission bool);
                INSERT INTO control VALUES(1,true);''')


def request(config, intent='pedido-1', key='chave-1', **changes):
    with connect(config, 'destination') as db:
        now = float(db.execute('SELECT extract(epoch FROM clock_timestamp()) AS t').fetchone()['t'])
    value = dict(tenant='horizonte', intent=intent, key=key, action='reserve',
                 resource='peca-A', quantity=2, expected_version=0,
                 expires_at=now + 300, original=None)
    value.update(changes)
    return value


def admit(config, job, body):
    with connect(config, 'client') as db:
        allowed = db.execute('SELECT admission FROM control WHERE id=1 FOR SHARE').fetchone()['admission']
        if not allowed:
            raise ValueError('admission_suspended')
        inserted = db.execute('INSERT INTO jobs(id,request) VALUES(%s,%s) ON CONFLICT DO NOTHING RETURNING id',
                              (job, Jsonb(body))).fetchone()
        old = db.execute('SELECT request FROM jobs WHERE id=%s', (job,)).fetchone()['request']
        if old != body:
            raise ValueError('intent_identity_changed')
        if inserted:
            db.execute('INSERT INTO outbox(id) VALUES(%s)', (job,))
    with connect(config, 'destination') as db:
        db.execute('INSERT INTO approvals VALUES(%s,true,to_timestamp(%s)) ON CONFLICT DO NOTHING',
                   (digest(body), body['expires_at']))


def claim(db, job, lease_seconds=1.0):
    row = db.execute('''UPDATE jobs SET token=token+1,
        lease_until=clock_timestamp() + %s * interval '1 second'
        WHERE id=%s AND (lease_until IS NULL OR lease_until<clock_timestamp())
        RETURNING token,request''', (lease_seconds, job)).fetchone()
    return row


def valid_request(body):
    required = {'tenant','intent','key','action','resource','quantity','expected_version','expires_at','original'}
    return (isinstance(body, dict) and required <= body.keys()
            and body['action'] in ('reserve','release') and body['resource']=='peca-A'
            and type(body['quantity']) is int and body['quantity']>0
            and type(body['expected_version']) is int and body['expected_version']>=0
            and type(body['expires_at']) in (float,int)
            and all(isinstance(body[k],str) and 0<len(body[k])<=100 for k in ('tenant','key','intent')))


def barrier(directory, name, detail=None):
    directory = Path(directory)
    save(directory / (name + '.ready.json'), {'pid':os.getpid(),'time_ns':time.time_ns(),'detail':detail})
    limit = time.monotonic()+20
    while not (directory / (name + '.release')).exists():
        if time.monotonic()>limit:
            raise TimeoutError('harness_barrier_expired:'+name)
        time.sleep(.02)


def execute(config, body, hook=lambda point: None):
    if not valid_request(body):
        return 400, {'effect':'not_applied','reason':'invalid_request'}
    h = digest(body)
    with connect(config, 'destination', 'l26-dest-'+body['key']) as db:
        token = body.get('token', 0)
        if token:
            db.execute('INSERT INTO fences VALUES(%s,%s,0) ON CONFLICT DO NOTHING', (body['tenant'],body['intent']))
            current = db.execute('SELECT token FROM fences WHERE tenant=%s AND intent=%s FOR UPDATE',
                                 (body['tenant'],body['intent'])).fetchone()['token']
            if token < current:
                return 409, {'effect':'unknown','reason':'stale_fence'}
            db.execute('UPDATE fences SET token=%s WHERE tenant=%s AND intent=%s', (token,body['tenant'],body['intent']))
        inserted = db.execute('''INSERT INTO receipts VALUES(%s,%s,%s,clock_timestamp()+interval '300 seconds',NULL)
            ON CONFLICT DO NOTHING RETURNING key''', (body['tenant'],body['key'],h)).fetchone()
        if not inserted:
            old = db.execute('SELECT *,expires>clock_timestamp() AS live FROM receipts WHERE tenant=%s AND key=%s',
                             (body['tenant'],body['key'])).fetchone()
            if old['hash'] != h:
                return 409, {'effect':'unknown','reason':'key_payload_mismatch'}
            if not old['live']:
                return 410, {'effect':'unknown','reason':'retention_expired'}
            return 200, old['body']
        approval = db.execute('SELECT enabled AND expires>clock_timestamp() AS ok FROM approvals WHERE hash=%s', (h,)).fetchone()
        live = db.execute('SELECT clock_timestamp()<to_timestamp(%s) AS ok', (body['expires_at'],)).fetchone()['ok']
        if not live:
            result = {'effect':'not_applied','reason':'deadline_expired'}
        elif not approval or not approval['ok']:
            result = {'effect':'not_applied','reason':'approval_denied'}
        else:
            result = mutate(db, body)
        result.update(tenant=body['tenant'], key=body['key'], hash=h, intent=body['intent'])
        db.execute('UPDATE receipts SET body=%s WHERE tenant=%s AND key=%s', (Jsonb(result),body['tenant'],body['key']))
        hook('before_commit')
    hook('after_commit')
    return (200 if result['effect']=='applied' else 409), result


def mutate(db, body):
    stock = db.execute("SELECT * FROM stock WHERE id='peca-A' FOR UPDATE").fetchone()
    qty = body['quantity']
    if body['action']=='reserve':
        if stock['version'] != body['expected_version']:
            return {'effect':'not_applied','reason':'version_conflict'}
        if stock['available'] < qty:
            return {'effect':'not_applied','reason':'insufficient_stock'}
        delta = -qty
    else:
        original = db.execute('SELECT * FROM effects WHERE id=%s FOR UPDATE', (body['original'],)).fetchone()
        released = db.execute("SELECT id FROM effects WHERE original=%s AND action='release'", (body['original'],)).fetchone()
        if (not original or original['tenant']!=body['tenant'] or original['action']!='reserve'
                or original['quantity']!=qty or not original['reversible'] or released):
            return {'effect':'not_applied','reason':'compensation_forbidden'}
        delta = qty
    db.execute("UPDATE stock SET available=available+%s,version=version+1 WHERE id='peca-A'", (delta,))
    row = db.execute('''INSERT INTO effects(tenant,intent,action,quantity,original)
        VALUES(%s,%s,%s,%s,%s) RETURNING id''',
        (body['tenant'],body['intent'],body['action'],qty,body['original'])).fetchone()
    return {'effect':'applied','effect_id':row['id'],'action':body['action']}


def lookup(config, body):
    with connect(config, 'destination') as db:
        row = db.execute('SELECT *,expires>clock_timestamp() AS live FROM receipts WHERE tenant=%s AND key=%s',
                         (body['tenant'],body['key'])).fetchone()
    if not row:
        return 404, {'effect':'unknown','reason':'not_observed'}
    if row['hash']!=digest(body):
        return 409, {'effect':'unknown','reason':'key_payload_mismatch'}
    if not row['live']:
        return 410, {'effect':'unknown','reason':'retention_expired'}
    return 200, row['body']


def classify(body, reply):
    if reply.get('hash')!=digest(body) or reply.get('tenant')!=body['tenant'] or reply.get('key')!=body['key']:
        return 'unknown'
    return {'applied':'confirmed','not_applied':'rejected'}.get(reply.get('effect'),'unknown')
