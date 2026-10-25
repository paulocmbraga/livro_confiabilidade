"""Verifica hashes E relações: plano, requisição, retorno, parser e agregados."""
from pathlib import Path
import argparse, math
from .core import ROOT,load,sha,schedule,request,parse,summarize

def verify(out,origins=True):
    out=Path(out);manifest=load(out/'manifesto.json')['files']
    actual={p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file() and p.name!='manifesto.json'}
    assert actual==set(manifest),'inventário'
    for rel,expected in manifest.items():
        path=(out/rel).resolve()
        assert path.is_relative_to(out.resolve()),'caminho'
        assert sha(path)==expected,'hash: '+rel
    state=load(out/'state.json');assert state['status']=='complete'
    pairs=load(out/'materials/pares.json');plan=load(out/'materials/plano.json');lock=load(out/'materials/modelos.lock.json')
    assert sha(out/'materials/pares.json')==plan['pair_sha256']
    assert len(pairs)==40 and len({p['id'] for p in pairs})==40
    cal={p['family'] for p in pairs if p['split']=='calibration'}
    test={p['family'] for p in pairs if p['split']=='test'}
    assert len(cal)==len(test)==5 and not cal&test,'vazamento familiar'
    trials=schedule(pairs,state['smoke']);assert trials==load(out/'schedule.json')
    assert len(trials)==state['completed']==state['planned']==(4 if state['smoke'] else 400)
    assert {p.stem for p in (out/'raw').glob('*.json')}=={t['id'] for t in trials}
    rubric=(out/'materials/rubrica.txt').read_text(encoding='utf-8');rows=[]
    for t in trials:
        r=load(out/'raw'/(t['id']+'.json'));p=next(p for p in pairs if p['id']==t['pair'])
        assert r['trial']==t and r['request']==request(p,t,rubric),'requisição'
        assert r['parsed']==parse(r['response'],t['order'],r['error']),'parser'
        assert isinstance(r['seconds'],(int,float)) and math.isfinite(r['seconds']) and r['seconds']>=0
        if r['response'] is not None:
            u=r['response']['usage'];assert all(type(u[k]) is int and u[k]>=0 for k in ['prompt_tokens','completion_tokens','total_tokens'])
            assert u['total_tokens']==u['prompt_tokens']+u['completion_tokens'],'tokens'
        rows.append(r)
    for j in ('qwen','smol'):
        resource=load(out/(j+'_resources.json'));assert resource['process_ended']
        assert resource['runtime_sha256']==lock['server_sha256']
        assert resource['model_sha256']==next(x['sha256'] for x in lock['downloads'] if x['id']==j)
    if not state['smoke']:assert summarize(rows,pairs)==load(out/'summary.json'),'agregação'
    if origins:
        orig=load(out/'materials/origens.json')
        assert sha(ROOT/'output/l23_principal_v01/manifesto.json')==orig['capture_manifest_sha256']
        for rel,h in (orig['files']|orig['source_sha256']).items():assert sha(ROOT/rel)==h,'origem'
        for p in pairs:
            for c in p['candidates']:
                assert c['sha256']==orig['files'][c['origin']]
                assert c['text']==load(ROOT/c['origin'])['response']['choices'][0]['message']['content'],'candidato'
    return {'calls':len(rows),'invalid':sum(not r['parsed']['valid'] for r in rows),
            'source_files':80,'human_reference':'pending','semantic_qualification':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();print(verify(a.out))
