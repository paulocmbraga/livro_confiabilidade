"""Campanha exclusiva; não toca contêineres alheios nem modifica provas anteriores."""
from pathlib import Path
import argparse,json,platform,socket,subprocess,sys,time,uuid
from importlib.metadata import version
from .core import *
from .telemetry import request
from . import slo,serving,economics
from laboratorios.parte_i.common import child,wait_file
ROOT=Path(__file__).resolve().parents[2]
IMAGE='otel/opentelemetry-collector-contrib@sha256:ffc818ee108d0b934fd14207fd87ff247c9b64f344ed349d0b66c166c18a2312'


def docker(*args):
    return subprocess.check_output(['docker',*map(str,args)],text=True,stderr=subprocess.STDOUT).strip()


def wait_port(port):
    for _ in range(100):
        try:
            with socket.create_connection(('127.0.0.1',port),timeout=.5):return
        except OSError:time.sleep(.1)
    raise TimeoutError('collector')


def flatten(path):
    spans=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        data=json.loads(line)
        for resource in data.get('resourceSpans',[]):
            for scope in resource.get('scopeSpans',[]):
                for s in scope['spans']:
                    attrs={a['key']:next(iter(a['value'].values())) for a in s.get('attributes',[])}
                    spans.append(dict(trace_id=s['traceId'],span_id=s['spanId'],parent_id=s.get('parentSpanId') or None,
                        role=attrs.get('app.role'),task=attrs.get('app.task'),phase=attrs.get('app.phase')))
    return spans


def telemetry(out):
    out.mkdir();sink=out/'sink';sink.mkdir();name='book-ix-'+uuid.uuid4().hex[:10]
    config='''receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
exporters:
  file/traces:
    path: /data/traces.jsonl
    append: true
    flush_interval: 100ms
  file/metrics:
    path: /data/metrics.jsonl
    append: true
    flush_interval: 100ms
service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [file/traces]
    metrics:
      receivers: [otlp]
      exporters: [file/metrics]
'''
    (out/'collector.yaml').write_text(config,encoding='utf-8',newline='\n')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));published_port=sock.getsockname()[1]
    args=['run','-d','--name',name,'--user','0:0','--memory','256m','--cpus','1',
        '-p',f'127.0.0.1:{published_port}:4318','--mount',f'type=bind,source={(out/"collector.yaml").resolve()},target=/etc/otelcol-contrib/config.yaml,readonly',
        '--mount',f'type=bind,source={sink.resolve()},target=/data',IMAGE]
    created=False;report=[]
    try:
        container=docker(*args);created=True
        inspect=json.loads(docker('inspect',name))[0];port=int(inspect['NetworkSettings']['Ports']['4318/tcp'][0]['HostPort'])
        save(out/'container.json',dict(name=name,id=container,image=IMAGE,port=port,arguments=args))
        wait_port(port);url=f'http://127.0.0.1:{port}'
        for mode in ['healthy','sampled','outage','saturation','recovery']:
            folder=out/mode;folder.mkdir()
            if mode=='outage':docker('stop','-t','3',name)
            if mode=='saturation':docker('start',name);wait_port(port)
            if mode=='saturation':
                with child('laboratorios.parte_ix.telemetry',['client','--out',folder/'client','--url',url,'--mode',mode],folder/'client_process') as client:
                    assert client.wait(30)==0
            else:
                with child('laboratorios.parte_ix.telemetry',['service','--out',folder/'service','--url',url,'--mode',mode],folder/'service_process') as service:
                    wait_file(folder/'service/ready.json',service);service_url=load(folder/'service/ready.json')['url']
                    with child('laboratorios.parte_ix.telemetry',['client','--out',folder/'client','--url',url,'--mode',mode,
                              '--service',service_url],folder/'client_process') as client:assert client.wait(45)==0
                    request(service_url+'/stop',{});assert service.wait(15)==0
        docker('stop','-t','3',name)
        spans=flatten(sink/'traces.jsonl');save(out/'spans.json',spans)
        for mode in ['healthy','sampled','outage','saturation','recovery']:
            folder=out/mode;ledger=[];attempts=[]
            for role in ['client','service']:
                if (folder/role/'ledger.json').exists():
                    ledger+=load(folder/role/'ledger.json');attempts+=load(folder/role/'exports.json')
            selected=[s for s in spans if s['phase']==mode]
            result=reconcile(ledger,selected,attempts)
            delays=[d for a in attempts if a['result']=='SUCCESS' for d in a['ack_delay_ms']]
            report.append(dict(phase=mode,**result,ack_delay_p95_ms=percentile(delays,.95)))
        save(out/'result.json',report)
    finally:
        if created:
            (out/'collector.log').write_text(docker('logs',name),encoding='utf-8')
            docker('rm','-f',name);save(out/'cleanup.json',dict(name=name,removed=True))


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    p.add_argument('--only',choices=['all','l33','l34','l35','l36'],default='all');a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    sources=list((ROOT/'laboratorios/parte_ix').glob('*.py'))+[ROOT/'requirements-parte-ix.lock.txt',ROOT/'materiais/l11/modelos.lock.json',ROOT/'testes/test_parte_ix.py']
    save(out/'inputs.json',{f.relative_to(ROOT).as_posix():sha(f) for f in sources})
    save(out/'plan.json',dict(version=1,selection=a.only,created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        l33=dict(phases=['healthy','sampled','outage','saturation','recovery'],normal_tasks=12,burst=200,queue=8,
            gate='explicit exporter stall; release after 200 spans; separate from collector outage'),
        l34=dict(target=.99,lag_minutes=12,windows=[30,5],burn_threshold=6,coverage=.95),
        l35=dict(tasks=18,parallel=2,threads=4,tokens=32,arrival='open and closed',deadline_scoring_seconds=4,
            timeout='socket 60s; does not prove remote cancellation',capacity='bounded experiment on shared CPU host'),
        l36=dict(development=12,reserve=12,shift=12,repeats_per_split=2,seed=36,
            costs='parameterized; no paid API; no measured human work',quality_gate=.8,
            manual_guard='complexity=1 always pending review, equal for all policies; no human evaluation executed')))
    save(out/'environment.json',dict(python=platform.python_version(),platform=platform.platform(),
        sdk=version('opentelemetry-sdk'),psutil=version('psutil'),docker=docker('version','--format','{{.Server.Version}}')))
    success=False
    try:
        lock=load(ROOT/'materiais/l11/modelos.lock.json');runtime=ROOT/'.modelos/l11'
        if a.only in ['all','l33']:telemetry(out/'l33')
        if a.only in ['all','l34']:slo.run(out/'l34')
        if a.only in ['all','l35']:serving.run(out/'l35',runtime,lock)
        if a.only in ['all','l36']:economics.run(out/'l36',runtime,lock)
        success=True
    finally:seal(out,'parte-ix-local-experiments',success)
    print(json.dumps(dict(out=str(out),complete=success)))
if __name__=='__main__':main()
