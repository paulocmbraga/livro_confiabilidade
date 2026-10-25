"""Destino HTTP/SQLite da bancada L25; observador lê arquivo por outra conexão."""
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import argparse,json,sqlite3
from contextlib import closing
from laboratorios.parte_i.common import load,save
from .core import admissible

def init(db,task):
    with closing(sqlite3.connect(db)) as c, c:
        c.executescript('CREATE TABLE state(id INTEGER PRIMARY KEY,body TEXT); CREATE TABLE effect(intent TEXT PRIMARY KEY,body TEXT); CREATE TABLE audit(n INTEGER PRIMARY KEY,body TEXT);')
        c.execute('INSERT INTO state VALUES(1,?)',(json.dumps({'version':0,'stock':task['stock'],'prices':task['prices'],'reads':0}),))
        if task.get('already'):
            state=json.loads(c.execute('SELECT body FROM state').fetchone()[0]);item=task['allowed'][0]
            e={'intent':task['id'],'item':item,'quantity':task['quantity'],'amount':task['quantity']*task['prices'][item]}
            c.execute('INSERT INTO effect VALUES(?,?)',(task['id'],json.dumps(e)));state['stock'][item]-=task['quantity'];state['version']+=1
            c.execute('UPDATE state SET body=?',(json.dumps(state),))

def inspect(db):
    with closing(sqlite3.connect(db)) as c, c:
        s=json.loads(c.execute('SELECT body FROM state').fetchone()[0]);effects=[json.loads(r[0]) for r in c.execute('SELECT body FROM effect')]
        audit=[json.loads(r[0]) for r in c.execute('SELECT body FROM audit ORDER BY n')]
    return dict(s,effects=effects,audit=audit)

def act(db,task,p):
    if not isinstance(p,dict):raise ValueError("object_required")
    with closing(sqlite3.connect(db,timeout=5)) as c, c:
        c.execute('BEGIN IMMEDIATE');s=json.loads(c.execute('SELECT body FROM state').fetchone()[0])
        receipt=c.execute('SELECT body FROM effect WHERE intent=?',(task['id'],)).fetchone()
        if receipt:result={'receipt':json.loads(receipt[0]),'version':s['version'],'cached':True}
        elif p.get('action')=='inspect':
            result={k:s[k] for k in ['version','stock','prices']};result=json.loads(json.dumps(result));s['reads']+=1
            if task.get('change_after_read') and s['reads']==1:s['stock']['A']=0;s['version']+=1
        else:
            error=admissible(task,s,p,s['reads']>0)
            if error:result={'error':error,'version':s['version']}
            elif p['action']=='reserve':
                item=p['item'];effect={'intent':task['id'],'item':item,'quantity':p['quantity'],'amount':p['quantity']*s['prices'][item]}
                c.execute('INSERT INTO effect VALUES(?,?)',(task['id'],json.dumps(effect)));s['stock'][item]-=p['quantity'];s['version']+=1
                result={'receipt':effect,'version':s['version'],'cached':False}
            else:result={'terminal':p['action'],'version':s['version']}
        c.execute('UPDATE state SET body=?',(json.dumps(s),));c.execute('INSERT INTO audit(body) VALUES(?)',(json.dumps({'proposal':p,'response':result}),));return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path);p.add_argument('--task',type=Path);p.add_argument('--ready',type=Path);a=p.parse_args();task=load(a.task);init(a.db,task)
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                n=int(self.headers.get('Content-Length','0'))
                if n>20000:raise ValueError('body')
                result=act(a.db,task,json.loads(self.rfile.read(n)));code=200
            except (ValueError,KeyError,TypeError) as e:result={'error':type(e).__name__};code=400
            data=json.dumps(result).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);save(a.ready,{'url':f'http://127.0.0.1:{server.server_port}'});server.serve_forever()

if __name__=='__main__':main()
