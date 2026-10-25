"""Versioned derived memory, real SQLite commits and a fresh process per command."""
import argparse,json,os,sqlite3
from pathlib import Path

class Memory:
    def __init__(self,path):
        self.db=sqlite3.connect(path)
        self.db.executescript('''CREATE TABLE IF NOT EXISTS facts (
          tenant TEXT, key TEXT, value TEXT, epoch INTEGER, deleted INTEGER,
          PRIMARY KEY(tenant,key));
          CREATE TABLE IF NOT EXISTS summaries (
          tenant TEXT, key TEXT, value TEXT, epoch INTEGER,
          PRIMARY KEY(tenant,key));''')
    def close(self):self.db.close()
    def run(self,actor,tenant,key,action,value=None,unsafe=False):
        if actor!=tenant:raise PermissionError('tenant mismatch')
        row=self.db.execute('SELECT value,epoch,deleted FROM facts WHERE tenant=? AND key=?',(tenant,key)).fetchone()
        if action in ('put','delete'):
            epoch=1 if row is None else row[1]+1
            self.db.execute('INSERT OR REPLACE INTO facts VALUES (?,?,?,?,?)',
                (tenant,key,value if action=='put' else '',epoch,int(action=='delete')))
            self.db.commit();return {'epoch':epoch,'deleted':action=='delete'}
        if action=='summarize':
            if row is None or row[2]:raise ValueError('no live fact')
            self.db.execute('INSERT OR REPLACE INTO summaries VALUES (?,?,?,?)',
                            (tenant,key,value,row[1]));self.db.commit();return {'epoch':row[1]}
        if action=='read':
            return {'value':None if row is None or row[2] else row[0],
                    'epoch':row[1] if row else None}
        if action=='summary':
            cached=self.db.execute('SELECT value,epoch FROM summaries WHERE tenant=? AND key=?',(tenant,key)).fetchone()
            valid=bool(row and not row[2] and cached and row[1]==cached[1])
            return {'value':cached[0] if cached and (valid or unsafe) else None,
                    'valid':valid,'unsafe':unsafe}
        raise ValueError('action')

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--request',type=Path,required=True)
    a=p.parse_args();m=Memory(a.db)
    try:
        request=json.loads(a.request.read_text(encoding='utf-8'))
        try:result={'ok':True,'result':m.run(**request)}
        except (PermissionError,ValueError) as e:result={'ok':False,'error':str(e)}
        print(json.dumps(dict(result,pid=os.getpid()),ensure_ascii=False))
    finally:m.close()
if __name__=='__main__':main()
