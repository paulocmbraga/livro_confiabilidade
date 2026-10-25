"""Serving CPU, isolamento de processo, SSE e recursos medidos."""
from contextlib import contextmanager
import json,socket,subprocess,threading,time
from urllib.request import Request,urlopen
import psutil
from .core import sha,save


def http(url,payload=None,timeout=60):
    data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None
    with urlopen(Request(url,data,{'Content-Type':'application/json'}),timeout=timeout) as r:
        return json.loads(r.read())


@contextmanager
def server(runtime,model,lock,out,parallel=1,batching=True):
    out.mkdir(parents=True);item=next(x for x in lock['downloads'] if x['id']==model)
    exe=runtime/'runtime_b11669/llama-server.exe';weights=runtime/item['filename']
    if sha(weights)!=item['sha256'] or sha(exe)!=lock['server_sha256']:raise ValueError('runtime/modelo')
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    args=[str(exe),'-m',str(weights),'--host','127.0.0.1','--port',str(port),'-t','4','-tb','4',
          '-c','8192','-np',str(parallel),'-ngl','0','--no-webui','--alias',model,
          '--cont-batching' if batching else '--no-cont-batching','--no-cache-prompt','--metrics']
    samples=[];done=threading.Event();started=time.perf_counter();proc=None
    try:
        with (out/'server.log').open('xb') as log:
            proc=subprocess.Popen(args,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            ps=psutil.Process(proc.pid)
            def monitor():
                while not done.wait(.2):
                    try:
                        cpu=ps.cpu_times();samples.append(dict(at=time.perf_counter()-started,
                            rss=ps.memory_info().rss,cpu_seconds=cpu.user+cpu.system,
                            available_ram=psutil.virtual_memory().available))
                    except psutil.Error:return
            t=threading.Thread(target=monitor,daemon=True);t.start();url=f'http://127.0.0.1:{port}'
            for _ in range(180):
                if proc.poll() is not None:raise RuntimeError('serving encerrou')
                try:
                    if http(url+'/health',timeout=1).get('status')=='ok':break
                except Exception:pass
                time.sleep(.5)
            else:raise TimeoutError('health')
            yield url
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:proc.wait(5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(5)
        done.set()
        if 't' in locals():t.join(2)
        save(out/'resources.json',dict(arguments=args[1:],model_sha256=item['sha256'],
            runtime_sha256=lock['server_sha256'],samples=samples,
            rss_peak=max((x['rss'] for x in samples),default=None),
            cpu_seconds=samples[-1]['cpu_seconds'] if samples else None,
            seconds=time.perf_counter()-started,ended=proc is not None and proc.poll() is not None,
            cpu_only=True,ram_total=psutil.virtual_memory().total))


def stream(url,payload):
    start=time.perf_counter();first=None;events=[];content=[];usage=None;finish=None
    request=dict(payload,stream=True,stream_options={'include_usage':True})
    with urlopen(Request(url+'/v1/chat/completions',json.dumps(request).encode(),
                         {'Content-Type':'application/json'}),timeout=60) as r:
        for line in r:
            if not line.startswith(b'data:'):continue
            raw=line[5:].strip()
            if raw==b'[DONE]':break
            event=json.loads(raw);events.append(event)
            if event.get('usage'):usage=event['usage']
            for choice in event.get('choices',[]):
                text=choice.get('delta',{}).get('content') or ''
                if text and first is None:first=time.perf_counter()
                content.append(text)
                if choice.get('finish_reason'):finish=choice['finish_reason']
    end=time.perf_counter()
    return dict(request=request,events=events,text=''.join(content),usage=usage,finish=finish,
        ttft=first-start if first is not None else None,elapsed=end-start,
        decode_seconds=end-first if first is not None else None)
