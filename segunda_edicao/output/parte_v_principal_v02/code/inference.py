"""Capture every request and received SSE event. No partial output is actionable."""
import json,time
from urllib.request import Request,urlopen
from .core import identity
from laboratorios.parte_i.common import save

ORDER={'type':'object','properties':{'quantity':{'type':'integer'}},
       'required':['quantity'],'additionalProperties':False}
VALUE={'type':'object','properties':{'value':{'type':'number'}},
       'required':['value'],'additionalProperties':False}

def infer(url,out,name,prompt,*,schema=None,temperature=0,seed=1701,cut=None,
          model='qwen',max_tokens=80):
    payload={'model':'l11-'+model,'messages':[
        {'role':'system','content':'Follow the task. Use only supplied information. Do not invent facts.'},
        {'role':'user','content':prompt}], 'temperature':temperature,'seed':seed,
        'top_p':.9,'max_tokens':max_tokens,'stream':True,'cache_prompt':False}
    if schema:payload['response_format']={'type':'json_schema','json_schema':
        {'name':'answer','strict':True,'schema':schema}}
    config={k:payload[k] for k in ('model','temperature','seed','top_p','max_tokens')}
    config['schema']=schema
    start=time.perf_counter();events=[];parts=[];finish=None;ttft=None;done=False;error=None
    try:
        req=Request(url+'/v1/chat/completions',data=json.dumps(payload).encode(),
                    headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=120) as response:
            for raw in response:
                line=raw.decode().strip()
                if not line.startswith('data:'):continue
                data=line[5:].strip()
                events.append({'seconds':time.perf_counter()-start,'data':data})
                if data=='[DONE]':done=True;break
                item=json.loads(data)
                for choice in item.get('choices',[]):
                    token=choice.get('delta',{}).get('content') or ''
                    if token:
                        if ttft is None:ttft=time.perf_counter()-start
                        parts.append(token)
                    finish=choice.get('finish_reason') or finish
                if cut is not None and len(parts)>=cut:break
    except Exception as exc:error=type(exc).__name__+': '+str(exc)
    record={'id':name,'request':payload,'configuration':config,'config_sha256':identity(config),
        'events':events,'text':''.join(parts),'finish_reason':finish,'done':done,
        'complete':done and finish=='stop' and error is None,'error':error,
        'content_events':len(parts),'ttft_seconds':ttft,'seconds':time.perf_counter()-start,
        'injected_cut_after_content_events':cut}
    save(out/(name+'.json'),record)
    return record
