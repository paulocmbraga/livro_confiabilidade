"""Fatorial em HTTP local, mais simulação de interferência identificada."""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import argparse,json,os,random,time,urllib.request
from statistics import mean
from laboratorios.parte_i.common import load,save


def cases():
    result=[]
    for i in range(40):
        kind=i%4
        revision=[2,1,1,1][kind];current=[2,2,1,1][kind];amount=-1 if kind==3 else 25
        result.append({'id':f'F{i:02}','kind':['current','obsolete','stable','negative'][kind],
            'proposal_revision':revision,'cached_revision':1,'current_revision':current,
            'amount':amount})
    return result


def decision(case, refresh, validate):
    reference=case['current_revision'] if refresh else case['cached_revision']
    allowed=not validate or (case['proposal_revision']==reference and case['amount']>0)
    return {'allowed':allowed,'reference_used':reference}


def plan_requests(rows,seed):
    rng=random.Random(seed);jobs=[];order=list(rows);rng.shuffle(order)
    for c in order:
        factors=[(0,0),(0,1),(1,0),(1,1)];rng.shuffle(factors)
        for a,b in factors:jobs.append({'case':c['id'],'refresh':a,'validate':b,
                                       'id':f"{c['id']}-{a}{b}"})
    return jobs


def serve(root,ready):
    root=Path(root);catalog={c['id']:c for c in load(root/'cases.json')};seen=set()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            status=200
            try:
                job=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if set(job)!={'id','case','refresh','validate'}:raise ValueError('shape')
                if job['id'] in seen:raise ValueError('duplicate')
                if any(type(job[k]) is not int or job[k] not in (0,1) for k in ('refresh','validate')):raise ValueError('factor')
                start=time.perf_counter_ns();raw=decision(catalog[job['case']],job['refresh'],job['validate'])
                response={'id':job['id'],**raw,'pid':os.getpid(),'server_ns':time.perf_counter_ns()-start}
                save(root/'audit'/(job['id']+'.json'),{'request':job,'response':response});seen.add(job['id'])
            except (KeyError,ValueError,TypeError) as exc:status=400;response={'error':str(exc)}
            body=json.dumps(response).encode();self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
    server=HTTPServer(('127.0.0.1',0),Handler)
    save(ready,{'pid':os.getpid(),'port':server.server_port,'scope':'loopback factorial fixture service'})
    try:server.serve_forever()
    finally:server.server_close()


def request(url,job):
    req=urllib.request.Request(url,data=json.dumps(job).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=5) as r:return r.status,json.loads(r.read())


def analyze(rows,observations):
    index={c['id']:c for c in rows};cells={f'{a}{b}':[] for a in (0,1) for b in (0,1)}
    seen=set()
    for o in observations:
        job=o['request'];key=job['id']
        if key in seen:raise ValueError('Requisição duplicada')
        seen.add(key);c=index[job['case']]
        oracle=c['proposal_revision']==c['current_revision'] and c['amount']>0
        cells[f"{job['refresh']}{job['validate']}"].append(int(o['response']['allowed']==oracle))
    if seen!={j['id'] for j in plan_requests(rows,0)}:raise ValueError('Fatorial incompleto')
    means={k:mean(v) for k,v in cells.items()}
    return {'cells':{k:{'n':len(v),'correct':sum(v),'mean':means[k]} for k,v in cells.items()},
        'refresh_at_validate0':means['10']-means['00'],
        'refresh_at_validate1':means['11']-means['01'],
        'interaction_difference_of_differences':means['11']-means['10']-means['01']+means['00'],
        'scope':'Controlled synthetic cases on an actual local service; no user benefit measured'}


def exposure(seed=803,groups=40,users=8):
    rng=random.Random(seed);out={}
    for unit in ('individual','group'):
        rows=[];group_z=[0]*(groups//2)+[1]*(groups-groups//2);rng.shuffle(group_z)
        individual_z=[0]*(groups*users//2)+[1]*(groups*users-groups*users//2);rng.shuffle(individual_z)
        for g in range(groups):
            zs=individual_z[g*users:(g+1)*users] if unit=='individual' else [group_z[g]]*users
            saturation=mean(zs)
            for u,z in enumerate(zs):
                peer=(sum(zs)-z)/(users-1)
                rows.append({'group':g,'user':u,'z':z,'saturation':saturation,
                    'peer_exposure':peer,'y':1+.2*z+.3*peer})
        diff=mean(r['y'] for r in rows if r['z'])-mean(r['y'] for r in rows if not r['z'])
        out[unit]={'rows':rows,'difference':diff,'treated':sum(r['z'] for r in rows),
                   'all_treated_vs_none_effect':.5,'direct_effect_holding_peer_exposure':.2}
    return out


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True)
    p.add_argument('--ready',type=Path,required=True);a=p.parse_args();serve(a.root,a.ready)
