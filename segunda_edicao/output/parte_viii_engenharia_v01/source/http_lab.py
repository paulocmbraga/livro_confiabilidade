"""HTTP real; relógio monotônico compartilhado apenas neste host."""
import argparse,http.client,json,socket,threading,time,urllib.request,urllib.error
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from .core import save,load,jitter,remaining
from laboratorios.parte_i.common import child,wait_file

def serve(out):
    state={};lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def reply(self,status,data,headers=None):
            raw=json.dumps(data).encode();self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            for k,v in (headers or {}).items():self.send_header(k,v)
            self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        def do_GET(self):
            with lock:copy=json.loads(json.dumps(state))
            self.reply(200,copy)
        def do_POST(self):
            b=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            case=b['case'];fault=b['fault'];now=time.monotonic()
            with lock:
                s=state.setdefault(case,dict(calls=0,effects=[],events=[]))
                s['calls']+=1;n=s['calls'];s['events'].append(dict(n=n,at=now,fault=fault))
            if b.get('deadline',float('inf'))<=now:
                self.reply(408,dict(error='expired'));return
            if fault=='always503' or (fault=='transient503' and n<=2):
                self.reply(503,dict(error='unavailable'));return
            if fault=='rate' and n<=2:
                self.reply(429,dict(error='limited'),{'Retry-After':'0.04'});return
            if fault=='reject':self.reply(400,dict(error='contract'));return
            if fault!='read':
                with lock:
                    if b['intent'] not in s['effects']:s['effects'].append(b['intent'])
            if fault in ('delay_after','read'):time.sleep(.11 if n==1 else .01)
            if fault=='drop_after' and n==1:
                self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            self.reply(200,dict(receipt=b['intent'],at=time.monotonic()))
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    save(out/'ready.json',dict(port=server.server_port));server.serve_forever()

def call(url,body,timeout):
    start=time.monotonic()
    req=urllib.request.Request(url,json.dumps(body).encode(),{'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            data=json.load(r);return dict(status=r.status,data=data,elapsed=time.monotonic()-start,retry_after=0)
    except urllib.error.HTTPError as e:
        return dict(status=e.code,data=json.loads(e.read()),elapsed=time.monotonic()-start,
                    retry_after=float(e.headers.get('Retry-After',0)))
    except (TimeoutError,OSError,http.client.RemoteDisconnected) as e:
        return dict(status=0,error=type(e).__name__,elapsed=time.monotonic()-start,retry_after=0)

def run(out):
    out.mkdir();results=[]
    with child('laboratorios.parte_viii.http_lab',['server','--out',out],out/'server') as proc:
        wait_file(out/'ready.json',proc);url='http://127.0.0.1:'+str(load(out/'ready.json')['port'])
        for policy in ['layered','budget']:
            for fault in ['always503','transient503','rate','reject','drop_after','delay_after']:
                case=policy+'_'+fault;started=time.monotonic();deadline=started+.35;attempts=[]
                def once():
                    body=dict(case=case,fault=fault,intent=case)
                    if policy=='budget':body['deadline']=deadline
                    response=call(url,body,.06 if policy=='layered' else min(.06,remaining(deadline,time.monotonic())))
                    attempts.append(response);return response
                def nested(depth):
                    for i in range(3):
                        result=once() if depth==0 else nested(depth-1)
                        if result['status']==200:return result
                    return result
                if policy=='layered':last=nested(2)
                else:
                    for i in range(3):
                        if remaining(deadline,time.monotonic(),.005)<=0:break
                        last=once()
                        if last['status'] not in (0,429,500,502,503,504):break
                        if i<2:
                            delay=max(last['retry_after'],jitter(i,29))
                            if delay+.005>=remaining(deadline,time.monotonic()):break
                            time.sleep(delay)
                results.append(dict(case=case,policy=policy,fault=fault,attempts=attempts,
                    useful=last['status']==200 and time.monotonic()<=deadline,
                    elapsed=time.monotonic()-started,deadline_seconds=.35))
        # A leitura redundante termina pelo primeiro resultado; o trabalho perdedor continua.
        start=time.monotonic()
        with ThreadPoolExecutor(2) as pool:
            f1=pool.submit(call,url,dict(case='hedge',fault='read',intent='read'),.5)
            time.sleep(.025)
            f2=pool.submit(call,url,dict(case='hedge',fault='read',intent='read'),.5)
            second=f2.result();first_useful=time.monotonic()-start;cancelled=f1.cancel();first=f1.result()
        results.append(dict(case='hedge',first=first,second=second,first_useful_seconds=first_useful,
                            loser_cancelled=cancelled,total_seconds=time.monotonic()-start))
        # Breaker mínimo: duas falhas abrem; cinco admissões recusadas; uma sonda fecha.
        breaker=[]
        for i in range(2):breaker.append(call(url,dict(case='breaker',fault='always503',intent='b'),.1))
        rejects=5;time.sleep(.04)
        probe=call(url,dict(case='breaker',fault='read',intent='b'),.3)
        results.append(dict(case='breaker',failures=breaker,rejected_open=rejects,probe=probe))
        time.sleep(.15)
        with urllib.request.urlopen(url,timeout=2) as r:stats=json.load(r)
        save(out/'results.json',results);save(out/'server_observation.json',stats)
    save(out/'server_exit.json',dict(pid=proc.pid,returncode=proc.returncode))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('role',choices=['server','run']);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();serve(a.out) if a.role=='server' else run(a.out)
