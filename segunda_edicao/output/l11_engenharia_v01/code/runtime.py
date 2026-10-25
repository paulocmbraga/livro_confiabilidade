"""Servidor local isolado por modelo, recursos amostrados e encerramento garantido."""
from contextlib import contextmanager
from pathlib import Path
import json, platform, socket, subprocess, threading, time
from urllib.request import Request, urlopen
import psutil
from .core import sha,save

def http(url, payload=None, timeout=90):
    data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None
    with urlopen(Request(url,data=data,headers={'Content-Type':'application/json'}),timeout=timeout) as r:
        return json.loads(r.read())

@contextmanager
def server(runtime, judge, lock, out, plan):
    item=next(i for i in lock['downloads'] if i['id']==judge)
    model=runtime/item['filename'];exe=runtime/'runtime_b11669/llama-server.exe'
    if sha(model)!=item['sha256'] or sha(exe)!=lock['server_sha256']:raise ValueError('hash de runtime/modelo')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    args=[str(exe),'-m',str(model),'--host','127.0.0.1','--port',str(port),'-t',str(plan['threads']),
          '-tb',str(plan['threads']),'-c',str(plan['context']),'-np','1','-ngl','0','--no-webui','--alias','l11-'+judge]
    start=time.perf_counter();samples=[];done=threading.Event();proc=None
    try:
        with (out/(judge+'_server.log')).open('wb') as log:
            proc=subprocess.Popen(args,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            process=psutil.Process(proc.pid)
            def monitor():
                while not done.wait(1):
                    try:
                        t=process.cpu_times();samples.append(dict(seconds=round(time.perf_counter()-start,3),
                            rss=process.memory_info().rss,cpu_seconds=t.user+t.system,
                            ram_available=psutil.virtual_memory().available))
                    except psutil.Error:return
            thread=threading.Thread(target=monitor,daemon=True);thread.start()
            url=f'http://127.0.0.1:{port}'
            for _ in range(180):
                if proc.poll() is not None:raise RuntimeError('Servidor encerrou durante inicialização')
                try:
                    if http(url+'/health',timeout=2).get('status')=='ok':break
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
        if 'thread' in locals():thread.join(3)
        save(out/(judge+'_resources.json'),dict(seconds=round(time.perf_counter()-start,3),
            rss_peak_bytes=max((s['rss'] for s in samples),default=None),samples=samples,
            cpu_seconds=samples[-1]['cpu_seconds'] if samples else None,
            process_ended=proc is not None and proc.poll() is not None,
            model_sha256=item['sha256'],runtime_sha256=lock['server_sha256'],
            arguments=args[1:],host_ram_bytes=psutil.virtual_memory().total,
            python=platform.python_version(),psutil=psutil.__version__,platform=platform.platform()))
