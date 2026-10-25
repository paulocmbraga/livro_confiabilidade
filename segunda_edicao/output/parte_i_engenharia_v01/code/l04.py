"""Journal append-only e workers reais; efeitos se limitam a artefatos locais."""
from pathlib import Path
import argparse, json, os, sqlite3, time
from .common import load, save, sha, digest

def connect(db):
    c=sqlite3.connect(db,timeout=10);c.execute('PRAGMA foreign_keys=ON');return c

def initialize(db, plan):
    with connect(db) as c:
        c.executescript('''
        CREATE TABLE cases(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE attempts(id TEXT PRIMARY KEY, case_id TEXT REFERENCES cases(id),
                              number INTEGER, admitted REAL, UNIQUE(case_id,number));
        CREATE TABLE results(attempt_id TEXT PRIMARY KEY REFERENCES attempts(id),
                             state TEXT NOT NULL, raw TEXT, sha256 TEXT, ended REAL);
        CREATE TABLE events(seq INTEGER PRIMARY KEY, kind TEXT, attempt_id TEXT, at REAL);
        ''')
        c.executemany('INSERT INTO cases VALUES (?,?)',
                      [(x['id'],json.dumps(x,sort_keys=True)) for x in plan['cases']])

def admit(db,case,number):
    ident=f'{case}-a{number}';now=time.time()
    with connect(db) as c:
        c.execute('INSERT INTO attempts VALUES (?,?,?,?)',(ident,case,number,now))
        c.execute('INSERT INTO events(kind,attempt_id,at) VALUES (?,?,?)',('admit',ident,now))
    return ident

def conclude(db,attempt,state,raw=None,hash_value=None):
    if state not in ('success','failed','interrupted'):raise ValueError(state)
    with connect(db) as c:
        c.execute('INSERT INTO results VALUES (?,?,?,?,?)',
                  (attempt,state,raw,hash_value,time.time()))
        c.execute('INSERT INTO events(kind,attempt_id,at) VALUES (?,?,?)',('end',attempt,time.time()))

def snapshot(db):
    with connect(db) as c:
        c.row_factory=sqlite3.Row
        return {name:[dict(x) for x in c.execute('SELECT * FROM '+name+(' ORDER BY seq' if name=='events' else ' ORDER BY 1'))]
                for name in ('cases','attempts','results','events')}

def reconcile(data,root,require_complete=True):
    cases={x['id']:json.loads(x['payload']) for x in data['cases']}
    attempts={x['id']:x for x in data['attempts']}; results={x['attempt_id']:x for x in data['results']}
    if len(cases)!=len(data['cases']) or len(attempts)!=len(data['attempts']) or len(results)!=len(data['results']):
        raise ValueError('Identidade repetida')
    if set(results)-set(attempts):raise ValueError('Resultado sem admissão')
    per_case={k:[] for k in cases};pending=0;ended={'success':0,'failed':0,'interrupted':0}
    for aid,a in attempts.items():
        if a['case_id'] not in cases:raise ValueError('Caso ausente')
        per_case[a['case_id']].append(a)
        r=results.get(aid)
        if not r:pending+=1;continue
        if r['state'] not in ended:raise ValueError('Estado inválido')
        if r['ended']<a['admitted']:raise ValueError('Fim anterior à admissão')
        ended[r['state']]+=1
        if r['state']!='interrupted':
            path=(Path(root)/r['raw']).resolve()
            if not path.is_relative_to(Path(root).resolve()) or sha(path)!=r['sha256']:
                raise ValueError('Saída bruta ausente ou adulterada')
            raw=load(path);case=cases[a['case_id']]
            if raw['attempt']!=aid or raw['case']!=a['case_id']:raise ValueError('Saída trocada')
            if raw['input_hash']!=digest(case):raise ValueError('Entrada trocada')
            expected='success' if type(case['x']) is int else 'failed'
            if r['state']!=expected or raw['state']!=expected:raise ValueError('Oráculo de cálculo divergente')
            if expected=='success' and raw['value']!=case['x']**2:raise ValueError('Quadrado incorreto')
    task_counts={'success':0,'failed':0,'pending':0}
    for cid,aa in per_case.items():
        numbers=sorted(a['number'] for a in aa)
        if numbers!=list(range(1,len(aa)+1)):raise ValueError('Sequência de tentativas incompleta')
        terminal=[results[a['id']]['state'] for a in aa
                  if a['id'] in results and results[a['id']]['state']!='interrupted']
        if len(terminal)>1:raise ValueError('Mais de uma conclusão por caso')
        task_counts[terminal[0] if terminal else 'pending']+=1
    # O journal também precisa explicar as transições; rehash não basta.
    events=data['events']
    if [e['seq'] for e in events]!=list(range(1,len(events)+1)):raise ValueError('Lacuna no journal')
    for aid in attempts:
        kinds=[e['kind'] for e in events if e['attempt_id']==aid]
        if kinds!=(['admit','end'] if aid in results else ['admit']):raise ValueError('História incoerente')
    if any(e['attempt_id'] not in attempts for e in events):raise ValueError('Evento sem tentativa')
    complete=not pending and not task_counts['pending']
    if require_complete and not complete:raise ValueError('Campanha incompleta')
    return {'admitted_cases':len(cases),'attempts':len(attempts),'tasks':task_counts,
            'attempt_states':{**ended,'pending':pending},'complete':complete}

def worker(args):
    folder=args.folder;case=load(args.case);start=time.time()
    save(folder/'ready.json',{'pid':os.getpid(),'started':start})
    deadline=time.monotonic()+30
    while not (folder/'release.json').exists():
        if time.monotonic()>deadline:raise TimeoutError('Barreira inicial')
        time.sleep(.01)
    state='success' if type(case['x']) is int else 'failed'
    raw={'case':case['id'],'attempt':args.attempt,'input_hash':digest(case),
         'state':state,'value':case['x']**2 if state=='success' else None,
         'error':None if state=='success' else 'x_not_integer','pid':os.getpid(),
         'started':start,'finished_computation':time.time()}
    save(folder/'raw.json',raw)
    if args.after_raw:
        save(folder/'after_raw.json',{'pid':os.getpid()})
        while not (folder/'publish.json').exists():
            if time.monotonic()>deadline:raise TimeoutError('Barreira de publicação')
            time.sleep(.01)
    rel=(folder/'raw.json').relative_to(args.root).as_posix()
    conclude(args.db,args.attempt,state,rel,sha(folder/'raw.json'))

def main():
    p=argparse.ArgumentParser();p.add_argument('role',choices=['worker','observe'])
    p.add_argument('--db',type=Path,required=True);p.add_argument('--root',type=Path)
    p.add_argument('--folder',type=Path);p.add_argument('--case',type=Path)
    p.add_argument('--attempt');p.add_argument('--after-raw',action='store_true')
    p.add_argument('--out',type=Path);a=p.parse_args()
    if a.role=='worker':worker(a)
    else:save(a.out,{'observer_pid':os.getpid(),'observed':time.time(),'data':snapshot(a.db)})

if __name__=='__main__':main()
