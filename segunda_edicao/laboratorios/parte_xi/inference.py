"""Inferência HTTP real, sem reparo silencioso de saídas."""
import time
from laboratorios.parte_ix.runtime import http
from .core import save
ANSWER={'type':'object','properties':{'limite':{'type':'integer'},'fonte':{'type':'string'}},'required':['limite','fonte'],'additionalProperties':False}
PLAN={'type':'object','properties':{'action':{'type':'string','enum':['reserve','hold']},'quantity':{'type':'integer'}},'required':['action','quantity'],'additionalProperties':False}
JUDGE={'type':'object','properties':{'approved':{'type':'boolean'}},'required':['approved'],'additionalProperties':False}

def infer(url,model,prompt,schema,out,maximum=100):
    request=dict(model=model,messages=[{'role':'user','content':prompt}],temperature=0,seed=441,
        max_tokens=maximum,response_format={'type':'json_schema','json_schema':{'name':'result','strict':True,'schema':schema}},cache_prompt=False)
    start=time.perf_counter();response=http(url+'/v1/chat/completions',request,timeout=90)
    result=dict(request=request,response=response,seconds=time.perf_counter()-start,
        text=response['choices'][0]['message']['content'],finish=response['choices'][0]['finish_reason'])
    save(out,result);return result
