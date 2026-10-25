"""Run the preregistered CPU campaign. A new output directory is mandatory."""
from pathlib import Path
import argparse,json,os,platform,shutil,subprocess,sys,time
from laboratorios.parte_i.common import save,load,sha,seal
from laboratorios.l11.runtime import server
from .core import order_contract,policy_metrics,judge_release,numeric,wer,identity,commit
from .inference import infer,ORDER,VALUE
P=Path(__file__).resolve().parents[2]

def memory_call(out,db,seq,**args):
    req=out/f'memory_{seq:03d}_request.json';save(req,args)
    start=time.perf_counter()
    r=subprocess.run([sys.executable,'-m','laboratorios.parte_v.memory','--db',str(db),'--request',str(req)],
        cwd=P,capture_output=True,text=True,encoding='utf-8',timeout=20,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    r.check_returncode();result=json.loads(r.stdout)
    save(out/f'memory_{seq:03d}_response.json',dict(result,seconds=time.perf_counter()-start))
    return result

def perception(out):
    from rapidocr_onnxruntime import RapidOCR
    import rapidocr_onnxruntime
    from pathlib import Path
    lock=load(P/'materiais/parte_v/modelos.lock.json');assets=P/'materiais/parte_v/entradas'
    models=P/'.modelos/parte_v'
    for name,digest in lock['inputs'].items():assert sha(assets/name)==digest,name
    for name,digest in lock['whisper_files'].items():assert sha(models/name)==digest,name
    for p in Path(rapidocr_onnxruntime.__file__).parent.rglob('*.onnx'):
        assert sha(p)==lock['ocr_models'][p.name],p.name
    engine=RapidOCR(intra_op_num_threads=4,inter_op_num_threads=1)
    records=[]
    for item in load(P/'materiais/parte_v/entradas.json'):
        path=assets/item['path'];start=time.perf_counter()
        if item['kind']=='ocr':
            result,times=engine(str(path));result=result or []
            text=' '.join(row[1] for row in result)
            details={'boxes':result,'stages_seconds':times}
        else:
            exe=models/'whisper-v1.8.7/Release/whisper-cli.exe'
            prefix=out/item['id']
            args=[str(exe),'-m',str(models/'ggml-tiny.bin'),'-f',str(path),'-l','pt',
                  '-t','4','-ng','-oj','-of',str(prefix)]
            r=subprocess.run(args,capture_output=True,timeout=120,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            (out/(item['id']+'_stdout.txt')).write_bytes(r.stdout)
            (out/(item['id']+'_stderr.txt')).write_bytes(r.stderr)
            r.check_returncode();raw=load(prefix.with_suffix('.json'))
            text=' '.join(row['text'].strip() for row in raw['transcription'])
            details={'args':args,'raw_file':prefix.name+'.json','returncode':r.returncode}
        record=dict(item,text=text,seconds=time.perf_counter()-start,details=details,
                    word_error_rate=wer(item['reference'],text),input_sha256=sha(path))
        save(out/(item['id']+'_perception.json'),record);records.append(record)
        print('perception',item['id'],repr(text),flush=True)
    return records

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    start=time.perf_counter();plan=load(P/'materiais/parte_v/plano.json');save(out/'plan.json',plan)
    code=out/'code';code.mkdir()
    for p in Path(__file__).parent.glob('*.py'):shutil.copy2(p,code/p.name)
    for file,name in [('laboratorios/parte_i/common.py','common_shared.py'),('laboratorios/l11/runtime.py','runtime_shared.py'),('laboratorios/l11/core.py','core_l11_shared.py')]:shutil.copy2(P/file,code/name)
    for file in ['modelos.lock.json','entradas.json']:shutil.copy2(P/'materiais/parte_v'/file,out/file)
    shutil.copy2(P/'materiais/l11/modelos.lock.json',out/'llm.lock.json')
    results={};complete=False
    try:
        per=out/'perception';per.mkdir();perceptions=perception(per)
        llm=out/'qwen';llm.mkdir();calls=out/'calls';calls.mkdir()
        with server(P/'.modelos/l11','qwen',load(out/'llm.lock.json'),llm,plan) as url:
            orders=[];ledger={};attempts=[]
            for quantity in plan['quantities']:
                for fmt in ['prompt','schema']:
                    for temperature in [0,.7]:
                        name=f'l17_q{quantity}_{fmt}_t{temperature}'
                        r=infer(url,calls,name,f'Extract exactly the signed integer quantity from this order: quantity={quantity}. Return only JSON with key quantity.',schema=ORDER if fmt=='schema' else None,temperature=temperature)
                        gate=order_contract(r['text'],r['complete'],r['config_sha256'],r['config_sha256'])
                        orders.append({'call':name,'quantity':quantity,'format':fmt,'temperature':temperature,
                            'gate':gate,'correct':gate.get('quantity')==quantity,'complete':r['complete']})
            prompt='Return JSON with quantity equal to 12.'
            cut=infer(url,calls,'l17_interrupted',prompt,schema=ORDER,cut=2)
            retry=infer(url,calls,'l17_retry',prompt,schema=ORDER)
            for r in [cut,retry]:
                gate=order_contract(r['text'],r['complete'],r['config_sha256'],r['config_sha256'])
                effect=commit(ledger,'order-001',{'quantity':gate['quantity']}) if gate['accepted'] else None
                attempts.append({'call':r['id'],'gate':gate,'effect':effect})
            mismatch=order_contract(retry['text'],retry['complete'],'old-configuration',retry['config_sha256'])
            # Deterministic replay of the same receipt, not another model inference.
            replay=commit(ledger,'order-001',{'quantity':12}) if retry['complete'] and numeric('{"value":12}')==12 and attempts[-1]['gate'].get('quantity')==12 else None
            results['L17']={'orders':orders,'attempts':attempts,'ledger':ledger,'replay':replay,'mismatched_configuration':mismatch}
            print('L17 complete',flush=True)
            answers=[]
            for case in plan['semantic_cases']:
                r=infer(url,calls,'l18_'+case['id'],case['prompt']+' Reply with the numerical answer only, or UNKNOWN if it is not determined by the information.',max_tokens=48)
                # Closed answer oracle. It does NOT grade explanatory natural language.
                answer=r['text'].strip().rstrip('.')
                correct=r['complete'] and answer in case['allowed']
                answers.append(dict(case,call=r['id'],answer=answer,correct=correct,complete=r['complete']))
            results['L18']={'answers':answers,'policies':{p:policy_metrics(answers,p) for p in ['all','evidence','reject_all']},
                'qualification':{'independent_reviewers':0,'heldout_adjudicated':False,'scope_matches':False,'threshold_validated':False},
                'judge_operational_release':False}
            print('L18 complete',flush=True)
            mem=out/'memory';mem.mkdir();db=mem/'state.sqlite';seq=0;episodes=[];checks=[]
            def mc(episode,action,**kw):
                nonlocal seq
                seq+=1
                return memory_call(mem,db,seq,actor=kw.pop('actor',episode),tenant=episode,key='limit',action=action,**kw)
            for e,(old,new) in enumerate(plan['memory_values'],1):
                tenant=f'episode{e}';mc(tenant,'put',value=str(old))
                summary=infer(url,calls,f'l19_summary_{e}',f'Summarize in one short sentence: The authorized limit for {tenant} is {old}. Preserve the exact number.',max_tokens=48)
                mc(tenant,'summarize',value=summary['text'])
                episode=[]
                for phase in ['initial','updated','deleted']:
                    if phase=='updated':mc(tenant,'put',value=str(new))
                    if phase=='deleted':mc(tenant,'delete')
                    current=mc(tenant,'read');safe=mc(tenant,'summary');unsafe=mc(tenant,'summary',unsafe=True)
                    expected=old if phase=='initial' else new if phase=='updated' else None
                    history=f'Turn 1: limit {old}.'
                    if phase!='initial':history+=f' Turn 2: replace previous limit by {new}.'
                    if phase=='deleted':history+=' Turn 3: the limit was deleted. Do not use either old value.'
                    contexts={'none':'No authorized limit is supplied.', 'history':history,
                        'summary_safe':safe['result']['value'] or ('Current authorized limit: '+str(current['result']['value']) if current['result']['value'] is not None else 'No authorized limit is supplied.'),
                        'summary_stale':unsafe['result']['value'] or 'No authorized limit is supplied.'}
                    for mode,context in contexts.items():
                        r=infer(url,calls,f'l19_e{e}_{phase}_{mode}',context+' What is the current authorized limit? Answer only the number or UNKNOWN if absent.',max_tokens=32)
                        # none intentionally has no fact; evaluate both task and context fidelity.
                        actual=r['text'].strip().rstrip('.')
                        task_ok=r['complete'] and actual==('UNKNOWN' if expected is None else str(expected))
                        context_expected=None if mode=='none' else expected
                        episode.append({'call':r['id'],'mode':mode,'phase':phase,'expected':expected,'answer':actual,
                            'task_correct':task_ok,'context_correct':r['complete'] and actual==('UNKNOWN' if context_expected is None else str(context_expected)),
                            'context_chars':len(context),'safe_summary':safe['result'],'current':current['result']})
                denied=mc(tenant,'read',actor='other-tenant');checks.append(denied)
                episodes.append({'id':tenant,'old':old,'new':new,'summary_call':summary['id'],'turns':episode})
            results['L19']={'episodes':episodes,'cross_tenant_checks':checks,'worker_commands':seq,
                           'storage_scope':'logical invalidation; not physical erasure of SQLite pages/backups'}
            print('L19 complete',flush=True)
            multimodal=[]
            for p in perceptions:
                pair={}
                for source in ['perception','oracle']:
                    text=p['text'] if source=='perception' else p['reference']
                    r=infer(url,calls,'l20_'+p['id']+'_'+source,
                        'Extract the final total amount, in reais, from this representation. Return JSON {"value": number}. Do not sum subtotal and total. Representation: '+text,schema=VALUE,max_tokens=48)
                    value=numeric(r['text']);pair[source]={'call':r['id'],'value':value,'complete':r['complete'],
                        'correct':r['complete'] and value is not None and abs(value-p['expected'])<.005}
                multimodal.append({'id':p['id'],'kind':p['kind'],'mode':p['mode'],'expected':p['expected'],
                    'wer':p['word_error_rate'],'pair':pair})
            results['L20']={'items':multimodal,'vision_llm_executed':False,'human_listeners':0,'perception_count':len(perceptions)}
            print('L20 complete',flush=True)
        judges=[];smol=out/'smol';smol.mkdir()
        with server(P/'.modelos/l11','smol',load(out/'llm.lock.json'),smol,plan) as url:
            for case in results['L18']['answers']:
                r=infer(url,calls,'l18_judge_'+case['id'],
                    'Is the proposed answer supported and correct? Reply PASS or FAIL only. Task: '+case['prompt']+' Proposed answer: '+case['answer'],model='smol',max_tokens=32)
                verdict=r['text'].strip().rstrip('.')
                judges.append({'case':case['id'],'call':r['id'],'verdict':verdict,'complete':r['complete'],
                    'agreement_with_closed_oracle':r['complete'] and verdict==('PASS' if case['correct'] else 'FAIL')})
        results['L18']['shadow_judgments']=judges
        human=out/'avaliacao_humana';human.mkdir()
        blind=[]
        for i,case in enumerate(sorted(results['L18']['answers'],key=lambda x:identity(x['id'])),1):
            blind.append({'blind_id':f'H{i:02d}','task':case['prompt'],'answer':case['answer']})
        save(human/'itens_cegos.json',blind)
        save(human/'chave_restrita.json',[{'blind_id':b['blind_id'],'case':c['id'],'closed_oracle':c['correct']} for b,c in zip(blind,sorted(results['L18']['answers'],key=lambda x:identity(x['id'])))])
        for reviewer in ['A','B']:save(human/f'revisor_{reviewer}.json',[dict(x,correctness=None,support=None,clarity=None,decision=None,comment=None) for x in blind])
        save(out/'results.json',results);complete=True
    except Exception as e:
        save(out/'failure.json',{'type':type(e).__name__,'message':str(e)});raise
    finally:
        save(out/'resources.json',{'seconds':time.perf_counter()-start,'python':platform.python_version(),
            'platform':platform.platform(),'paid_api_calls':0,'gpu_used':False,'human_evaluators':0,
            'cpu_threads':plan['threads'],'complete':complete})
        seal(out,'parte_v',complete=complete)
    print({'out':str(out),'seconds':time.perf_counter()-start},flush=True)
if __name__=='__main__':main()
