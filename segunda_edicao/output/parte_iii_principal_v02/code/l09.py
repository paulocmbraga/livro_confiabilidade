"""Destino SQLite/HTTP mutável e referência aritmética escrita separadamente."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import argparse,json,re,sqlite3,random
from laboratorios.parte_i.common import save,load

VARIANTS=('correct','rounding','duplicate','overdraft','conflict')

def cents(text,mode='correct'):
    if not isinstance(text,str) or not re.fullmatch(r'[0-9]{1,6}(?:\.[0-9]{1,3})?',text):
        raise ValueError('amount')
    value=Decimal(text)
    if value<=0:raise ValueError('amount')
    return int(value.quantize(Decimal('.01'),rounding=ROUND_HALF_EVEN if mode=='rounding' else ROUND_HALF_UP)*100)

def reference_cents(text):
    # Sem Decimal, float ou chamada ao conversor da implementação.
    if type(text) is not str or not re.fullmatch(r'[0-9]{1,6}(?:\.[0-9]{1,3})?',text):raise ValueError('amount')
    whole,_,fraction=text.partition('.');digits=(fraction+'000')[:3]
    thousandths=int(whole)*1000+int(digits)
    if thousandths<=0:raise ValueError('amount')
    return (thousandths+5)//10

def operations():
    rows=[('A','credit','1.005'),('A','credit','1.005'),('B','debit','0.105'),
          ('C','debit','20'),('A','credit','2'),('D','credit','-1'),
          ('E','credit','2.335'),('F','debit','1.235')]
    rng=random.Random(909)
    for n in range(32):
        rows.append((f'G{n//2}' if n%5==0 else f'R{n}',
                     rng.choice(['credit','debit']),rng.choice(['0.005','0.015','1.005','2.50','9.995'])))
    return [dict(id=k,op=op,amount=a) for k,op,a in rows]

class Reference:
    def __init__(self,shared_rounding=False):
        self.balance=0;self.seen={};self.shared_rounding=shared_rounding
    def apply(self,row):
        try:
            value=cents(row['amount'],'rounding') if self.shared_rounding else reference_cents(row['amount'])
            if row['op'] not in ('credit','debit') or not re.fullmatch('[A-Za-z0-9]+',row['id']):raise ValueError('operation')
        except (ValueError,KeyError,TypeError):return {'status':'invalid','balance':self.balance}
        key=row['id'];payload=(row['op'],row['amount'])
        if key in self.seen:
            previous,status=self.seen[key]
            return {'status':status if previous==payload else 'conflict','balance':self.balance}
        status='applied'
        if row['op']=='debit' and value>self.balance:status='insufficient'
        else:self.balance+=value if row['op']=='credit' else -value
        self.seen[key]=(payload,status)
        return {'status':status,'balance':self.balance}

class Ledger:
    def __init__(self,path,variant):
        if variant not in VARIANTS:raise ValueError('variant')
        self.variant=variant;self.db=sqlite3.connect(path)
        self.db.executescript('CREATE TABLE account(balance INTEGER NOT NULL); INSERT INTO account VALUES(0); CREATE TABLE receipt(id TEXT PRIMARY KEY,payload TEXT,status TEXT);')
    def balance(self):return self.db.execute('SELECT balance FROM account').fetchone()[0]
    def apply(self,row):
        try:
            value=cents(row['amount'],self.variant)
            if row['op'] not in ('credit','debit') or not re.fullmatch('[A-Za-z0-9]+',row['id']):raise ValueError('operation')
        except (KeyError,TypeError,ValueError):return {'status':'invalid','balance':self.balance()}
        payload=json.dumps([row['op'],row['amount']]);old=self.db.execute('SELECT payload,status FROM receipt WHERE id=?',(row['id'],)).fetchone()
        if old and self.variant!='duplicate':
            status=old[1] if old[0]==payload or self.variant=='conflict' else 'conflict'
            return {'status':status,'balance':self.balance()}
        balance=self.balance();status='applied'
        if row['op']=='debit' and value>balance and self.variant!='overdraft':status='insufficient'
        else:balance+=value if row['op']=='credit' else -value
        with self.db:
            self.db.execute('UPDATE account SET balance=?',(balance,))
            self.db.execute('INSERT OR REPLACE INTO receipt VALUES(?,?,?)',(row['id'],payload,status))
        return {'status':status,'balance':balance}

def analyze(rows,shared_rounding=False):
    ref=Reference(shared_rounding);failures=[];unknown=[]
    for i,row in enumerate(rows):
        expected=ref.apply(row['request'])
        if row.get('observed') is None:unknown.append(i)
        elif row['observed']!=expected or row['state']['balance']!=expected['balance']:failures.append(i)
    return {'failures':failures,'unknown':unknown,'decision':'fail' if failures else 'inconclusive' if unknown else 'pass'}

def serve(folder,variant):
    ledger=Ledger(folder/'ledger.sqlite',variant)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,value):
            data=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):self.send({'balance':ledger.balance()})
        def do_POST(self):
            row=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.send(ledger.apply(row))
    server=HTTPServer(('127.0.0.1',0),Handler)
    save(folder/'ready.json',{'port':server.server_port});server.serve_forever()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',type=Path,required=True);p.add_argument('--variant',choices=VARIANTS,required=True);a=p.parse_args();serve(a.folder,a.variant)
