"""Processos filhos da bancada: produtor, consumidor e despachante."""
import argparse,json,time
from pathlib import Path
from .core import *

def run(a):
    cfg=load(a.config);out=a.out;out.mkdir(parents=True,exist_ok=True);r=broker(cfg)
    if a.role=='producer':
        rows=[]
        for intent in ['A1','A2','A3','B1','B2','P','C','A1','X','Y']:
            kind='poison' if intent=='P' else 'cancel' if intent=='C' else 'normal'
            mid=r.eval(ADMIT,1,'work',8,intent,kind,time.time())
            rows.append(dict(intent=intent,kind=kind,message_id=mid,admitted=bool(mid)))
        save(out/'result.json',rows);return
    if a.role=='consumer':
        rows=[];limit=time.monotonic()+15
        while time.monotonic()<limit:
            claimed=r.xautoclaim('work','g',a.name,150,'0-0',count=1)[1]
            if claimed:messages=claimed;source='claim'
            else:
                values=r.xreadgroup('g',a.name,{'work':'>'},count=1,block=100)
                messages=values[0][1] if values else [];source='new'
            if not messages:
                if r.xlen('work')==0:break
                continue
            mid,body=messages[0];intent=body['intent'];outcome='cancelled'
            deliveries=r.xpending_range('work','g',mid,mid,1)[0]['times_delivered']
            if body['kind']=='poison':
                if deliveries>=3:
                    r.eval(DEAD,2,'work','dead','g',mid,intent);outcome='dead_letter'
                else:outcome='retry_pending'
            else:
                if body['kind']=='normal':outcome=effect(cfg,intent)
                if a.crash:
                    save(out/'after_effect.json',dict(intent=intent,message_id=mid,outcome=outcome))
                    while True:time.sleep(.05)
                r.eval(ACK,1,'work','g',mid)
            rows.append(dict(intent=intent,message_id=mid,source=source,deliveries=deliveries,
                outcome=outcome,age_ms=1000*(time.time()-float(body['at']))))
        save(out/'result.json',rows);return
    if a.role=='dispatch':
        with connect(cfg) as c:rows=c.execute('SELECT id FROM outbox WHERE NOT sent ORDER BY id').fetchall()
        actions=[]
        for row in rows:
            intent=row['id'];outcome=accept_event(cfg,intent)
            actions.append(dict(intent=intent,outcome=outcome))
            if a.crash:
                save(out/'after_effect.json',actions)
                while True:time.sleep(.05)
            with connect(cfg) as c:
                c.execute('UPDATE outbox SET sent=true WHERE id=%s',(intent,))
                c.execute("UPDATE jobs SET status='confirmed' WHERE id=%s",(intent,))
        save(out/'result.json',actions);return
    if a.role=='stale':
        save(out/'paused.json',dict(token=1))
        wait(lambda:(out/'resume.json').exists(),20)
        save(out/'result.json',dict(outcome=fenced_write(cfg,1,'old',not a.unsafe)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('role',choices=['producer','consumer','dispatch','stale'])
    p.add_argument('--config',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--name',default='consumer');p.add_argument('--crash',action='store_true')
    p.add_argument('--unsafe',action='store_true');run(p.parse_args())
