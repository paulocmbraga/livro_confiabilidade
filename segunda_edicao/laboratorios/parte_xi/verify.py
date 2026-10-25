"""Conferência offline de identidade e relações; não valida semântica humana."""
from pathlib import Path
import argparse,math,json
from laboratorios.parte_iv import core as ml
from laboratorios.parte_iv.calibration import calibrate
from .core import *

def close(a,b):
    if isinstance(a,float) or isinstance(b,float):assert math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-10),(a,b)
    elif isinstance(a,dict):
        assert set(a)==set(b)
        for k in a:close(a[k],b[k])
    elif isinstance(a,list):
        assert len(a)==len(b)
        for x,y in zip(a,b):close(x,y)
    else:assert a==b,(a,b)

def verify(root):
    root=Path(root);manifest=check_manifest(root);assert manifest['complete']
    d=load(root/'l41/data.json');v=load(root/'l41/variants.json');calls=load(root/'l41/calls.json')
    assert len(calls)==800 and len({(x['mode'],x['id']) for x in calls})==800
    m=load(root/'l41/model.json');cal=load(root/'l41/calibrator.json')
    assert set(r['id'] for r in d['train']).isdisjoint(r['id'] for r in d['reserve'])
    assert max(r['label_available'] for r in d['train'])<min(r['at'] for r in d['calibration'])
    for name in ['clean','unit_bad','recovered']:
        chosen=[x for x in calls if x['mode']==name];assert len(chosen)==200 and all(x['status']==200 for x in chosen)
        out=calibrate([x['body'] for x in chosen],cal);close(v[name]['outputs'],out)
        close(v[name]['metrics'],ml.metrics(d['reserve'],out));close(v[name]['cost'],cost(d['reserve'],out))
        close(v[name]['gate'],release_gate(v[name]['metrics'],name!='unit_bad',True))
    assert all(x['status']==422 for x in calls if x['mode']=='unit_guard')
    assert v['unit_guard']['rejected']==200 and not v['leaky']['gate']['allowed']
    close(v['clean']['outputs'],v['recovered']['outputs'])
    for name in ['leaky','old_on_shift','retrained']:
        model=load(root/'l41'/('leaky.json' if name=='leaky' else 'candidate.json' if name=='retrained' else 'model.json'))
        rows=d['reserve'] if name=='leaky' else d['shift_reserve'];pred=ml.predictions(model,rows)
        if name!='leaky':pred=calibrate(pred,load(root/'l41'/('candidate_calibrator.json' if name=='retrained' else 'calibrator.json')))
        close(pred,v[name]['outputs']);close(ml.metrics(rows,pred),v[name]['metrics'])
    rows=load(root/'l42/rows.json');assert len(rows)==24 and len({x['id'] for x in rows})==24
    for r in rows:
        assert r['structural']==answer_signal(r['text'],r['doc'])
        assert r['doc'] in corpus(r['doc']['version'])
        assert retrieve(corpus(r['doc']['version']),r['doc']['family'])[0]['document']==r['doc']
        if r['mode']=='race_protected':assert not r['delivered']
        if r['mode'].startswith('race'):assert r['timing']['begin']<r['timing']['updated']<r['timing']['end']
        if r['mode']=='fresh':assert r['delivered'] and bound(r['bundle'],r['current'])
    groups=load(root/'l42/summary.json')['groups']
    for mode,g in groups.items():
        subset=[x for x in rows if x['mode']==mode];assert g['n']==len(subset)==4
        assert g['structural']==sum(r['structural'] for r in subset)
        assert g['stale_exposed']==sum(r['delivered'] and not bound(r['bundle'],r['current']) for r in subset)
    ops=load(root/'l43/rows.json');assert len(ops)==18
    for r in ops:
        if r['mode']!='workflow':
            expected=proposal(r['planner'],r['task'])['accepted']
            if r['mode']=='team':expected=expected and proposal(r['specialist'],r['task'])['accepted']
            assert r['decision']['accepted']==expected
        assert bool(r['receipt'] and r['receipt']['receipt'])==r['decision']['accepted']
    assert load(root/'l43/before_restart.json')==load(root/'l43/after_restart.json')
    assert not load(root/'l43/migration_while_delegated.json')['ok']
    recovery=load(root/'l43/recovery.json');assert not recovery['blocked']['ok'] and recovery['migrated']['ok'] and recovery['ack']['ok']
    receipts=recovery['final']['receipts'];assert len({x['id'] for x in receipts})==len(receipts)
    assert sum(x['id']=='fault-43' for x in receipts)==1 and all(x['quantity']==1 for x in receipts)
    assert all(x['status']=='done' for x in recovery['final']['intents'])
    lost=load(root/'l43/lost_confirmation.json');assert any('effect_committed' in x for x in lost['lines']) and not any('"result"' in x for x in lost['lines'])
    epochs=[]
    for i in range(5):
        r=load(root/f'l44/epoch_{i}/result.json');assert r['epoch']==i and len(r['rag'])==len(r['agents'])==len(r['judgments'])==3
        close(r['ml_metrics'],ml.metrics(r['ml_rows'],r['ml_outputs']))
        for x in r['rag']:assert x['structural']==answer_signal(x['text'],x['doc'])
        for x in r['agents']:assert x['decision']==proposal(x['text'],x['task'])
        if i==4:assert all(not x['delivered'] for x in r['rag'])
        epochs.append(r)
    inference=[]
    for path in root.rglob('*.json'):
        r=load(path)
        if isinstance(r,dict) and 'response' in r and 'request' in r and isinstance(r['response'],dict) and 'choices' in r['response']:
            assert r['text']==r['response']['choices'][0]['message']['content'] and r['seconds']>0
            assert r['request']['temperature']==0 and r['request']['seed']==441
            assert r['response']['usage']['total_tokens']>0;inference.append((path,r))
    assert len(inference)==84,len(inference)
    for name in ['qwen','smol']:assert load(root/f'runtime_{name}/resources.json')['ended']
    env=load(root/'environment.json');assert env['human_participants']==0
    return dict(complete=True,files=len(manifest['files']),inference_calls=len(inference),
        tokens=sum(r['response']['usage']['total_tokens'] for _,r in inference),serving_requests=len(calls),
        epoch_count=5,wall_seconds=env['seconds'],human='pending',independent_reader='pending')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('capture',type=Path);a=p.parse_args();print(json.dumps(verify(a.capture)))
