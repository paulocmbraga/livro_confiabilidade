"""SDK 1.38.0, OTLP HTTP real e comparação com ledger separado."""
import argparse,json,os,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
from opentelemetry import propagate,trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import Sampler,SamplingResult,Decision,ParentBased,ALWAYS_ON
from opentelemetry.sdk.trace.export import BatchSpanProcessor,SimpleSpanProcessor,SpanExporter,SpanExportResult
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from .core import save,load


class EveryOther(Sampler):
    def should_sample(self,parent_context,trace_id,name,kind=None,attributes=None,links=None,trace_state=None):
        selected=int((attributes or {}).get('app.sequence',0))%2==0
        return SamplingResult(Decision.RECORD_AND_SAMPLE if selected else Decision.DROP,attributes)
    def get_description(self):return 'deterministic alternating sequence; educational, not random'


class Recorder(SpanExporter):
    def __init__(self,url,gate=False):
        self.inner=OTLPSpanExporter(endpoint=url+'/v1/traces',timeout=.4)
        self.rows=[];self.entered=threading.Event();self.release=threading.Event();self.gate=gate
    def export(self,spans):
        start=time.time_ns()
        if self.gate and not self.entered.is_set():
            self.entered.set()
            if not self.release.wait(10):raise TimeoutError('gate de ensaio não liberado')
        error=None
        try:result=self.inner.export(spans)
        except Exception as exc:
            result=SpanExportResult.FAILURE;error=type(exc).__name__+': '+str(exc)
        end=time.time_ns()
        self.rows.append(dict(start_ns=start,end_ns=end,result=result.name,error=error,
            ids=[[f'{s.context.trace_id:032x}',f'{s.context.span_id:016x}'] for s in spans],
            ack_delay_ms=[(end-s.end_time)/1e6 for s in spans]))
        return result
    def shutdown(self):self.inner.shutdown()


def provider(url,role,mode):
    exporter=Recorder(url,mode=='saturation')
    sampler=ParentBased(EveryOther() if mode=='sampled' else ALWAYS_ON)
    p=TracerProvider(resource=Resource.create({'service.name':'ix-'+role}),sampler=sampler)
    processor=BatchSpanProcessor(exporter,max_queue_size=8,max_export_batch_size=1,
        schedule_delay_millis=10000) if mode=='saturation' else SimpleSpanProcessor(exporter)
    p.add_span_processor(processor);return p,exporter


def identity(span,task,role,parent=None):
    c=span.get_span_context()
    return dict(task=task,role=role,trace_id=f'{c.trace_id:032x}',span_id=f'{c.span_id:016x}',
                parent_id=parent,sampled=bool(c.trace_flags.sampled),recorded_ns=time.time_ns())


def request(url,data):
    with urlopen(Request(url,json.dumps(data).encode(),{'Content-Type':'application/json'}),timeout=15) as r:
        return json.loads(r.read())


def main():
    ap=argparse.ArgumentParser();ap.add_argument('role',choices=['service','client'])
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--url',required=True)
    ap.add_argument('--mode',required=True);ap.add_argument('--service');a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    p,exporter=provider(a.url,a.role,a.mode);tracer=p.get_tracer('book.ix','1');ledger=[]
    if a.role=='service':
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path=='/stop':
                    self.send_response(200);self.end_headers();self.wfile.write(b'{}')
                    threading.Thread(target=server.shutdown,daemon=True).start();return
                ctx=propagate.extract(body['carrier']);parent=trace.get_current_span(ctx).get_span_context()
                with tracer.start_as_current_span('effect',context=ctx,attributes={
                    'app.task':body['task'],'app.role':'service','app.phase':a.mode}) as span:
                    # Efeito autoral sintético no ledger, separado do pipeline OTLP.
                    record=identity(span,body['task'],'service',f'{parent.span_id:016x}')
                    record['effect']='receipt-'+body['task'];ledger.append(record)
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(record).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        save(a.out/'ready.json',dict(url=f'http://127.0.0.1:{server.server_port}',pid=os.getpid()))
        server.serve_forever(poll_interval=.01);server.server_close()
    else:
        n=200 if a.mode=='saturation' else 12
        for i in range(n):
            task=f'{a.mode}-{i}'
            with tracer.start_as_current_span('task',attributes={'app.task':task,
                'app.role':'client','app.phase':a.mode,'app.sequence':i}) as span:
                row=identity(span,task,'client');carrier={};propagate.inject(carrier)
                if a.mode!='saturation':row['response']=request(a.service,dict(task=task,carrier=carrier))
                ledger.append(row)
            if a.mode=='saturation' and i==0:
                if not exporter.entered.wait(5):raise TimeoutError('exportador não entrou no gate')
        exporter.release.set()
    flushed=p.force_flush();p.shutdown()
    if a.role=='client':
        reader=PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=a.url+'/v1/metrics',timeout=.4),
                                            export_interval_millis=60000)
        mp=MeterProvider(metric_readers=[reader],resource=Resource.create({'service.name':'ix-client'}))
        mp.get_meter('book.ix').create_counter('app.tasks').add(len(ledger),{'phase':a.mode})
        mp.force_flush();mp.shutdown()
    save(a.out/'ledger.json',ledger);save(a.out/'exports.json',exporter.rows)
    save(a.out/'ended.json',dict(pid=os.getpid(),force_flush=flushed))
if __name__=='__main__':main()
