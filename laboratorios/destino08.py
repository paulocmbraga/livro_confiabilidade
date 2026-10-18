"""Destino persistente de L08. Cada chamada roda em processo separado via JSON/stdin."""
import json
from contextlib import closing
import sqlite3
import sys
from pathlib import Path


def initialize(path,scenario):
    if Path(path).exists():raise FileExistsError(path)
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript('''CREATE TABLE config (scenario TEXT);
        CREATE TABLE stock (sku TEXT PRIMARY KEY, quantity INTEGER);
        CREATE TABLE approvals (principal TEXT, sku TEXT, quantity INTEGER, granted INTEGER);
        CREATE TABLE reservations (intent TEXT PRIMARY KEY, principal TEXT, sku TEXT, quantity INTEGER);
        CREATE TABLE tickets (id TEXT PRIMARY KEY, closed INTEGER);
        CREATE TABLE events (id INTEGER PRIMARY KEY, operation TEXT, principal TEXT, status TEXT);''')
        db.execute('INSERT INTO config VALUES (?)',(scenario,))
        db.execute('INSERT INTO stock VALUES (?,?)',('P1',0 if scenario=='sem_estoque' else 2))
        db.execute('INSERT INTO approvals VALUES (?,?,?,?)',('ana','P1',1,int(scenario!='negada')))
        db.execute('INSERT INTO tickets VALUES (?,?)',('C1',0))


def handle(path,request):
    with closing(sqlite3.connect(path)) as db, db:
        db.row_factory=sqlite3.Row
        scenario=db.execute('SELECT scenario FROM config').fetchone()[0]
        op=request['operation']; principal=request.get('principal','ana')
        if op=='snapshot':
            return dict(available=scenario!='sem_observacao',
                reservations=[dict(r) for r in db.execute('SELECT * FROM reservations')],
                tickets=[dict(r) for r in db.execute('SELECT * FROM tickets')],
                stock=[dict(r) for r in db.execute('SELECT * FROM stock')],
                events=[dict(r) for r in db.execute('SELECT * FROM events')])
        if op=='stock':
            result=dict(status='retry' if scenario=='ciclo' else 'ok',
                        quantity=db.execute('SELECT quantity FROM stock').fetchone()[0])
        elif op=='approval':
            row=db.execute('SELECT granted FROM approvals WHERE principal=? AND sku=? AND quantity=?',
                           (principal,'P1',1)).fetchone()
            result=dict(status='ok' if row and row[0] else 'denied')
        elif op=='reserve':
            sku=request.get('sku');quantity=request.get('quantity');intent=request.get('intent')
            row=db.execute('SELECT granted FROM approvals WHERE principal=? AND sku=? AND quantity=?',
                           (principal,sku,quantity)).fetchone()
            valid=type(quantity) is int and quantity>0 and sku=='P1' and intent=='I1'
            if not valid or not row or not row[0]:result=dict(status='denied')
            elif db.execute('SELECT 1 FROM reservations WHERE intent=?',(intent,)).fetchone():
                result=dict(status='ok',receipt=intent)
            elif scenario=='sucesso_falso':result=dict(status='ok',receipt='fantasma')
            elif db.execute('SELECT quantity FROM stock WHERE sku=?',(sku,)).fetchone()[0]<quantity:
                result=dict(status='empty')
            else:
                db.execute('UPDATE stock SET quantity=quantity-? WHERE sku=?',(quantity,sku))
                db.execute('INSERT INTO reservations VALUES (?,?,?,?)',(intent,principal,sku,quantity))
                result=dict(status='unknown' if scenario in ('resposta_perdida','sem_observacao') else 'ok',receipt=intent)
        elif op=='receipt':
            row=db.execute('SELECT * FROM reservations WHERE intent=?',(request.get('intent'),)).fetchone()
            result=(dict(status='unavailable') if scenario=='sem_observacao'
                    else dict(status='ok',receipt=dict(row)) if row else dict(status='absent'))
        elif op=='close':
            row=db.execute('SELECT * FROM reservations WHERE intent=?',('I1',)).fetchone()
            if row and row['principal']==principal:
                db.execute('UPDATE tickets SET closed=1 WHERE id=?',('C1',));result=dict(status='ok')
            else:result=dict(status='blocked')
        else:raise ValueError('Operação desconhecida')
        db.execute('INSERT INTO events(operation,principal,status) VALUES (?,?,?)',(op,principal,result['status']))
        return result


if __name__=='__main__':
    print(json.dumps(handle(sys.argv[1],json.load(sys.stdin)),ensure_ascii=False))
