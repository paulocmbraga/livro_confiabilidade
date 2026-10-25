"""Bundles imutáveis e publicação local transacional; barreira antes de servir."""
from contextlib import contextmanager
from pathlib import Path
import argparse, json, os, sqlite3, time
import numpy as np
from laboratorios.parte_i.common import digest, load, save
from .retrieval import exact_cache_key


@contextmanager
def connection(path):
    con = sqlite3.connect(path, timeout=5, isolation_level=None)
    con.execute('PRAGMA foreign_keys=ON')
    try: yield con
    finally: con.close()


def init(path):
    with connection(path) as c:
        c.executescript('''
          PRAGMA journal_mode=WAL;
          CREATE TABLE bundles(id TEXT PRIMARY KEY, hash TEXT NOT NULL, payload TEXT NOT NULL);
          CREATE TABLE active(singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            bundle TEXT REFERENCES bundles(id), epoch INTEGER NOT NULL, auth_epoch INTEGER NOT NULL);
          INSERT INTO active VALUES(1,NULL,0,0);
          CREATE TABLE revoked(doc TEXT PRIMARY KEY);
          CREATE TABLE cache(key TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE history(epoch INTEGER PRIMARY KEY, bundle TEXT NOT NULL, reason TEXT NOT NULL);
        ''')


def stage(path, bundle):
    if len(bundle['documents']) != len(bundle['vectors']): raise ValueError('Índice incompleto')
    ids = [d['id'] for d in bundle['documents']]
    if len(ids) != len(set(ids)) or not ids: raise ValueError('Identidades inválidas')
    vectors = np.asarray(bundle['vectors'], dtype=float)
    if vectors.ndim != 2 or not np.isfinite(vectors).all(): raise ValueError('Vetores inválidos')
    if any(d['version'] != bundle['version'] for d in bundle['documents']): raise ValueError('Mistura de versões')
    with connection(path) as c:
        c.execute('INSERT INTO bundles VALUES(?,?,?)', (bundle['id'], digest(bundle), json.dumps(bundle, ensure_ascii=False)))


def publish(path, identifier, reason='update', crash=None):
    with connection(path) as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT payload,hash FROM bundles WHERE id=?', (identifier,)).fetchone()
        if not row or digest(json.loads(row[0])) != row[1]: raise ValueError('Bundle ausente ou divergente')
        epoch = c.execute('SELECT epoch FROM active').fetchone()[0]+1
        c.execute('UPDATE active SET bundle=?,epoch=?', (identifier,epoch))
        c.execute('INSERT INTO history VALUES(?,?,?)', (epoch,identifier,reason))
        if crash == 'before_commit': os._exit(86)
        c.execute('COMMIT')
        if crash == 'after_commit': os._exit(86)
        return epoch


def revoke(path, identifier):
    with connection(path) as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('INSERT OR IGNORE INTO revoked VALUES(?)', (identifier,))
        c.execute('UPDATE active SET auth_epoch=auth_epoch+1')
        # Simplificação conservadora: invalida todo o cache local.
        c.execute('DELETE FROM cache'); c.execute('COMMIT')


def snapshot(path):
    with connection(path) as c:
        c.execute('BEGIN')
        row = c.execute('SELECT bundle,epoch,auth_epoch FROM active').fetchone()
        data = c.execute('SELECT payload,hash FROM bundles WHERE id=?', (row[0],)).fetchone()
        revoked = [r[0] for r in c.execute('SELECT doc FROM revoked ORDER BY doc')]
        c.execute('COMMIT')
    if data is None: raise ValueError('Nenhum bundle ativo')
    bundle = json.loads(data[0])
    if digest(bundle) != data[1]: raise ValueError('Integridade do bundle')
    return {'bundle': bundle, 'hash': data[1], 'epoch': row[1], 'auth_epoch': row[2], 'revoked': revoked}


def candidate(snap, tenant, question, query_vector):
    bundle = snap['bundle']; vectors = np.asarray(bundle['vectors'],dtype=np.float32)
    q = np.asarray(query_vector,dtype=np.float32)
    allowed = [i for i,d in enumerate(bundle['documents']) if d['tenant'] == tenant and d['id'] not in snap['revoked']]
    ranked = sorted(allowed,key=lambda i:(-float(vectors[i]@q),bundle['documents'][i]['id']))
    selected = [bundle['documents'][i] for i in ranked[:1]]
    return {'tenant': tenant, 'question': question, 'bundle': bundle['id'], 'epoch': snap['epoch'],
            'auth_epoch': snap['auth_epoch'], 'bundle_hash': snap['hash'],
            'embedding': bundle['embedding'], 'index_version': bundle['version'],
            'answer': selected[0]['text'] if selected else 'SEM EVIDÊNCIA',
            'citations': [d['id'] for d in selected], 'cache_hit': False,
            'generator': 'extractive-v1', 'prompt': 'return-top1-text-v1'}


def cache_key(result):
    return exact_cache_key(result['tenant'],result['epoch'],result['auth_epoch'],result['bundle_hash'],
                           result['prompt'],result['generator'],result['question'])


def deliver(path, result, safe=True):
    with connection(path) as c:
        c.execute('BEGIN IMMEDIATE')
        current = c.execute('SELECT bundle,epoch,auth_epoch FROM active').fetchone()
        if safe and current != (result['bundle'],result['epoch'],result['auth_epoch']):
            c.execute('ROLLBACK'); return {'status': 'superseded', 'served': False, 'candidate': result}
        c.execute('INSERT OR REPLACE INTO cache VALUES(?,?)', (cache_key(result),json.dumps(result,ensure_ascii=False)))
        c.execute('COMMIT')
    return {'status': 'served', 'served': True, 'response': result}


def query(path, tenant, question, vector):
    snap = snapshot(path); proposed = candidate(snap,tenant,question,vector)
    with connection(path) as c:
        row = c.execute('SELECT payload FROM cache WHERE key=?',(cache_key(proposed),)).fetchone()
    if row:
        proposed=json.loads(row[0]); proposed['cache_hit']=True
    return deliver(path,proposed)


def worker():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True)
    p.add_argument('--action',choices=['read','publish'],required=True);p.add_argument('--input',type=Path)
    p.add_argument('--out',type=Path);p.add_argument('--ready',type=Path);p.add_argument('--go',type=Path)
    p.add_argument('--bundle');p.add_argument('--crash',choices=['before_commit','after_commit']);p.add_argument('--unsafe',action='store_true')
    a=p.parse_args()
    if a.action=='publish':publish(a.db,a.bundle,crash=a.crash);return
    started=time.perf_counter();request=load(a.input);snap=snapshot(a.db)
    result=candidate(snap,request['tenant'],request['question'],request['vector'])
    if a.ready:
        save(a.ready,{'pid':os.getpid(),'epoch':snap['epoch'],'ready_at':time.time()})
        limit=time.monotonic()+20
        while not a.go.exists():
            if time.monotonic()>limit:raise TimeoutError('Barreira de ensaio')
            time.sleep(.01)
    delivery=deliver(a.db,result,safe=not a.unsafe)
    save(a.out,{'pid':os.getpid(),'seconds':time.perf_counter()-started,'delivery':delivery})


if __name__=='__main__':worker()
