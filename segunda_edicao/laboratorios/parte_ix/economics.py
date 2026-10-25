"""L36: desenvolvimento, limiar congelado e políticas realmente executadas."""
from contextlib import ExitStack
import json,time
from .core import save,digest,expected,route,cache_key,useful_cost,percentile,Budget
from .runtime import server,http


def tasks(split):
    complex_count=10 if split=='shift' else 6
    rows=[]
    for i in range(12):
        # Identidades e valores distintos por partição; não dados humanos.
        offset={'development':0,'reserve':100,'shift':200}[split]
        active=i%4!=0;blocked=i%5==0;limit=50+offset
        value=limit+10 if i%3==0 else limit-10
        complexity=int(i<complex_count)
        if complexity:
            prompt=(f'Pedido {split}-{i}: conta {"ativa" if active else "inativa"}; valor {value}; '
                f'limite {limit}; bloqueio {"sim" if blocked else "nao"}. '
                'A regra geral aprova valores ate o limite, inclusive. Porem contas inativas devem ir para revisao; '
                'bloqueio tem precedencia e exige revisao mesmo com saldo. Caso contrario aprove. '
                'Retorne somente JSON com decisao igual a aprovar ou revisar.')
        else:
            prompt=(f'Pedido {split}-{i}. Aprovar se ativa=true E valor<=limite E bloqueada=false; '
                f'senao revisar. ativa={str(active).lower()}, valor={value}, limite={limit}, '
                f'bloqueada={str(blocked).lower()}. JSON: decisao=aprovar ou revisar.')
        rows.append(dict(id=f'{split}-{i}',split=split,active=active,blocked=blocked,limit=limit,value=value,
                         complexity=complexity,prompt=prompt,tenant='horizonte'))
    return rows


def infer(url,model,task):
    schema={'type':'object','properties':{'decisao':{'type':'string','enum':['aprovar','revisar']}},
            'required':['decisao'],'additionalProperties':False}
    payload=dict(model=model,messages=[{'role':'user','content':task['prompt']}],temperature=0,seed=36,max_tokens=64,
        response_format={'type':'json_schema','json_schema':{'name':'decision','strict':True,'schema':schema}})
    requested_ns=time.time_ns();start=time.perf_counter();response=http(url+'/v1/chat/completions',payload);elapsed=time.perf_counter()-start
    choice=response['choices'][0];value=None
    try:value=json.loads(choice['message']['content']).get('decisao')
    except (ValueError,TypeError):pass
    acceptable=choice['finish_reason']=='stop' and value==expected(task)
    return dict(task=task['id'],model=model,request=payload,response=response,elapsed=elapsed,requested_ns=requested_ns,
        value=value,reference=expected(task),acceptable=acceptable,review_required=task['complexity']==1,
        token_units=response['usage']['total_tokens']*(1 if model=='smol' else 3))


def choose_threshold(development,data,min_quality=.8):
    scores=[]
    indexed={(r['task'],r['model']):r for r in development}
    for threshold in [-1,0,1]:
        selected=[indexed[(t['id'],route(t['complexity'],threshold))] for t in data]
        quality=sum(r['acceptable'] for r in selected)/len(selected)
        scores.append(dict(threshold=threshold,quality=quality,units=sum(r['token_units'] for r in selected)))
    eligible=[s for s in scores if s['quality']>=min_quality]
    selected=min(eligible,key=lambda s:(s['units'],s['threshold'])) if eligible else scores[0]
    return dict(threshold=selected['threshold'],quality_gate_met=bool(eligible),scores=scores,
        selection='min token proxy under development quality >= 0.8; fallback all qwen if infeasible',
        training_ids=[t['id'] for t in data])


def totals(rows,host_per_hour=1.20,review_minutes=2,review_per_hour=60,storage_per_task=.001):
    # Autoencaminhamento observado = resposta "revisar" ou resposta inválida.
    # Correção avaliada pelo oráculo; encaminhado não é conclusão humana.
    completed=[r for r in rows if r['value']=='aprovar' and r['acceptable'] and not r.get('review_required',False)]
    pending=sum(r['value']!='aprovar' or r.get('review_required',False) for r in rows)
    seconds=sum(r['elapsed'] for r in rows if not r['cache_hit'])
    infrastructure=seconds*host_per_hour/3600
    review=pending*review_minutes*review_per_hour/60
    storage=len(rows)*storage_per_task
    cost=infrastructure+review+storage
    return dict(tasks=len(rows),correct_decisions=sum(r['acceptable'] for r in rows),
        useful_automatic=len(completed),human_pending=pending,
        unsafe_approvals=sum(r['value']=='aprovar' and not r['acceptable'] and not r.get('review_required',False) for r in rows),
        calls=sum(not r['cache_hit'] for r in rows),cache_hits=sum(r['cache_hit'] for r in rows),
        tokens=sum(r['response']['usage']['total_tokens'] for r in rows if not r['cache_hit']),
        serial_inference_seconds=seconds,p95_latency=percentile([r['elapsed'] for r in rows],.95),
        assumed_infrastructure_brl=infrastructure,assumed_storage_brl=storage,assumed_review_brl=review,
        assumed_total_brl=cost,cost_per_useful_auto=useful_cost(cost,len(completed)),
        quality=sum(r['acceptable'] for r in rows)/len(rows))


def run(out,runtime,lock):
    out.mkdir();development=tasks('development');reserve=tasks('reserve');shift=tasks('shift')
    save(out/'tasks.json',dict(development=development,reserve=reserve,shift=shift))
    all_rows=[];summaries=[]
    with ExitStack() as stack:
        urls={m:stack.enter_context(server(runtime,m,lock,out/('runtime_'+m))) for m in ['smol','qwen']}
        dev=[infer(urls[m],m,t) for t in development for m in ['smol','qwen']]
        save(out/'development.json',dev);decision=choose_threshold(dev,development)
        # Arquivo exclusivo persistido ANTES da primeira chamada de reserva.
        decision['frozen_ns']=time.time_ns();save(out/'threshold.json',decision)
        for split,data in [('reserve',reserve),('shift',shift)]:
            workload=data+[dict(data[0],id=data[0]['id']+'-repeat'),dict(data[-1],id=data[-1]['id']+'-repeat')]
            for policy in ['smol','qwen','routed_cache']:
                cache={};rows=[];budget=Budget(1000000)
                for task in workload:
                    model=route(task['complexity'],decision['threshold']) if policy=='routed_cache' else policy
                    key=cache_key(task['tenant'],task['prompt'],model,'rules-v1','decision-v1')
                    if policy=='routed_cache' and key in cache:
                        # Cronometrar lookup; não reutilizar latência histórica como latência do hit.
                        begin=time.perf_counter();row=dict(cache[key]);elapsed=time.perf_counter()-begin
                        row.update(task=task['id'],elapsed=elapsed,cache_hit=True)
                    else:
                        # Contabilidade em unidades experimentais, não preço contratado.
                        amount=20000;assert budget.reserve(task['id'],amount)
                        row=infer(urls[model],model,task);budget.settle(task['id'],row['token_units'])
                        row['cache_hit']=False
                        if row['response']['choices'][0]['finish_reason']=='stop':cache[key]=dict(row)
                    rows.append(row)
                item=dict(split=split,policy=policy,**totals(rows));summaries.append(item)
                all_rows.append(dict(split=split,policy=policy,rows=rows,budget_spent_units=budget.spent))
    save(out/'policies.json',all_rows);save(out/'result.json',summaries)
    sensitivity=[]
    for group in all_rows:
        for review_minutes in [0,2,5]:
            for host_per_hour in [.3,1.2,4.8]:
                sensitivity.append(dict(split=group['split'],policy=group['policy'],
                    review_minutes=review_minutes,host_per_hour=host_per_hour,
                    **totals(group['rows'],host_per_hour,review_minutes)))
    save(out/'sensitivity.json',sensitivity)
    b=Budget(100);assert b.reserve('unknown',80);b.settle('unknown',None)
    denied=not b.reserve('next',30);b.settle('unknown',70);accepted=b.reserve('next',30)
    save(out/'unknown_cost_control.json',dict(denied_while_unknown=denied,accepted_after_receipt=accepted,
        scope='deterministic accounting control; no timed-out inference was injected'))
