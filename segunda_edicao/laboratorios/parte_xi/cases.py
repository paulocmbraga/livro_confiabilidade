"""Novas execuções ponta a ponta sobre mecanismos das Partes IV, VII e IX."""
from pathlib import Path
import copy,time,threading,json
from concurrent.futures import ThreadPoolExecutor
from laboratorios.parte_i.common import child,wait_file
from laboratorios.parte_iv import core as ml
from laboratorios.parte_iv.calibration import fit_calibrator,calibrate,reliability
from laboratorios.parte_x.service import request
from .core import *
from .inference import infer,ANSWER,PLAN,JUDGE

def run41(out):
    out.mkdir();started=time.perf_counter()
    specs=[('train',600,141,0),('calibration',160,142,10000),('reserve',200,143,15000),('shift_train',300,144,20000),('shift_calibration',100,145,24000),('shift_reserve',100,146,26000)]
    data={name:ml.generate(n,seed,name,start,shifted=name.startswith('shift')) for name,n,seed,start in specs}
    save(out/'data.json',data)
    prep=ml.preprocessor(data['train']);model=ml.fit(data['train'],prep);leaky=ml.fit(data['train'],prep,future=True)
    cal=fit_calibrator(ml.predictions(model,data['calibration']),data['calibration'])
    candidate=ml.fit(data['shift_train'],ml.preprocessor(data['shift_train']))
    candidate_cal=fit_calibrator(ml.predictions(candidate,data['shift_calibration']),data['shift_calibration'])
    save(out/'model.json',model);save(out/'leaky.json',leaky);save(out/'calibrator.json',cal)
    save(out/'candidate.json',candidate);save(out/'candidate_calibrator.json',candidate_cal)
    variants={};calls=[]
    with child('laboratorios.parte_iv.server',['--model',out/'model.json','--out',out/'serving'],out/'process') as proc:
        wait_file(out/'serving/ready.json',proc);url='http://127.0.0.1:'+str(load(out/'serving/ready.json')['port'])
        for mode in ['clean','unit_bad','unit_guard','recovered']:
            outputs=[]
            for i,original in enumerate(data['reserve']):
                row=copy.deepcopy(original)
                if mode in ('unit_bad','unit_guard'):
                    row['unit']='minute';row['age']=None if row['age'] is None else row['age']*60
                status,body=request(url,{'row':row,'mode':mode,'attempt':f'{mode}_{i:03d}'})
                calls.append(dict(mode=mode,id=row['id'],status=status,body=body))
                if status==200:outputs.append(body)
            if outputs:
                outputs=calibrate(outputs,cal);metric=ml.metrics(data['reserve'],outputs)
                variants[mode]=dict(metrics=metric,cost=cost(data['reserve'],outputs),gate=release_gate(metric,mode!='unit_bad',True),reliability=reliability(outputs,data['reserve']),outputs=outputs)
            else:variants[mode]=dict(rejected=len(data['reserve']),gate={'allowed':False})
    outputs=ml.predictions(leaky,data['reserve']);metric=ml.metrics(data['reserve'],outputs)
    variants['leaky']=dict(metrics=metric,cost=cost(data['reserve'],outputs),outputs=outputs,gate=release_gate(metric,True,False))
    for name,m,c in [('old_on_shift',model,cal),('retrained',candidate,candidate_cal)]:
        outputs=calibrate(ml.predictions(m,data['shift_reserve']),c);metric=ml.metrics(data['shift_reserve'],outputs)
        variants[name]=dict(metrics=metric,cost=cost(data['shift_reserve'],outputs),outputs=outputs,gate=release_gate(metric,True,True))
    save(out/'calls.json',calls);save(out/'variants.json',variants)
    save(out/'summary.json',dict(seconds=time.perf_counter()-started,serving_requests=len(calls),synthetic=True,
         recovered_equal=variants['clean']['outputs']==variants['recovered']['outputs'],human_transfer='pending'))
    return model,candidate,cal,candidate_cal,data

def rag_prompt(doc):
    return 'Responda somente JSON com limite inteiro em reais e fonte (ID exato). Use o documento, sem conhecimento externo. Documento: '+json.dumps(doc,ensure_ascii=False)

def run42(out,url,model):
    out.mkdir();start=time.perf_counter();rows=[];cache={}
    families=['viagem','hospedagem','alimentacao','taxi']
    for family in families:
        doc=retrieve(corpus('v1'),family)[0]['document'];r=infer(url,model,rag_prompt(doc),ANSWER,out/f'prime_{family}.json')
        cache[family]=r['text']
        rows.append(dict(id='prime_'+family,mode='prime',text=r['text'],doc=doc,bundle=dict.fromkeys(['corpus','index','cache','prompt'],'v1'),current='v1',delivered=True,structural=answer_signal(r['text'],doc)))
    for mode in ['stale_cache','mixed_index','race_unprotected','race_protected','fresh']:
        for family in families:
            bundle=dict.fromkeys(['corpus','index','cache','prompt'],'v2');current='v2'
            doc=retrieve(corpus('v2'),family)[0]['document'];timing={}
            if mode=='stale_cache':text=cache[family];bundle['cache']='v1';doc=retrieve(corpus('v1'),family)[0]['document']
            elif mode=='mixed_index':
                bundle['index']='v1';doc=retrieve(corpus('v1'),family)[0]['document']
                text=infer(url,model,rag_prompt(doc),ANSWER,out/f'{mode}_{family}.json')['text']
            elif mode.startswith('race'):
                doc=retrieve(corpus('v1'),family)[0]['document'];bundle=dict.fromkeys(bundle,'v1')
                # Controle de escalonamento local: atualização ocorre enquanto HTTP de inferência está em voo.
                with ThreadPoolExecutor(max_workers=1) as executor:
                    begun=time.perf_counter();future=executor.submit(infer,url,model,rag_prompt(doc),ANSWER,out/f'{mode}_{family}.json')
                    time.sleep(.05);updated=time.perf_counter();current='v2'
                    text=future.result()['text'];ended=time.perf_counter()
                timing=dict(begin=begun,updated=updated,end=ended,update_during_flight=begun<updated<ended)
            else:text=infer(url,model,rag_prompt(doc),ANSWER,out/f'{mode}_{family}.json')['text']
            valid=bound(bundle,current);delivered=valid if mode in ('race_protected','fresh') else True
            rows.append(dict(id=mode+'_'+family,mode=mode,text=text,doc=doc,bundle=bundle,current=current,
                delivered=delivered,version_valid=valid,structural=answer_signal(text,doc),timing=timing))
    save(out/'rows.json',rows)
    summary={mode:dict(n=sum(r['mode']==mode for r in rows),delivered=sum(r['mode']==mode and r['delivered'] for r in rows),
        stale_exposed=sum(r['mode']==mode and r['delivered'] and not bound(r['bundle'],r['current']) for r in rows),
        structural=sum(r['mode']==mode and r['structural'] for r in rows)) for mode in ['prime','stale_cache','mixed_index','race_unprotected','race_protected','fresh']}
    save(out/'summary.json',dict(groups=summary,seconds=time.perf_counter()-start,human_support='pending',load_profile='closed loop, 1 inference in flight; update concurrent'))

def run44(out,url,model,ml_cases,epochs):
    out.mkdir(parents=True,exist_ok=True);initial,candidate,cal,cal2,data=ml_cases
    for epoch in epochs:
        folder=out/f'epoch_{epoch}';folder.mkdir();start=time.perf_counter()
        context=dict(data='v1' if epoch==0 else 'v2',model='v1' if epoch<2 else 'v2',judge='J1' if epoch<3 else 'J2',dependency='D1' if epoch<4 else 'D2',contract='bounded-v1')
        rows=data['reserve'][:3] if epoch==0 else data['shift_reserve'][:3]
        predictions=calibrate(ml.predictions(initial if epoch<2 else candidate,rows),cal if epoch<2 else cal2)
        rag=[];agents=[];judgments=[]
        for i,family in enumerate(['viagem','hospedagem','alimentacao']):
            doc=retrieve(corpus('v1' if epoch==0 else 'v2'),family)[0]['document']
            response=infer(url,model,rag_prompt(doc),ANSWER,folder/f'rag_{i}.json')
            parsed=parse(response['text']);dependency_ok=bool(isinstance(parsed,dict) and (('limite' in parsed) if epoch<4 else ('limit_cents' in parsed)))
            rag.append(dict(doc=doc,text=response['text'],structural=answer_signal(response['text'],doc),dependency_ok=dependency_ok,delivered=dependency_ok))
            task=dict(quantity=[1,2,1][i],authorized=[True,True,False][i])
            plan=infer(url,model,'Reserve somente authorized=true e quantity=1. Caso contrario hold. Pedido: '+json.dumps(task),PLAN,folder/f'plan_{i}.json')
            decision=proposal(plan['text'],task);agents.append(dict(task=task,decision=decision,text=plan['text']))
            rule='Aprove se existe um numero na resposta.' if epoch<3 else 'Aprove somente se limite e fonte coincidem exatamente com o documento.'
            judged=infer(url,model,rule+' Documento: '+json.dumps(doc)+' Resposta: '+response['text'],JUDGE,folder/f'judge_{i}.json')
            judgments.append(dict(text=judged['text'],parsed=parse(judged['text']),reference=rag[-1]['structural'],rubric=context['judge']))
        save(folder/'result.json',dict(epoch=epoch,context=context,model_id=model,ml_rows=rows,ml_outputs=predictions,ml_metrics=ml.metrics(rows,predictions),rag=rag,agents=agents,judgments=judgments,seconds=time.perf_counter()-start,logical_time=f'epoch-{epoch}',real_days=False))
