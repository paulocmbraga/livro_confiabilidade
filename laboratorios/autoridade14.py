"""L14: subconjuntos didáticos MCP 2025-11-25 e A2A 1.0.0 sobre HTTP local.

Não é SDK, servidor conformante completo, OAuth nem autenticação de produção.
X-Lab-Actor seleciona identidades de bancada, sem valor como credencial real.
"""
import argparse
from contextlib import contextmanager, closing
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import urllib.request
from .dados_ii import write, lines, table

MCP='2025-11-25';A2A='1.0.0'
TRANSPORTS=('direto','mcp','a2a')
ACTORS={'executor':dict(principal='ana',scopes=['close'],audience='tickets'),
        'leitor':dict(principal='ana',scopes=['read'],audience='tickets'),
        'outro':dict(principal='bruno',scopes=['close'],audience='tickets'),
        'audiencia_errada':dict(principal='ana',scopes=['close'],audience='outro-servico')}

def request_for():
    return dict(intent='I14',principal='ana',resource='T1',action='close',version=0,quantity=1,deadline=150)

def digest(req):
    return hashlib.sha256(json.dumps(req,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def initialize(path,revoked=False,version=0):
    with closing(sqlite3.connect(path)) as db:
        db.executescript('CREATE TABLE tickets(id TEXT PRIMARY KEY,owner TEXT,state TEXT,version INTEGER);'
            'CREATE TABLE approvals(hash TEXT PRIMARY KEY,revoked INTEGER);'
            'CREATE TABLE receipts(intent TEXT PRIMARY KEY,hash TEXT,body TEXT);'
            'CREATE TABLE audit(seq INTEGER PRIMARY KEY,actor TEXT,reason TEXT);')
        db.execute('INSERT INTO tickets VALUES(?,?,?,?)',('T1','ana','open',version))
        db.execute('INSERT INTO tickets VALUES(?,?,?,?)',('T2','bruno','open',0))
        db.execute('INSERT INTO approvals VALUES(?,?)',(digest(request_for()),int(revoked)))
        db.commit()

def execute(path,req,actor='executor',now=100,schema='1'):
    db=sqlite3.connect(path,timeout=5)
    try:
        db.execute('BEGIN IMMEDIATE')
        ctx=ACTORS.get(actor);reason=None;receipt=None
        if schema!='1' or not isinstance(req,dict) or set(req)!=set(request_for()):reason='schema'
        elif any(type(req[k]) is not int for k in ('quantity','version','deadline')):reason='tipo'
        elif any(type(req[k]) is not str for k in ('intent','principal','resource','action')):reason='tipo'
        elif req['quantity']!=1 or req['action']!='close':reason='contrato'
        elif ctx is None or ctx['principal']!=req['principal']:reason='identidade'
        elif ctx['audience']!='tickets':reason='audiencia'
        elif 'close' not in ctx['scopes']:reason='escopo'
        else:
            resource=db.execute('SELECT owner,state,version FROM tickets WHERE id=?',(req['resource'],)).fetchone()
            approval=db.execute('SELECT revoked FROM approvals WHERE hash=?',(digest(req),)).fetchone()
            old=db.execute('SELECT hash,body FROM receipts WHERE intent=?',(req['intent'],)).fetchone()
            if not resource or resource[0]!=ctx['principal']:reason='recurso'
            elif now>req['deadline']:reason='prazo'
            elif not approval or approval[0]:reason='aprovacao'
            elif old:
                if old[0]!=digest(req):reason='conflito'
                else:receipt=json.loads(old[1]);reason='repeticao'
            elif resource[2]!=req['version']:reason='versao'
            else:
                db.execute("UPDATE tickets SET state='closed',version=version+1 WHERE id=?",(req['resource'],))
                receipt=dict(req,hash=digest(req),effect='applied',new_version=req['version']+1)
                db.execute('INSERT INTO receipts VALUES(?,?,?)',(req['intent'],digest(req),json.dumps(receipt)))
                reason='aplicado'
        db.execute('INSERT INTO audit(actor,reason) VALUES(?,?)',(actor,reason));db.commit()
        return dict(allowed=receipt is not None,reason=reason,receipt=receipt)
    finally:db.close()

def snapshot(path):
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    try:
        return dict(tickets=[list(r) for r in db.execute('SELECT * FROM tickets ORDER BY id')],
            receipts=[json.loads(r[0]) for r in db.execute('SELECT body FROM receipts ORDER BY intent')],
            audit=[list(r) for r in db.execute('SELECT * FROM audit ORDER BY seq')])
    finally:db.close()

def valid_receipt(req,receipt):
    return (isinstance(receipt,dict) and all(receipt.get(k)==v for k,v in req.items())
        and receipt.get('hash')==digest(req) and receipt.get('effect')=='applied'
        and receipt.get('new_version')==req['version']+1)

def cases():
    rows=[]
    for i,name in enumerate(('normal','repeticao','recurso','principal','estado_alterado','expirada',
            'revogada','delegacao_ampliada','audiencia','campo_extra','booleano','schema_novo','artefato_trocado'),1):
        c=dict(case_id=f'P{i:02}',name=name,request=request_for(),actor='executor',now=100,
            revoked=False,version=0,schema='1',repeat=1,tamper=False)
        if name=='repeticao':c['repeat']=2
        if name=='recurso':c['request']['resource']='T2'
        if name=='principal':c['actor']='outro'
        if name=='estado_alterado':c['version']=1
        if name=='expirada':c['now']=151
        if name=='revogada':c['revoked']=True
        if name=='delegacao_ampliada':c['actor']='leitor'
        if name=='audiencia':c['actor']='audiencia_errada'
        if name=='campo_extra':c['request']['admin']=True
        if name=='booleano':c['request']['quantity']=True
        if name=='schema_novo':c['schema']='2'
        if name=='artefato_trocado':c['tamper']=True
        c['expected_effects']=1 if name in ('normal','repeticao','artefato_trocado') else 0
        rows.append(c)
    return rows

def serve(path,portfile,now):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,data):
            raw=json.dumps(data).encode();self.send_response(200)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            self.reply(dict(name='Horizonte L14',description='Perfil local parcial',version='1.0',
                supportedInterfaces=[dict(url='http://127.0.0.1:'+str(self.server.server_port)+'/a2a',
                    protocolBinding='JSONRPC',protocolVersion=A2A)],capabilities={},
                defaultInputModes=['application/json'],defaultOutputModes=['application/json'],
                skills=[dict(id='close',name='Encerrar chamado',description='Exige autorização vinculada',tags=['tickets'])]))
        def do_POST(self):
            try:
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                ident=data.get('id');method=data.get('method');params=data.get('params',{})
                if self.path=='/mcp':
                    if method=='initialize':
                        if params.get('protocolVersion')!=MCP:raise ValueError('versao_mcp')
                        self.server.negotiated=True
                        self.reply(dict(jsonrpc='2.0',id=ident,result=dict(protocolVersion=MCP,
                            capabilities={'tools':{}},serverInfo=dict(name='L14',version='1.0'))));return
                    if method=='notifications/initialized':
                        if not self.server.negotiated or 'id' in data:raise ValueError('notificacao')
                        self.server.initialized=True;self.send_response(202);self.end_headers();return
                    if not self.server.initialized:raise ValueError('sem_inicializacao')
                    if self.headers.get('MCP-Protocol-Version')!=MCP:raise ValueError('cabecalho_versao')
                    if method=='tools/list':
                        schema=dict(type='object',properties={k:dict(type='integer' if type(v)is int else 'string')
                            for k,v in request_for().items()},required=list(request_for()),additionalProperties=False)
                        self.reply(dict(jsonrpc='2.0',id=ident,result={'tools':[dict(name='close',inputSchema=schema)]}));return
                    if method!='tools/call' or params.get('name')!='close':raise ValueError('metodo')
                    req=params['arguments']
                elif self.path=='/a2a':
                    if method!='SendMessage':raise ValueError('metodo')
                    message=params['message']
                    if message['role']!='ROLE_USER' or not message['messageId']:raise ValueError('mensagem')
                    req=message['parts'][0]['data']
                elif self.path=='/direto':req=params
                else:raise ValueError('rota')
                result=execute(path,req,self.headers.get('X-Lab-Actor',''),now,self.headers.get('X-Lab-Schema',''))
                if self.path=='/mcp':result=dict(content=[dict(type='text',text=json.dumps(result))],
                    structuredContent=result,isError=not result['allowed'])
                elif self.path=='/a2a':result={'task':dict(id='task-'+req.get('intent','invalid'),contextId='ctx-l14',
                    status={'state':'TASK_STATE_COMPLETED' if result['allowed'] else 'TASK_STATE_REJECTED'},
                    artifacts=[dict(artifactId='decision',parts=[dict(data=result)])])}
                self.reply(dict(jsonrpc='2.0',id=ident,result=result))
            except (ValueError,KeyError,TypeError,IndexError) as exc:
                self.reply(dict(jsonrpc='2.0',id=locals().get('ident'),error=dict(code=-32602,message=str(exc))))
    http=HTTPServer(('127.0.0.1',0),Handler);http.initialized=False;http.negotiated=False
    portfile.write_text(str(http.server_port),encoding='ascii');http.serve_forever()

@contextmanager
def server(path,folder,now):
    portfile=folder/'port.txt';log=(folder/'server.log').open('w',encoding='utf8')
    proc=subprocess.Popen([sys.executable,'-m','laboratorios.autoridade14','--serve',str(path),
        '--portfile',str(portfile),'--now',str(now)],stdout=log,stderr=log)
    try:
        end=time.monotonic()+10
        while time.monotonic()<end:
            if proc.poll() is not None:raise RuntimeError('Servidor terminou; consulte server.log')
            if portfile.exists() and portfile.read_text().strip().isdigit():break
            time.sleep(.02)
        else:raise TimeoutError('Inicialização')
        yield 'http://127.0.0.1:'+portfile.read_text().strip(),proc.pid
    finally:
        proc.terminate();proc.wait(timeout=5);log.close()

def run_case(case,transport,folder):
    folder.mkdir();db=folder/'destination.sqlite';initialize(db,case['revoked'],case['version']);wire=[]
    with server(db,folder,case['now']) as (url,pid):
        def call(method,params):
            payload=dict(jsonrpc='2.0',id=len(wire)+1,method=method,params=params)
            request=urllib.request.Request(url+'/'+transport,json.dumps(payload).encode(),headers={
                'Content-Type':'application/json','MCP-Protocol-Version':MCP,'X-Lab-Actor':case['actor'],'X-Lab-Schema':case['schema']})
            with urllib.request.urlopen(request,timeout=3) as response:raw=json.load(response)
            wire.append(dict(request=payload,response=raw))
            if raw.get('id')!=payload['id']:raise ValueError('correlacao_rpc')
            return raw
        if transport=='mcp':
            call('initialize',dict(protocolVersion=MCP,capabilities={},clientInfo=dict(name='L14',version='1.0')))
            payload=dict(jsonrpc='2.0',method='notifications/initialized')
            notification=urllib.request.Request(url+'/mcp',json.dumps(payload).encode(),headers={
                'Content-Type':'application/json','MCP-Protocol-Version':MCP})
            with urllib.request.urlopen(notification,timeout=3) as response:
                if response.status!=202:raise ValueError('notificacao_nao_aceita')
                wire.append(dict(request=payload,response={'http_status':response.status}))
            call('tools/list',{})
        if transport=='a2a':
            with urllib.request.urlopen(url+'/.well-known/agent-card.json',timeout=3) as r:card=json.load(r)
            write(folder/'agent_card.json',card)
        results=[]
        for _ in range(case['repeat']):
            req=case['request']
            if transport=='mcp':method='tools/call';params=dict(name='close',arguments=req)
            elif transport=='a2a':method='SendMessage';params=dict(message=dict(role='ROLE_USER',messageId='m-'+str(len(wire)),parts=[dict(data=req)]))
            else:method='execute';params=req
            raw=call(method,params);result=raw['result']
            if transport=='mcp':result=result['structuredContent']
            if transport=='a2a':result=result['task']['artifacts'][0]['parts'][0]['data']
            observed=deepcopy(result)
            if case['tamper']:observed['receipt']['resource']='T2'
            client=('confirmed' if valid_receipt(req,observed['receipt']) else 'unknown') if observed['allowed'] else 'rejected'
            results.append(dict(observed=observed,client=client))
    state=snapshot(db);lines(folder/'wire.jsonl',wire);write(folder/'snapshot.json',state)
    row=dict(case_id=case['case_id'],transport=transport,pid=pid,client_pid=os.getpid(),
        calls=len(wire),expected_effects=case['expected_effects'],effects=len(state['receipts']),
        client=results[-1]['client'],reason=results[-1]['observed']['reason'],results=results)
    if row['effects']!=row['expected_effects']:raise AssertionError(row)
    write(folder/'result.json',row);return row

def summarize(rows):
    return [dict(transport=t,cases=len(g),effects=sum(r['effects'] for r in g),
        confirmed=sum(r['client']=='confirmed' for r in g),unknown=sum(r['client']=='unknown' for r in g),
        rejected=sum(r['client']=='rejected' for r in g),post_requests=sum(r['calls'] for r in g))
        for t in TRANSPORTS for g in [[r for r in rows if r['transport']==t]]]

def capture(folder):
    folder.mkdir();rows=[]
    for c in cases():
        for t in TRANSPORTS:rows.append(run_case(c,t,folder/(c['case_id']+'_'+t)))
    lines(folder/'permission_cases.jsonl',cases());lines(folder/'permission_trials.jsonl',rows)
    table(folder/'permission_matrix.csv',[{k:v for k,v in r.items() if k!='results'} for r in rows])
    lines(folder/'effect_receipts.jsonl',[dict(case_id=r['case_id'],transport=r['transport'],receipt=x['observed']['receipt'])
        for r in rows for x in r['results'] if x['client']=='confirmed'])
    write(folder/'protocol_manifest.json',dict(mcp=MCP,a2a=A2A,transport='HTTP loopback em subprocessos',
        scope='Subconjuntos didáticos de envelopes; sem conformidade integral, SDK, OAuth, streaming ou cancelamento A2A.',
        identity='Cabeçalho de bancada escolhe identidade preparada; não autentica usuário real.',
        mutations='A última perturbação troca o artefato observado após a resposta, sem alterar o wire original.'))
    return summarize(rows)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--serve',type=Path);p.add_argument('--portfile',type=Path)
    p.add_argument('--now',type=int,default=100);a=p.parse_args();serve(a.serve,a.portfile,a.now)
