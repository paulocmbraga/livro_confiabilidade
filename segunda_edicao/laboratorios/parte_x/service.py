"""Serviços HTTP de bancada. Loopback, SQLite e falhas reais de processo.

As capacidades fixas são identidades de ensaio, não autenticação de produção.
"""
from contextlib import closing
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import argparse,json,os,sqlite3,threading,time,urllib.request,urllib.error
from .core import load,save,predict,digest


def request(url,data=None,timeout=5):
    req=urllib.request.Request(url,data=json.dumps(data or {}).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:return r.status,json.loads(r.read())
    except urllib.error.HTTPError as e:return e.code,json.loads(e.read())


class Store:
    def __init__(self,path):
        self.path=path
        with closing(sqlite3.connect(path)) as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS cfg(k TEXT PRIMARY KEY,v TEXT NOT NULL);
              INSERT OR IGNORE INTO cfg VALUES('mode','auto'),('stage','live'),('retest','no');
              CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,amount INTEGER NOT NULL,
                schema INTEGER NOT NULL,state TEXT NOT NULL,priority INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS effects(id TEXT PRIMARY KEY,amount INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY,event TEXT,detail TEXT);
            ''');db.commit()

    def call(self,path,data):
        with closing(sqlite3.connect(self.path,timeout=5)) as db:
            db.row_factory=sqlite3.Row;db.execute('BEGIN IMMEDIATE')
            try:
                status,body=self._call(db,path,data)
                db.execute('INSERT INTO audit(event,detail) VALUES(?,?)',(path,json.dumps({'request':data,'status':status,'body':body},sort_keys=True)))
                db.commit();return status,body
            except Exception:db.rollback();raise

    def _call(self,db,path,d):
        cfg=dict(db.execute('SELECT k,v FROM cfg').fetchall())
        def update(k,v):db.execute('UPDATE cfg SET v=? WHERE k=?',(v,k))
        def count(state):return db.execute('SELECT count(*) FROM tasks WHERE state=?',(state,)).fetchone()[0]
        if path=='/state':
            return 200,dict(config=cfg,tasks=[dict(r) for r in db.execute('SELECT * FROM tasks ORDER BY id')],
                effects=[dict(r) for r in db.execute('SELECT * FROM effects ORDER BY id')])
        if path=='/admit':
            if cfg['stage']!='live':return 503,{'reason':'draining_or_archived'}
            if type(d.get('amount')) is not int or d['amount']<0:return 400,{'reason':'integer_cents_required'}
            old=db.execute('SELECT * FROM tasks WHERE id=?',(d['id'],)).fetchone()
            if old:return (200,dict(old)) if old['amount']==d['amount'] else (409,{'reason':'identity_conflict'})
            state='pending' if cfg['mode']=='auto' else 'review'
            if state=='review' and count('review')>=3:return 429,{'reason':'review_capacity'}
            db.execute('INSERT INTO tasks VALUES(?,?,1,?,?)',(d['id'],d['amount'],state,d.get('priority',0)))
            return 201,{'id':d['id'],'state':state}
        if path=='/effect':
            if d.get('capability')!='active':return 403,{'reason':'shadow_has_no_write_capability'}
            if cfg['stage']=='archived' or cfg['mode']!='auto':return 423,{'reason':'autonomy_disabled'}
            row=db.execute('SELECT * FROM tasks WHERE id=?',(d['id'],)).fetchone()
            if not row or row['schema']!=1:return 409,{'reason':'missing_or_incompatible_task'}
            old=db.execute('SELECT * FROM effects WHERE id=?',(d['id'],)).fetchone()
            if old:return 200,dict(old)
            if row['state']!='pending':return 409,{'reason':'not_pending'}
            db.execute('INSERT INTO effects VALUES(?,?)',(row['id'],row['amount']))
            # O recibo existe antes de o cliente confirmar a conclusão da tarefa.
            return 201,{'id':row['id'],'amount':row['amount']}
        if path=='/resolve':
            row=db.execute('SELECT * FROM tasks WHERE id=?',(d['id'],)).fetchone()
            if not row:return 404,{'reason':'missing'}
            effect=db.execute('SELECT * FROM effects WHERE id=?',(d['id'],)).fetchone()
            terminal='done' if effect else 'cancelled'
            if effect and d.get('decision')=='cancel':return 409,{'reason':'effect_exists'}
            if not effect and d.get('decision')!='cancel':return 409,{'reason':'receipt_missing'}
            db.execute('UPDATE tasks SET state=? WHERE id=?',(terminal,d['id']))
            return 200,{'state':terminal,'evidence':'destination_receipt' if effect else d.get('reason','explicit_cancellation')}
        if path=='/mode':
            if d['mode'] not in ('auto','hold'):return 400,{'reason':'invalid_mode'}
            if d['mode']=='auto' and (count('pending') or count('review') or cfg['retest']!='yes' or cfg['stage']!='live'):
                return 409,{'reason':'return_gate'}
            update('mode',d['mode']);return 200,{'mode':d['mode']}
        if path=='/retest':
            # O chamador da bancada fornece a conclusão; não é um verificador remoto.
            update('retest','yes' if d['passed'] else 'no');return 200,{'accepted':True}
        if path=='/next_review':
            row=db.execute("SELECT * FROM tasks WHERE state='review' ORDER BY priority DESC,id LIMIT 1").fetchone()
            return 200,dict(row) if row else {}
        if path=='/migrate':
            if count('pending') or count('review'):return 409,{'reason':'open_tasks'}
            db.execute('UPDATE tasks SET schema=2');return 200,{'schema':2,'amount_unit':'integer_cents_preserved'}
        if path=='/read':
            row=db.execute('SELECT * FROM tasks WHERE id=?',(d['id'],)).fetchone()
            if not row:return 404,{'reason':'missing'}
            if row['schema'] not in d['supported']:return 409,{'reason':'incompatible_reader'}
            return 200,dict(row)
        if path=='/drain':
            if cfg['stage']=='archived':return 409,{'reason':'already_archived'}
            update('stage','draining');return 200,{'stage':'draining'}
        if path=='/archive':
            if cfg['stage']!='draining' or count('pending') or count('review') or not d.get('dependencies_closed'):
                return 409,{'reason':'obligations_open'}
            update('stage','archived');update('mode','hold');return 200,{'stage':'archived','receipts':'readable'}
        return 404,{'reason':'unknown_path'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--role',choices=['store','model'],required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--db',type=Path)
    p.add_argument('--model',type=Path);p.add_argument('--destination');p.add_argument('--shadow',action='store_true');a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=False)
    store=Store(a.db) if a.role=='store' else None;model=load(a.model) if a.model else None
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            d=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
            if self.path=='/stop':
                status,body=200,{'stopped':True};threading.Thread(target=self.server.shutdown,daemon=True).start()
            elif store:status,body=store.call(self.path,d)
            elif self.path=='/predict':status,body=200,{'prediction':predict(model,d['x']),'model_sha256':digest(model)}
            elif self.path=='/effect':
                status,body=request(a.destination+'/effect',{'id':d['id'],'capability':'shadow' if a.shadow else 'active'})
                if d.get('crash_after_receipt') and status in (200,201):
                    save(a.out/'committed_before_crash.json',dict(status=status,body=body,wall_epoch=time.time()))
                    os._exit(23)
            else:status,body=404,{'reason':'unknown_path'}
            content=json.dumps(body).encode();self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(content)))
            self.end_headers();self.wfile.write(content)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    save(a.out/'ready.json',dict(url=f'http://127.0.0.1:{server.server_port}',pid=os.getpid(),role=a.role,model=model))
    server.serve_forever(poll_interval=.02);server.server_close()
if __name__=='__main__':main()
