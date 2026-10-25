"""L35: chegada aberta, loop fechado e admissão sobre llama.cpp real."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import threading,time
from .core import save,percentile
from .runtime import server,http,stream


def tasks():
    return [dict(id=f'T{i:02}',scheduled=(i*.4 if i<6 else 3 if i<12 else 8+(i-12)*.5),
        slow=i in [7,8,9,10],tenant='b' if i%3==0 else 'a',
        prompt=f'Pedido {i}. Explique em portugues, em duas frases, por que confirmar um recibo antes de repetir uma operacao.') for i in range(18)]


def summary(rows):
    done=[x for x in rows if x['status']=='completed']
    return dict(offered=len(rows),completed=len(done),rejected=sum(x['status']=='rejected' for x in rows),
        errors=sum(x['status']=='error' for x in rows),within_4s=sum(x['end_to_end']<=4 for x in done),
        p50=percentile([x['end_to_end'] for x in done],.5),p95=percentile([x['end_to_end'] for x in done],.95),
        p99=percentile([x['end_to_end'] for x in done],.99),
        ttft_p95=percentile([x['ttft_total'] for x in done if x['ttft_total'] is not None],.95),
        offered_lag_p95=percentile([x['start_lag'] for x in rows],.95),
        recovery_p95=percentile([x['end_to_end'] for x in done if int(x['id'][1:])>=12],.95),
        completion_tokens=sum((x['response']['usage'] or {}).get('completion_tokens',0) for x in done),
        tenant_admitted={t:sum(x['tenant']==t and x['status']!='rejected' for x in rows) for t in ['a','b']})


def run(out,runtime,lock):
    out.mkdir();work=tasks();save(out/'tasks.json',work)
    class Dependency(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            time.sleep(.6 if self.path=='/slow' else .01)
            self.send_response(200);self.end_headers();self.wfile.write(b'{"ok":true}')
    dep=ThreadingHTTPServer(('127.0.0.1',0),Dependency)
    thread=threading.Thread(target=dep.serve_forever,daemon=True);thread.start()
    all_results=[]
    try:
        for mode,batching,admission,closed in [('open_no_batch',False,False,False),
            ('open_batch',True,False,False),('open_admission',True,True,False),('closed_batch',True,False,True)]:
            folder=out/mode;folder.mkdir();gate=threading.BoundedSemaphore(2)
            with server(runtime,'qwen',lock,folder/'runtime',parallel=2,batching=batching) as url:
                # Aquecimento declarado, fora da amostra. Cache de prompt desativado.
                warm=stream(url,dict(model='qwen',messages=[{'role':'user','content':'Diga ola.'}],max_tokens=4,temperature=0,seed=35))
                save(folder/'warmup.json',warm);origin=time.perf_counter()
                def one(task):
                    due=origin+task['scheduled']
                    if not closed:time.sleep(max(0,due-time.perf_counter()))
                    arrived=time.perf_counter();scheduled=arrived if closed else due
                    row=dict(task,id=task['id'],arrival=arrived-origin,start_lag=arrived-scheduled)
                    if admission and not gate.acquire(blocking=False):
                        return dict(row,status='rejected',end_to_end=time.perf_counter()-scheduled)
                    try:
                        dep_start=time.perf_counter()
                        http(f'http://127.0.0.1:{dep.server_port}/'+('slow' if task['slow'] else 'fast'))
                        dep_seconds=time.perf_counter()-dep_start
                        response=stream(url,dict(model='qwen',messages=[{'role':'user','content':task['prompt']}],
                            max_tokens=32,temperature=0,seed=35))
                        elapsed=time.perf_counter()-scheduled
                        return dict(row,status='completed',end_to_end=elapsed,dependency=dep_seconds,
                            ttft_total=row['start_lag']+dep_seconds+response['ttft'] if response['ttft'] is not None else None,
                            response=response)
                    except Exception as e:
                        return dict(row,status='error',error=type(e).__name__+': '+str(e),end_to_end=time.perf_counter()-scheduled)
                    finally:
                        if admission:gate.release()
                if closed:rows=[one(t) for t in work]
                else:
                    with ThreadPoolExecutor(max_workers=18) as pool:rows=list(pool.map(one,work))
                # As requisições já terminaram: nenhum timeout é tratado como cancelamento remoto.
                save(folder/'rows.json',rows);save(folder/'summary.json',summary(rows))
                all_results.append(dict(mode=mode,wall_seconds=time.perf_counter()-origin,**summary(rows)))
    finally:dep.shutdown();dep.server_close();thread.join(2)
    save(out/'result.json',all_results)
