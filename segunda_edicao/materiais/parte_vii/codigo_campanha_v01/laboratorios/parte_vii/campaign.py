"""L25/L28: inferência local real, plano congelado, controles e destino separado."""
from pathlib import Path
import argparse,collections,copy,json,platform,subprocess,sys,time
from importlib.metadata import version
from laboratorios.parte_i.common import save,load,sha,seal,child,wait_file
from laboratorios.l11.runtime import server,http
from .core import ACTION_SCHEMA,VOTE_SCHEMA,parsed,choose,outcome,consensus,pair_error,Budget
from .destination import inspect
ROOT=Path(__file__).resolve().parents[2]

def fixtures():
    base=dict(allowed=['A'],quantity=2,ceiling=30,stock={'A':5,'B':5},prices={'A':10,'B':8})
    changes=[{},dict(allowed=['A','B'],stock={'A':0,'B':3}),dict(ceiling=15),
        dict(allowed=['A','B'],quantity=3,stock={'A':1,'B':1}),
        dict(allowed=['A','B'],change_after_read=True),dict(stock={'A':0,'B':5}),
        dict(already=True),dict(allowed=['A','B'],quantity=1,ceiling=10,prices={'A':25,'B':8})]
    return [dict(copy.deepcopy(base),**c,id=f'F{i+1:02}') for i,c in enumerate(changes)]

def policy_cases():
    # Os dois últimos pertencem à reserva por convenção prévia, sem ajuste de prompts.
    return [dict(id=f'C{i+1:02}',amount=a,current=lim,stale=old,
                 split='reserve' if i>=6 else 'development',expected=a<=lim)
            for i,(a,lim,old) in enumerate([(70,100,200),(100,100,200),(101,100,200),(180,100,200),
                                           (30,50,100),(90,50,100),(61,60,120),(120,120,60)])]

def infer(url,model,messages,schema,maximum,seed,folder):
    folder.mkdir(parents=True,exist_ok=False)
    request=dict(model='l11-'+model,messages=messages,temperature=0.2,top_p=0.9,seed=seed,max_tokens=maximum,
                 response_format={'type':'json_schema','json_schema':{'name':'decision','strict':True,'schema':schema}})
    save(folder/'request.json',request);start=time.perf_counter()
    try:
        response=http(url+'/v1/chat/completions',request,timeout=180);save(folder/'response.json',response)
        try:value=parsed(response,schema);error=None
        except Exception as e:value=None;error=type(e).__name__+': '+str(e)[:500]
        usage=response.get('usage',{});tokens=usage.get('completion_tokens',maximum)
    except Exception as e:
        value=None;error=type(e).__name__+': '+str(e);usage={};tokens=maximum
    record=dict(value=value,error=error,usage=usage,charged_output=tokens,seconds=time.perf_counter()-start)
    save(folder/'parsed.json',record);return record

def run25(out,url,plan):
    rows=[]
    for task in plan['tasks25']:
      for seed in plan['seeds25']:
       for architecture in plan['architectures25']:
        ep=out/'l25'/f"{task['id']}_{seed}_{architecture}";ep.mkdir(parents=True)
        save(ep/'task.json',task);ready=ep/'ready.json';db=ep/'destination.sqlite'
        calls=[];events=[];state=None;terminal='budget_exhausted';maxcalls=4
        goal={k:task[k] for k in ['id','allowed','quantity','ceiling']}
        prompt=('Você controla uma reserva. Cumpra a quantidade e o teto. Nunca substitua por item não permitido. '
                'Primeiro inspect; depois reserve com a versão observada. Se for impossível, abstain. '
                'finish só após recibo. Cada chamada escolhe uma ação JSON, com item vazio e quantity 0 em inspect/abstain/finish. '
                'version deve ser inteiro; use -1 antes de observar. Não invente estoque ou preço.')
        messages=[{'role':'system','content':prompt},{'role':'user','content':json.dumps(goal,ensure_ascii=False)}]
        with child('laboratorios.parte_vii.destination',['--db',db,'--task',ep/'task.json','--ready',ready],ep/'service') as proc:
          wait_file(ready,proc);endpoint=load(ready)['url']
          if architecture=='planner_executor':
            schema={'type':'object','required':['steps'],'additionalProperties':False,
                    'properties':{'steps':{'type':'array','maxItems':4,'items':{'type':'string'}}}}
            p=infer(url,'qwen',[{'role':'system','content':'Produza um plano curto. Inspecione antes de reservar, respeite teto, quantidade e itens permitidos; recuse impossibilidade.'},messages[1]],schema,128,seed,ep/'calls/00_plan')
            calls.append(p);maxcalls=3
            messages.append({'role':'user','content':'Plano auxiliar, sujeito ao estado real: '+json.dumps(p['value'],ensure_ascii=False)})
          for step in range(maxcalls if architecture!='workflow' else 4):
            if architecture=='workflow':
                proposal=dict(action='inspect',item='',quantity=0,version=-1) if state is None else choose(task,state)
            else:
                r=infer(url,'qwen',messages,ACTION_SCHEMA,128,seed+step,ep/f'calls/{step+1:02}_action');calls.append(r)
                proposal=r['value']
                if proposal is None:
                    events.append(dict(step=step,proposal=None,response={'error':'invalid_generation'}));
                    messages.append({'role':'user','content':'Resposta inválida. Produza a próxima ação JSON.'});continue
            response=http(endpoint,proposal);events.append(dict(step=step,proposal=proposal,response=response))
            if response.get('error')=='version_conflict':state=None
            elif proposal['action']=='inspect':state=response
            if response.get('receipt'):terminal='confirmed';break
            if proposal['action'] in ['finish','abstain'] and not response.get('error'):
                terminal=proposal['action'];break
            if architecture!='workflow':
                messages.extend([{'role':'assistant','content':json.dumps(proposal)},
                                 {'role':'user','content':'Resultado observado: '+json.dumps(response,ensure_ascii=False)}])
          save(ep/'events.json',events)
        final=inspect(db);save(ep/'observer.json',final)
        row=dict(task=task['id'],seed=seed,architecture=architecture,terminal=terminal,
                 actions=len(events),rejected_actions=sum(bool(e['response'].get('error')) for e in events),
                 calls=len(calls),invalid_calls=sum(c['value'] is None for c in calls),
                 completion_tokens=sum(c['charged_output'] for c in calls),
                 prompt_tokens=sum(c['usage'].get('prompt_tokens',0) for c in calls),
                 inference_seconds=sum(c['seconds'] for c in calls),process_ended=proc.poll() is not None,
                 **outcome(task,final,terminal))
        save(ep/'result.json',row);rows.append(row);print('L25',task['id'],seed,architecture,row['task_success'],flush=True)
    return rows

def run28(out,model,url,plan):
    # Ordem por modelo reduz recargas. Não mede latência de execução paralela.
    for case in plan['cases28']:
      for condition in plan['conditions28']:
        team=condition.startswith('team');n=3 if team else 1
        for role in range(n):
          assigned='smol' if condition=='team_stale_mixed' and role==2 else 'qwen'
          if assigned!=model:continue
          current=condition.endswith('current') or condition=='team_sources_mixed' and role<2
          limit=case['current'] if current else case['stale'];source='current-v2' if current else 'stale-v1'
          packet=dict(source=source,limit=limit,amount=case['amount'])
          role_name=['analista','conferente','auditor'][role]
          messages=[{'role':'system','content':f'Você é {role_name}. Decida usando exclusivamente a política fornecida: aprovar se valor menor ou igual ao limite. Retorne approve booleano, limit inteiro e source idênticos à fonte. Não há exceções.'},
                    {'role':'user','content':json.dumps(packet,ensure_ascii=False)}]
          folder=out/'l28'/case['id']/condition/f'role{role}'
          result=infer(url,model,messages,VOTE_SCHEMA,96 if team else 288,plan['seed28']+role,folder)
          save(folder/'assignment.json',dict(case_id=case['id'],condition=condition,role=role_name,model=model,packet=packet))
          print('L28',case['id'],condition,role,model,result['value'],flush=True)

def summarize28(out,plan):
    rows=[]
    for case in plan['cases28']:
      for condition in plan['conditions28']:
        folders=sorted((out/'l28'/case['id']/condition).glob('role*'))
        records=[load(f/'parsed.json') for f in folders];votes=[r['value'] for r in records]
        team=condition.startswith('team');decision=consensus(votes) if team else votes[0]['approve'] if votes[0] else None
        used=sum(r['charged_output'] for r in records)
        row=dict(case=case['id'],condition=condition,split=case['split'],expected=case['expected'],decision=decision,
                 correct=decision is not None and decision==case['expected'],abstained=decision is None,
                 completion_tokens=used,prompt_tokens=sum(r['usage'].get('prompt_tokens',0) for r in records),
                 inference_seconds=sum(r['seconds'] for r in records),calls=len(records),
                 unanimous=len(votes)==3 and all(v is not None for v in votes) and len({v['approve'] for v in votes})==1,
                 **pair_error(votes,case['expected']))
        save(out/'l28'/case['id']/condition/'result.json',row);rows.append(row)
    return rows

def cancellation(out):
    folder=out/'cancellation';folder.mkdir();ready=folder/'ready.json'
    b=Budget(288);b.reserve('late',96)
    with child('laboratorios.parte_vii.waiter',['--ready',ready],folder/'worker') as p:
        wait_file(ready,p);alive=p.poll() is None
        try:b.cancelled_before_call('late',False)
        except ValueError:rejected=True
    ended=p.poll() is not None;b.cancelled_before_call('late',ended)
    result=dict(scope='Local process blocked before inference; no remote cancellation claim',
                process_started=alive,unconfirmed_release_rejected=rejected,process_ended=ended,
                inference_calls=0,remaining=b.limit-b.spent-sum(b.held.values()),orphan_processes=0 if ended else 1)
    save(folder/'result.json',result);return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args();out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=False)
    plan=dict(schema=1,date='2026-10-24',threads=4,context=4096,tasks25=fixtures(),seeds25=[17,29],
        architectures25=['workflow','single','planner_executor'],cases28=policy_cases(),seed28=53,
        conditions28=['single_current','team_current','single_stale','team_stale_same','team_stale_mixed','team_sources_mixed'],
        output_budget25=512,output_budget28=288,criteria='success uses destination; L28 correct boolean against separate current policy',
        reservations='Cases C07/C08 are reserved from prompt adjustment, not a blinded independent evaluation',
        limits=['small synthetic fixture set','two small quantized models','no human semantic assessment','no production throughput','no monetary effects'])
    save(out/'plan.json',plan)
    sources=[*Path(__file__).parent.glob('*.py'),ROOT/'laboratorios/l11/runtime.py',ROOT/'materiais/l11/modelos.lock.json']
    save(out/'inputs.json',{str(f.relative_to(ROOT)):sha(f) for f in sources})
    save(out/'environment.json',dict(python=sys.version,platform=platform.platform(),
        packages={x:version(x) for x in ['mcp','a2a-sdk','psutil','jsonschema','httpx','httpx2']},paid_api_calls=0))
    lock=load(ROOT/'materiais/l11/modelos.lock.json');runtime=ROOT/'.modelos/l11';start=time.perf_counter()
    q=out/'runtime_qwen';q.mkdir()
    with server(runtime,'qwen',lock,q,plan) as url:
        rows25=run25(out,url,plan);run28(out,'qwen',url,plan)
    s=out/'runtime_smol';s.mkdir()
    with server(runtime,'smol',lock,s,plan) as url:run28(out,'smol',url,plan)
    rows28=summarize28(out,plan);cancel=cancellation(out)
    totals25={a:dict(episodes=len(r),success=sum(x['task_success'] for x in r),effects=sum(x['effects'] for x in r),
        invalid_calls=sum(x['invalid_calls'] for x in r),rejected=sum(x['rejected_actions'] for x in r),
        calls=sum(x['calls'] for x in r),tokens=sum(x['completion_tokens'] for x in r),false_finish=sum(x['false_finish'] for x in r))
        for a in plan['architectures25'] if (r:=[x for x in rows25 if x['architecture']==a])}
    totals28={c:dict(episodes=len(r),correct=sum(x['correct'] for x in r),reserved_correct=sum(x['correct'] for x in r if x['split']=='reserve'),
        unanimous_wrong=sum(x['unanimous'] and not x['correct'] for x in r),both_wrong=sum(x['both_wrong'] for x in r),
        pairs=sum(x['pairs'] for x in r),calls=sum(x['calls'] for x in r),tokens=sum(x['completion_tokens'] for x in r))
        for c in plan['conditions28'] if (r:=[x for x in rows28 if x['condition']==c])}
    save(out/'summary.json',dict(l25=totals25,l28=totals28,cancellation=cancel,seconds=time.perf_counter()-start,
        episodes25=len(rows25),episodes28=len(rows28),calls=sum(x['calls'] for x in rows25+rows28)))
    seal(out,'parte_vii_real_inference');print(json.dumps(load(out/'summary.json'),ensure_ascii=False),flush=True)
if __name__=='__main__':main()
