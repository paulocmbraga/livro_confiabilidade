"""L15: destino transacional e cliente persistente. Apenas bancada local.

Relógio lógico, identidades e aprovações são fixtures, não autenticação.
O HTTP não expõe endpoints de administração ou injeção de falhas.
"""
import argparse
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf8')).hexdigest()


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(path):
    db = sqlite3.connect(path, timeout=10, isolation_level=None, factory=Connection)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA synchronous=FULL')
    return db


def initialize(path):
    with connect(path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS stock(
          resource TEXT PRIMARY KEY, available INTEGER CHECK(available>=0), version INTEGER);
        INSERT OR IGNORE INTO stock VALUES('peca-A',10,0);
        CREATE TABLE IF NOT EXISTS approvals(
          hash TEXT PRIMARY KEY, until_time INTEGER, revoked INTEGER);
        CREATE TABLE IF NOT EXISTS receipts(
          principal TEXT, key TEXT, hash TEXT, expires INTEGER, body TEXT,
          PRIMARY KEY(principal,key));
        CREATE TABLE IF NOT EXISTS reservations(
          id TEXT PRIMARY KEY, intent TEXT, resource TEXT, quantity INTEGER,
          state TEXT, version INTEGER);
        CREATE TABLE IF NOT EXISTS effects(
          seq INTEGER PRIMARY KEY AUTOINCREMENT, intent TEXT, action TEXT,
          reservation TEXT, quantity INTEGER);
        ''')


def approve(path, request, until=200, revoked=False):
    # Provisionamento da bancada, fora do transporte HTTP.
    with connect(path) as db:
        db.execute('INSERT OR REPLACE INTO approvals VALUES(?,?,?)',
                   (digest(request), until, int(revoked)))


def request_for(intent='pedido-1', key='chave-1', quantity=2, expected_version=0):
    return dict(principal='operador-horizonte', key=key, intent=intent,
                action='reserve', resource='peca-A', quantity=quantity,
                expected_version=expected_version, deadline=150)


class Destination:
    def __init__(self, path, now=100, fault='none', lookup='yes', legacy=False):
        self.path, self.now, self.fault = Path(path), now, fault
        self.lookup_enabled, self.legacy = lookup, legacy
        self.lock = threading.Lock()

    def consume_fault(self):
        with self.lock:
            fault, self.fault = self.fault, 'none'
            return fault

    def lookup(self, principal, key):
        if self.lookup_enabled == 'no':
            return 501, {'error': 'lookup_unsupported'}
        if self.lookup_enabled == 'unavailable':
            return 503, {'error': 'lookup_unavailable'}
        with connect(self.path) as db:
            row = db.execute('SELECT * FROM receipts WHERE principal=? AND key=?',
                             (principal, key)).fetchone()
        if not row:
            return 404, {'error': 'not_observed'}
        if self.now >= row['expires']:
            return 410, {'error': 'retention_expired'}
        return 200, json.loads(row['body'])

    def execute(self, req):
        required = {'principal','key','intent','action','resource','quantity',
                    'expected_version','deadline'}
        if not isinstance(req, dict) or not required <= req.keys():
            return 400, {'error': 'invalid_request', 'effect': 'not_applied'}, 'none'
        if (req['action'] not in ('reserve','release') or req['resource'] != 'peca-A'
                or type(req['quantity']) is not int or req['quantity'] <= 0
                or type(req['expected_version']) is not int
                or type(req['deadline']) is not int
                or any(not isinstance(req[k], str) or not req[k]
                       for k in ('principal','key','intent'))):
            return 400, {'error': 'invalid_request', 'effect': 'not_applied'}, 'none'
        db = connect(self.path)
        try:
            db.execute('BEGIN IMMEDIATE')
            def reject(code, reason, uncertain=False):
                db.rollback()
                return code, {'error':reason,
                              'effect':'unknown' if uncertain else 'not_applied'}, 'none'
            h = digest(req)
            old = db.execute('SELECT * FROM receipts WHERE principal=? AND key=?',
                             (req['principal'],req['key'])).fetchone()
            if old and not self.legacy:
                if old['hash'] != h:
                    return reject(409,'key_payload_mismatch', True)
                if self.now >= old['expires']:
                    return reject(410,'retention_expired', True)
                db.rollback()
                return 200, json.loads(old['body']), 'none'
            if self.now >= req['deadline']:
                return reject(410,'request_expired', True)
            approval = db.execute('SELECT * FROM approvals WHERE hash=?',(h,)).fetchone()
            if not approval or approval['revoked'] or self.now >= approval['until_time']:
                return reject(403,'approval_denied')
            if req['action'] == 'reserve':
                stock = db.execute('SELECT * FROM stock WHERE resource=?',
                                   (req['resource'],)).fetchone()
                if not self.legacy and stock['version'] != req['expected_version']:
                    return reject(409,'version_conflict')
                if stock['available'] < req['quantity']:
                    return reject(409,'insufficient_stock')
                rid = str(uuid.uuid4())
                db.execute('UPDATE stock SET available=available-?,version=version+1 WHERE resource=?',
                           (req['quantity'],req['resource']))
                db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?)',
                           (rid,req['intent'],req['resource'],req['quantity'],'reserved',0))
            else:
                rid = req.get('reservation')
                reservation = db.execute('SELECT * FROM reservations WHERE id=?',(rid,)).fetchone()
                if (not reservation or reservation['state'] != 'reserved'
                        or reservation['version'] != req['expected_version']
                        or reservation['quantity'] != req['quantity']
                        or reservation['resource'] != req['resource']):
                    return reject(409,'compensation_forbidden')
                db.execute("UPDATE reservations SET state='released',version=version+1 WHERE id=?",(rid,))
                db.execute('UPDATE stock SET available=available+?,version=version+1 WHERE resource=?',
                           (req['quantity'],req['resource']))
            body = dict(principal=req['principal'], key=req['key'], hash=h,
                        intent=req['intent'], action=req['action'], reservation=rid,
                        effect='applied', committed_at=self.now)
            db.execute('INSERT INTO effects(intent,action,reservation,quantity) VALUES(?,?,?,?)',
                       (req['intent'],req['action'],rid,req['quantity']))
            if not self.legacy:
                db.execute('INSERT INTO receipts VALUES(?,?,?,?,?)',
                           (req['principal'],req['key'],h,self.now+50,canonical(body)))
            fault = self.consume_fault()
            if fault == 'before_commit':
                os._exit(71)
            db.commit()
            if fault == 'after_commit':
                os._exit(72)
            return 200, body, fault
        finally:
            db.close()


def serve(args):
    destination = Destination(args.db, args.now, args.fault, args.lookup, args.legacy)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body):
            raw = canonical(body).encode('utf8')
            self.send_response(code)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            self.reply(*destination.lookup(query.get('principal',[''])[0],query.get('key',[''])[0]))

        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 8192:
                    raise ValueError('size')
                req = json.loads(self.rfile.read(size))
            except (ValueError, UnicodeError):
                self.reply(400, {'error':'invalid_json','effect':'not_applied'})
                return
            code, body, fault = destination.execute(req)
            if fault == 'drop_reply':
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.reply(code, body)
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    Path(args.ready).write_text(str(server.server_address[1]),encoding='ascii')
    server.serve_forever()


def init_ledger(path, request):
    with connect(path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS operations(
          intent TEXT PRIMARY KEY, request TEXT, state TEXT, receipt TEXT);
        CREATE TABLE IF NOT EXISTS events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT, intent TEXT, state TEXT, detail TEXT);
        ''')
        old = db.execute('SELECT request FROM operations WHERE intent=?',(request['intent'],)).fetchone()
        if old and old['request'] != canonical(request):
            raise ValueError('Intenção existente não pode trocar chave ou payload')
        db.execute('INSERT OR IGNORE INTO operations VALUES(?,?,?,NULL)',
                   (request['intent'],canonical(request),'prepared'))


def record(path, intent, state, detail, receipt=None):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        # Um worker atrasado não apaga evidência confirmada por outro.
        old = db.execute('SELECT state FROM operations WHERE intent=?',(intent,)).fetchone()
        if old['state'] not in ('confirmed','rejected'):
            db.execute('UPDATE operations SET state=?,receipt=? WHERE intent=?',
                       (state,canonical(receipt) if receipt else None,intent))
        db.execute('INSERT INTO events(intent,state,detail) VALUES(?,?,?)',(intent,state,detail))
        db.commit()


def http_json(url, req=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, data=canonical(req).encode('utf8') if req else None,
                                     headers={'Content-Type':'application/json'})
    try:
        with opener.open(request,timeout=3) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def valid_receipt(req, reply):
    return (isinstance(reply,dict) and reply.get('effect') == 'applied'
            and reply.get('hash') == digest(req)
            and all(reply.get(k) == req[k] for k in ('principal','key','intent','action'))
            and isinstance(reply.get('reservation'),str) and bool(reply['reservation']))


def work(path, intent, url, recover=False, fault='none'):
    with connect(path) as db:
        row = db.execute('SELECT * FROM operations WHERE intent=?',(intent,)).fetchone()
    if row['state'] in ('confirmed','rejected'):
        return
    req = json.loads(row['request'])
    previous = row['state']
    record(path,intent,'unknown','before_network')
    if fault == 'before_send':
        os._exit(74)
    try:
        if recover or previous == 'unknown':
            query = urllib.parse.urlencode({'principal':req['principal'],'key':req['key']})
            code, reply = http_json(url+'/?'+query)
            if code != 404:
                if code == 200 and valid_receipt(req,reply):
                    record(path,intent,'confirmed','lookup_verified',reply)
                else:
                    record(path,intent,'unknown',f'lookup_{code}')
                return
            # 404 não prova ausência. Reenvio só usa a MESMA identidade sob
            # o contrato desta bancada: deduplicação atômica e prazo no destino.
        code, reply = http_json(url+'/',req)
        if fault == 'after_receive':
            os._exit(73)
        if code == 200 and valid_receipt(req,reply):
            record(path,intent,'confirmed','reply_verified',reply)
        elif code in (400,403,409) and reply.get('effect') == 'not_applied':
            record(path,intent,'rejected',reply['error'])
        else:
            record(path,intent,'unknown',f'unconfirmed_{code}')
    except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError) as exc:
        record(path,intent,'unknown',type(exc).__name__+': '+str(exc))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command',required=True)
    server = sub.add_parser('serve')
    server.add_argument('--db',required=True);server.add_argument('--ready',required=True)
    server.add_argument('--now',type=int,default=100)
    server.add_argument('--fault',default='none')
    server.add_argument('--lookup',choices=['yes','no','unavailable'],default='yes')
    server.add_argument('--legacy',action='store_true')
    worker = sub.add_parser('work')
    worker.add_argument('--db',required=True);worker.add_argument('--intent',required=True)
    worker.add_argument('--url',required=True);worker.add_argument('--recover',action='store_true')
    worker.add_argument('--fault',default='none');worker.add_argument('--barrier')
    args = parser.parse_args()
    if args.command == 'serve':
        serve(args)
    else:
        if args.barrier:
            import time
            Path(args.barrier+'.'+str(os.getpid())+'.ready').touch()
            limit = time.monotonic()+10
            while not Path(args.barrier).exists():
                if time.monotonic()>limit:raise TimeoutError('barrier')
                time.sleep(.01)
        work(args.db,args.intent,args.url,args.recover,args.fault)


if __name__ == '__main__':
    main()
