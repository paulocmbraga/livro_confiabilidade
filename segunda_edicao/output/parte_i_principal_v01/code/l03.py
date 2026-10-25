"""Serviço HTTP local, coletor real e observador externo em processos distintos.

Propostas do modelo e identidade autenticada são fixtures do harness confiável.
O parser não é fronteira de sandbox; não há LLM nem IdP nesta bancada.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from pathlib import Path
from contextlib import closing
import argparse, json, os, sqlite3, time
from .common import save, load

def request(url, payload=None):
    data=None if payload is None else json.dumps(payload).encode()
    try:
        with urlopen(Request(url,data=data,headers={'Content-Type':'application/json'}),timeout=2) as r:
            return r.status,json.loads(r.read())
    except HTTPError as e:
        return e.code,json.loads(e.read())

def initialize(db):
    with closing(sqlite3.connect(db)) as c, c:
        c.executescript('''
        CREATE TABLE effects (id TEXT PRIMARY KEY, tenant TEXT, cents INTEGER);
        CREATE TABLE audit (id TEXT PRIMARY KEY, event TEXT NOT NULL);
        ''')

def validate(proposal, context):
    if type(proposal) is not dict or set(proposal)!={'tenant','cents','revision'}:
        return 'schema'
    if type(proposal['cents']) is not int or not 0<proposal['cents']<=context['limit']:
        return 'amount'
    if proposal['tenant']!=context['tenant']:return 'tenant'
    if proposal['revision']!=context['revision']:return 'stale'
    if not context['authorized']:return 'authority'
    return None

def apply(db, mode, payload, collector):
    proposal=payload['proposal']; context=payload['context']; ident=payload['id']
    if mode=='protected':
        problem=validate(proposal,context)
        if problem:return 422,{'state':'rejected','reason':problem}
    else:
        # Controle deliberadamente inadequado: só tenta acessar campos.
        if type(proposal) is not dict or not {'tenant','cents'}<=set(proposal):
            return 500,{'state':'error','reason':'unvalidated_model_output'}
    telemetry_ok=False
    try:
        status,_=request(collector,{'event':ident,'available':payload['collector_up']})
        telemetry_ok=status==200
    except (URLError,TimeoutError):pass
    if mode=='naive' and not telemetry_ok:
        return 503,{'state':'failed','reason':'optional_collector'}
    if payload['audit_required_online'] and not telemetry_ok:
        return 503,{'state':'blocked','reason':'required_online_evidence'}
    # SQLite é destino e journal local. Sem atomicidade com o coletor remoto.
    c=sqlite3.connect(db,isolation_level=None)
    try:
        c.execute('BEGIN IMMEDIATE')
        buffered=c.execute('SELECT COUNT(*) FROM audit').fetchone()[0]
        if mode=='protected' and buffered>=payload['buffer_capacity']:
            c.rollback();return 503,{'state':'blocked','reason':'audit_capacity'}
        if c.execute('SELECT 1 FROM effects WHERE id=?',(ident,)).fetchone():
            c.rollback();return 409,{'state':'conflict','reason':'duplicate_id'}
        c.execute('INSERT INTO effects VALUES (?,?,?)',
                  (ident,proposal['tenant'],proposal['cents']))
        if mode=='protected':
            c.execute('INSERT INTO audit VALUES (?,?)',
                      (ident,json.dumps({'proposal':proposal,'context':context})))
        c.commit()
    finally:c.close()
    return 200,{'state':'applied','telemetry':'online' if telemetry_ok else 'buffered'}

def observe(db):
    with closing(sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro',uri=True)) as c:
        return {'effects':[list(r) for r in c.execute('SELECT * FROM effects ORDER BY id')],
                'audit':[list(r) for r in c.execute('SELECT * FROM audit ORDER BY id')],
                'observer_pid':os.getpid(),'observed_at':time.time()}

def serve(args):
    if args.role=='service':initialize(args.db)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def reply(self,status,body):
            raw=json.dumps(body).encode();self.send_response(status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):self.reply(200,{'pid':os.getpid(),'role':args.role})
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if args.role=='collector':
                self.reply(200 if data['available'] else 503,{'accepted':data['available']})
            else:
                status,body=apply(args.db,args.mode,data,args.collector);self.reply(status,body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    save(args.ready,{'port':server.server_port,'pid':os.getpid(),'role':args.role})
    server.serve_forever(poll_interval=.05)

def main():
    p=argparse.ArgumentParser();p.add_argument('role',choices=['service','collector','observe'])
    p.add_argument('--db',type=Path);p.add_argument('--ready',type=Path)
    p.add_argument('--mode',choices=['naive','protected']);p.add_argument('--collector')
    p.add_argument('--out',type=Path);a=p.parse_args()
    if a.role=='observe':save(a.out,observe(a.db))
    else:serve(a)

if __name__=='__main__':main()
