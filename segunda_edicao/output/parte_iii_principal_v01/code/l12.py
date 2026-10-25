"""Workers reais, inferência local, avaliador separado e coletor com identidade."""
from http.server import HTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import argparse,json,os,time,re
from laboratorios.parte_i.common import load,save,digest
from laboratorios.l11.core import strict_json
from laboratorios.l11.runtime import http

def cases():
    values=[10,30,7,15,20,5,45,12]
    return [dict(id=f'T{i:02}',document=f'Documento D{i:02}. O prazo desta tarefa é {v} dias.',
                 question='Qual é o prazo em dias?',expected=v,source=f'D{i:02}') for i,v in enumerate(values,1)]

def request_for(case):
    return {'model':'l11-qwen','messages':[
        {'role':'system','content':'Extraia o prazo do documento. Responda somente JSON com a chave prazo e um inteiro. Não invente valores.'},
        {'role':'user','content':case['document']+'\n'+case['question']}],
        'temperature':0,'seed':1200+int(case['id'][1:]),'max_tokens':48,'stream':False,'cache_prompt':False,
        'response_format':{'type':'json_schema','json_schema':{'name':'deadline','strict':True,'schema':{'type':'object','properties':{'prazo':{'type':'integer'}},'required':['prazo'],'additionalProperties':False}}}}

def consumed_text(raw,truncate=False):
    if raw['error'] or not raw['response']:return None
    try:
        choice=raw['response']['choices'][0]
        if choice['finish_reason']!='stop':return None
        text=choice['message']['content']
        return text[:max(1,len(text)//2)] if truncate else text
    except (KeyError,IndexError,TypeError):return None

def evaluate(text,case,version):
    if version not in ('exact-v1','exact-v2'):raise ValueError('judge version')
    try:
        obj=strict_json(text)
        if set(obj)!={'prazo'} or type(obj['prazo']) is not int:raise ValueError('schema')
    except (ValueError,TypeError,KeyError):return {'valid':False,'correct':False,'reason':'invalid'}
    correct=obj['prazo']==case['expected']
    if version=='exact-v2':correct=correct and case['source'] in text
    return {'valid':True,'correct':correct,'reason':'match' if correct else 'mismatch'}

class Collector:
    def __init__(self,expected):
        self.expected={e['attempt']:e for e in expected}
        if len(self.expected)!=len(expected):raise ValueError('duplicate admission')
        self.received={};self.events=[];self.closed=False
    def callback(self,payload):
        key=payload.get('attempt');expected=self.expected.get(key)
        if self.closed:status='late'
        elif expected is None:status='unknown_attempt'
        elif any(payload.get(k)!=expected[k] for k in ('case','candidate','judge')):status='identity_mismatch'
        elif type(payload.get('valid')) is not bool or type(payload.get('correct')) is not bool or (payload['correct'] and not payload['valid']) or not isinstance(payload.get('output_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',payload['output_sha256']):status='malformed'
        elif key in self.received:status='duplicate' if self.received[key]==payload else 'conflicting_duplicate'
        else:self.received[key]=payload;status='accepted'
        event={'index':len(self.events),'payload':payload,'status':status};self.events.append(event)
        return event
    def snapshot(self):return {'closed':self.closed,'received':self.received,'events':self.events}

def release(report,now,expected_identity):
    if report['identity']!=expected_identity:return 'blocked_identity'
    if type(now) not in (int,float) or not report['created']<=now<=report['expires']:return 'blocked_expired'
    if any(v!='evaluated' for v in report['tasks'].values()):return 'blocked_incomplete'
    if report.get('accepted_correct')!=len(report['tasks']):return 'blocked_quality'
    if report.get('human_semantic_qualification') is not True:return 'blocked_qualification'
    return 'eligible_for_review'

def service(role,folder,config_path):
    config=load(config_path);collector=Collector(config['expected']) if role=='collector' else None
    reference={r['id']:r for r in config.get('cases',[])}
    count=0
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,value):
            data=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):self.send(collector.snapshot() if collector else {'status':'ok'})
        def do_POST(self):
            nonlocal count
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if role=='collector':
                if self.path=='/close':collector.closed=True;result=collector.snapshot()
                else:result=collector.callback(payload)
            else:
                result=evaluate(payload['text'],reference[payload['case']],payload['judge'])
                result.update(judge=payload['judge'],case=payload['case'],input_sha256=digest(payload['text']))
            save(folder/f'event_{count:03}.json',{'path':self.path,'request':payload,'response':result});count+=1
            self.send(result)
    server=HTTPServer(('127.0.0.1',0),Handler);save(folder/'ready.json',{'port':server.server_port,'pid':os.getpid()});server.serve_forever()

def worker(config_path,resume=False):
    config=load(config_path);folder=Path(config['folder']);mode=config['mode']
    if mode=='crash_before_inference' and not resume:
        save(folder/'before_crash.json',{'pid':os.getpid(),'stage':'before_inference'});os._exit(86)
    if resume and (folder/'raw.json').exists():raw=load(folder/'raw.json')
    else:
        start=time.perf_counter();response=None;error=None
        try:response=http(config['model_url']+'/v1/chat/completions',config['request'],90)
        except Exception as exc:error={'type':type(exc).__name__,'message':str(exc)}
        raw={'request':config['request'],'response':response,'error':error,'seconds':time.perf_counter()-start,'pid':os.getpid()}
        save(folder/'raw.json',raw)
    if mode=='crash_after_raw' and not resume:
        save(folder/'after_crash.json',{'pid':os.getpid(),'stage':'durable_raw_before_callback'});os._exit(87)
    text=consumed_text(raw,mode=='truncated_consumer')
    judge='exact-v2' if mode=='judge_change' else config['expected']['judge']
    ev_req={'case':config['expected']['case'],'judge':judge,'text':text}
    evaluation=http(config['evaluator_url']+'/evaluate',ev_req)
    save(folder/'evaluation.json',{'request':ev_req,'response':evaluation})
    payload={**config['expected'],'judge':judge,'output_sha256':digest(text),'valid':evaluation['valid'],'correct':evaluation['correct']}
    if mode=='candidate_mismatch':payload['candidate']='other-candidate'
    save(folder/'callback.json',payload)
    if mode!='delayed_callback':
        result=http(config['collector_url']+'/callback',payload);save(folder/'delivery.json',result)
        if mode=='duplicate_callback':save(folder/'duplicate_delivery.json',http(config['collector_url']+'/callback',payload))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('role',choices=['worker','evaluator','collector']);p.add_argument('--config',type=Path,required=True);p.add_argument('--folder',type=Path);p.add_argument('--resume',action='store_true');a=p.parse_args()
    if a.role=='worker':worker(a.config,a.resume)
    else:service(a.role,a.folder,a.config)
