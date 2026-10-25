"""Diagnóstico pós-campanha: ordem do enum e ausência de gramática, sem ajuste oculto."""
from pathlib import Path
import argparse,copy,shutil,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from laboratorios.l11.core import load,save,sha,request,parse
from laboratorios.l11.runtime import http,server

def design():
    return [dict(id=f'{j}_{mode}_{order}',judge=j,pair='F01Q1',mode=mode,order=order,repeat=0,seed=1101)
            for j in ('qwen','smol') for mode in ('reverse_enum','free_json') for order in ('AB','BA')]

def payload(pair,t,rubric):
    r=request(pair,dict(t,mode='base'),rubric)
    if t['mode']=='reverse_enum':r['response_format']['json_schema']['schema']['properties']['choice']['enum']=['review','tie','B','A']
    else:del r['response_format']
    return r

def run(out):
    out.mkdir(parents=True,exist_ok=False);(out/'raw').mkdir()
    source=ROOT/'output/l11_principal_v01';shutil.copytree(source/'materials',out/'materials')
    shutil.copy2(Path(__file__),out/'diagnosticar_formato11.py')
    for name in ('core.py','runtime.py'):shutil.copy2(ROOT/'laboratorios/l11'/name,out/name)
    save(out/'plano_diagnostico.json',{'phase':'exploratory_post_primary','primary_manifest':sha(source/'manifesto.json'),
        'reason':'Primeira posição domina os julgamentos principais. Distinguir contribuição do enum e formato.',
        'selection':'F01Q1, primeiro par do desenho; mesmos textos e seed, sem seleção por acerto.',
        'design':design(),'expected_calls':8,'not_independent_holdout':True,
        'limits':'Um par. Enum e gramática não isolam todos os fatores; sem referência humana.'})
    pairs=load(out/'materials/pares.json');pair=next(p for p in pairs if p['id']=='F01Q1')
    lock=load(out/'materials/modelos.lock.json');plan=load(out/'materials/plano.json')
    rubric=(out/'materials/rubrica.txt').read_text(encoding='utf-8');summary=[]
    save(out/'state.json',{'status':'running','planned':8})
    for j in ('qwen','smol'):
        with server(ROOT/'.modelos/l11',j,lock,out,plan) as url:
            for t in [t for t in design() if t['judge']==j]:
                req=payload(pair,t,rubric);before=time.perf_counter();response=None;error=None
                try:response=http(url+'/v1/chat/completions',req,90)
                except Exception as e:error={'type':type(e).__name__,'detail':str(e)}
                parsed=parse(response,t['order'],error)
                row=dict(trial=t,request=req,response=response,error=error,parsed=parsed,seconds=time.perf_counter()-before)
                save(out/'raw'/(t['id']+'.json'),row);summary.append({'trial':t,'parsed':parsed})
                print(t['id'],parsed,flush=True)
    save(out/'summary.json',summary);save(out/'state.json',{'status':'complete','planned':8,'completed':8})
    save(out/'manifesto.json',{'files':{p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()}})

def verify(out):
    manifest=load(out/'manifesto.json')['files']
    assert set(manifest)=={p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file() and p.name!='manifesto.json'}
    for rel,h in manifest.items():assert sha(out/rel)==h
    plan=load(out/'plano_diagnostico.json');assert plan['design']==design() and plan['expected_calls']==8
    assert plan['primary_manifest']==sha(ROOT/'output/l11_principal_v01/manifesto.json')
    assert load(out/'state.json')=={'status':'complete','planned':8,'completed':8}
    assert {p.stem for p in (out/'raw').glob('*.json')}=={t['id'] for t in design()}
    pair=next(p for p in load(out/'materials/pares.json') if p['id']=='F01Q1')
    rubric=(out/'materials/rubrica.txt').read_text(encoding='utf-8');rows=[]
    for t in design():
        r=load(out/'raw'/(t['id']+'.json'));assert r['trial']==t and r['request']==payload(pair,t,rubric)
        assert r['parsed']==parse(r['response'],t['order'],r['error']);rows.append({'trial':t,'parsed':r['parsed']})
        if r['response'] is not None:
            u=r['response']['usage'];assert u['total_tokens']==u['prompt_tokens']+u['completion_tokens']
    assert rows==load(out/'summary.json')
    for j in ('qwen','smol'):assert load(out/(j+'_resources.json'))['process_ended']
    return {'calls':8,'invalid':sum(not r['parsed']['valid'] for r in rows),'phase':'exploratory_post_primary'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['run','verify']);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.mode=='run':run(a.out.resolve())
    print(verify(a.out.resolve()))
