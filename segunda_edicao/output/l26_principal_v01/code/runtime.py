"""Processos HTTP e worker. Apenas loopback; não constitui autenticação de produção."""
import argparse
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from psycopg.types.json import Jsonb
from .core import barrier, canonical, claim, classify, connect, execute, load, lookup, save


def serve(config, directory, fault):
    state = {'used':False}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = load_bytes(self.rfile.read(int(self.headers['Content-Length'])))
            with lock:
                active = fault if not state['used'] and self.path=='/execute' else 'none'
                if self.path=='/execute':
                    state['used'] = True

            def hook(point):
                if active == point:
                    save(directory/(point+'.ready.json'), {'pid':os.getpid(),'time_ns':time.time_ns()})
                    os._exit(71 if point=='before_commit' else 72)
                if active=='hold_commit' and point=='before_commit':
                    barrier(directory, 'commit')

            if self.path=='/execute':
                code, reply = execute(config, body, hook)
            elif self.path=='/lookup':
                if fault in ('no_lookup','unavailable_lookup'):
                    code, reply = (501 if fault=='no_lookup' else 503), {'effect':'unknown','reason':fault}
                else:
                    code, reply = lookup(config, body)
            else:
                code, reply = 404, {'effect':'unknown'}
            if active=='drop_reply':
                save(directory/'drop_reply.ready.json', {'pid':os.getpid(),'time_ns':time.time_ns()})
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            raw = canonical(reply).encode()
            self.send_response(code)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    save(directory/'server_ready.json', {'port':server.server_port,'pid':os.getpid()})
    server.serve_forever()


def load_bytes(raw):
    import json
    return json.loads(raw.decode())


def send(port, action, body):
    request = urllib.request.Request(f'http://127.0.0.1:{port}/{action}',
                                     data=canonical(body).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=15) as response:
            return response.status, load_bytes(response.read())
    except urllib.error.HTTPError as error:
        return error.code, load_bytes(error.read())


def worker(config, directory, job, attempt, port, mode, fault, bypass):
    started = time.perf_counter()
    with connect(config, 'client', 'l26-worker-'+attempt) as db:
        if bypass:
            row = db.execute('SELECT request,token FROM jobs WHERE id=%s', (job,)).fetchone()
            token = 0
        else:
            row = claim(db, job)
            if row is None:
                save(directory/(attempt+'.json'), {'outcome':'lease_busy','job':job,'pid':os.getpid()})
                return
            token = row['token']
        body = row['request']
        db.execute('INSERT INTO attempts(id,job,mode,token) VALUES(%s,%s,%s,%s)', (attempt,job,mode,token))
        db.execute("UPDATE jobs SET state='unknown',updated=clock_timestamp() WHERE id=%s", (job,))
    if fault=='before_send':
        save(directory/(attempt+'.before_send.json'), {'pid':os.getpid(),'time_ns':time.time_ns()})
        os._exit(73)
    if fault=='hold_send':
        barrier(directory, attempt+'.send', {'token':token})
    try:
        status, reply = send(port, mode, {**body, 'token':token} if mode=='execute' else body)
        outcome = classify(body, reply)
        error = None
    except (OSError, ValueError) as exc:
        status, reply, outcome, error = None, {}, 'unknown', type(exc).__name__+': '+str(exc)
    if fault=='after_receive':
        save(directory/(attempt+'.after_receive.json'), {'reply':reply,'status':status,'pid':os.getpid()})
        os._exit(74)
    with connect(config, 'client') as db:
        guard = '' if bypass else ' AND token=%s'
        params = [outcome,Jsonb(reply) if outcome!='unknown' else None,job]
        if guard:
            params.append(token)
        changed = db.execute('''UPDATE jobs SET state=%s,receipt=%s,lease_until=NULL,
            updated=clock_timestamp() WHERE id=%s'''+guard+' RETURNING id',params).fetchone()
        if changed and outcome in ('confirmed','rejected'):
            db.execute('UPDATE outbox SET pending=false WHERE id=%s',(job,))
        db.execute('UPDATE attempts SET ended=clock_timestamp(),outcome=%s WHERE id=%s', (outcome,attempt))
    save(directory/(attempt+'.json'),dict(job=job,attempt=attempt,mode=mode,token=token,
         pid=os.getpid(),status=status,reply=reply,outcome=outcome,ledger_updated=bool(changed),
         seconds=time.perf_counter()-started,error=error))


def main():
    p=argparse.ArgumentParser();p.add_argument('role',choices=['server','worker'])
    p.add_argument('--config',type=Path,required=True);p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--fault',default='none');p.add_argument('--job',default='job1')
    p.add_argument('--attempt',default='a1');p.add_argument('--port',type=int)
    p.add_argument('--mode',default='execute');p.add_argument('--bypass',action='store_true')
    a=p.parse_args();config=load(a.config)
    if a.role=='server':serve(config,a.directory,a.fault)
    else:worker(config,a.directory,a.job,a.attempt,a.port,a.mode,a.fault,a.bypass)


if __name__=='__main__':main()
