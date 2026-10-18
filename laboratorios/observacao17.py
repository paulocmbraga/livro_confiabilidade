"""Dois serviços HTTP locais; protocolo de telemetria próprio, sem SDK OTel."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import statistics
import threading
import time
from urllib.request import Request, urlopen
from .dados_ii import write, lines, table

PROFILES = ('sucessos', 'falhas', 'controlado')
SECRET = 'SEGREDO-FICTICIO-L17'
FIELDS = ('schema', 'task', 'tenant', 'attempt', 'trace', 'span', 'parent',
          'service', 'status', 'duration_ns')


def cases():
    return [dict(task=f'T{i:02}', tenant='A' if i % 2 else 'B',
                 fail=i % 4 == 0, sampled=i != 9) for i in range(1, 13)]


def sanitize(event):
    return {k: event[k] for k in FIELDS if k in event}


@contextmanager
def service(callback):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            result = json.dumps(callback(payload)).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(result)))
            self.end_headers()
            self.wfile.write(result)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/'
    finally:
        server.shutdown(); thread.join(); server.server_close()


def post(url, payload):
    request = Request(url, json.dumps(payload).encode(),
                      {'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=5) as response:
        return json.load(response)


def audit(ledger, events):
    rows = []
    for task in ledger:
        observed = [e for e in events if e['task'] == task['task']]
        valid = [e for e in observed if e['tenant'] == task['tenant']
                 and e['trace'] == task['trace'] and e['attempt'] == 1]
        spans = {e['span'] for e in valid}
        root = task['task'] + '-gateway'
        child = task['task'] + '-tool'
        complete = (spans == {root, child}
                    and len(valid) == 2
                    and all(e['parent'] == (root if e['span'] == child else None)
                            for e in valid))
        rows.append(dict(task=task['task'], sampled=task['sampled'],
                         ledger_status=task['status'], observed=len(observed),
                         identity_errors=len(observed)-len(valid), complete=complete,
                         state=('completo' if complete else 'perdido_ou_incompleto')
                         if task['sampled'] else 'nao_amostrado'))
    known = {r['task'] for r in ledger}
    expected = sum(r['sampled'] for r in ledger)
    return dict(admitted=len(ledger), sampled=expected,
                complete=sum(r['complete'] for r in rows),
                coverage=sum(r['complete'] for r in rows)/len(ledger),
                sampled_coverage=sum(r['complete'] for r in rows)/expected,
                identity_errors=sum(r['identity_errors'] for r in rows),
                orphans=sum(e['task'] not in known for e in events), rows=rows)


def run(profile):
    if profile not in PROFILES:
        raise ValueError(profile)
    events = []; ledger = []
    def emit(c, name, status, duration):
        if not c['sampled']:
            return
        if profile == 'sucessos' and status != 'ok':
            return
        if profile == 'falhas' and c['task'] == 'T05' and name == 'tool':
            return
        event = dict(schema='livro.telemetry/1', task=c['task'], tenant=c['tenant'],
                     attempt=1, trace=c['trace'], span=c['task']+'-'+name,
                     parent=c['task']+'-gateway' if name == 'tool' else None,
                     service=name, status=status, duration_ns=duration,
                     content={'prompt': SECRET}, authorization=SECRET)
        if profile == 'falhas' and c['task'] == 'T07' and name == 'tool':
            event['tenant'] = 'B'
        events.append(sanitize(event) if profile == 'controlado' else event)
    def tool(c):
        start = time.perf_counter_ns()
        status = 'erro_preparado' if c['fail'] else 'ok'
        emit(c, 'tool', status, time.perf_counter_ns()-start)
        return dict(status=status)
    with service(tool) as tool_url:
        def gateway(c):
            start = time.perf_counter_ns()
            response = post(tool_url, c)
            emit(c, 'gateway', response['status'], time.perf_counter_ns()-start)
            return response
        with service(gateway) as gateway_url:
            for original in cases():
                c = dict(original, trace='trace-'+original['task'])
                # O registro independente existe antes do envio à aplicação.
                ledger.append(dict(c, status='admitido'))
                ledger[-1]['status'] = post(gateway_url, c)['status']
    if profile == 'falhas':
        events.append(dict(events[0], task='DESCONHECIDA', span='orfao'))
    return ledger, events, audit(ledger, events)


def benchmark(repetitions=6, count=3000):
    rows = []
    example = dict(schema='1', task='T', content=SECRET, status='ok')
    for repetition in range(repetitions):
        for mode in (('base', 'exportar') if repetition % 2 == 0
                     else ('exportar', 'base')):
            start = time.perf_counter_ns()
            for _ in range(count):
                item = dict(example)
                if mode == 'exportar':
                    json.dumps(sanitize(item))
            rows.append(dict(repetition=repetition, mode=mode, count=count,
                             elapsed_ns=time.perf_counter_ns()-start))
    return rows


def capture(folder):
    folder.mkdir()
    results = {}
    for profile in PROFILES:
        ledger, events, report = run(profile)
        lines(folder/f'{profile}_ledger.jsonl', ledger)
        lines(folder/f'{profile}_collector.jsonl', events)
        table(folder/f'{profile}_trace_audit.csv', report.pop('rows'))
        report['secret_exposed'] = SECRET in json.dumps(events)
        results[profile] = report
    write(folder/'telemetry_schema.json', dict(version='livro.telemetry/1',
          allowed=FIELDS, protocol='JSON próprio sobre HTTP; não é OTLP',
          retention='somente política ilustrativa; sem expurgo implementado'))
    write(folder/'privacy_checks.json', {k: v['secret_exposed'] for k,v in results.items()})
    table(folder/'overhead.csv', benchmark())
    return results
