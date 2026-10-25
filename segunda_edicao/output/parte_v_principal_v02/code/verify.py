"""Recompute relations, terminal events and task scores without new inference."""
from pathlib import Path
import argparse,json
from laboratorios.parte_i.common import load,check_manifest
from .core import identity,order_contract,policy_metrics,numeric,wer,judge_release

def verify(root):
    root=Path(root);m=check_manifest(root);assert m['complete']
    plan=load(root/'plan.json');r=load(root/'results.json')
    calls={p.stem:load(p) for p in (root/'calls').glob('*.json')}
    assert len(calls)==115,len(calls)
    for name,c in calls.items():
        assert c['id']==name and identity(c['configuration'])==c['config_sha256']
        text=[];finish=None;done=False
        times=[]
        for event in c['events']:
            times.append(event['seconds'])
            if event['data']=='[DONE]':done=True;continue
            for choice in json.loads(event['data']).get('choices',[]):
                text.append(choice.get('delta',{}).get('content') or '')
                finish=choice.get('finish_reason') or finish
        assert times==sorted(times)
        assert ''.join(text)==c['text'] and finish==c['finish_reason'] and done==c['done']
        assert c['complete']==(done and finish=='stop' and c['error'] is None)
    assert len(r['L17']['orders'])==20
    for q in r['L17']['orders']:
        c=calls[q['call']];g=order_contract(c['text'],c['complete'],c['config_sha256'],c['config_sha256'])
        assert q['gate']==g and q['correct']==(g.get('quantity')==q['quantity'])
    assert r['L17']['attempts'][0]['gate']['reason']=='incomplete'
    assert not r['L17']['mismatched_configuration']['accepted']
    a=r['L18']['answers'];assert len(a)==12
    for x in a:
        c=calls[x['call']];assert x['answer']==c['text'].strip().rstrip('.')
        assert x['correct']==(c['complete'] and x['answer'] in x['allowed'])
    assert r['L18']['policies']=={p:policy_metrics(a,p) for p in plan['policies']}
    assert not judge_release(r['L18']['qualification']) and not r['L18']['judge_operational_release']
    assert len(r['L18']['shadow_judgments'])==12
    for j in r['L18']['shadow_judgments']:
        c=calls[j['call']];case=next(x for x in a if x['id']==j['case'])
        assert j['verdict']==c['text'].strip().rstrip('.')
        assert j['agreement_with_closed_oracle']==(c['complete'] and j['verdict']==('PASS' if case['correct'] else 'FAIL'))
    assert len(r['L19']['episodes'])==3
    for e in r['L19']['episodes']:
        assert len(e['turns'])==12
        for t in e['turns']:
            c=calls[t['call']];assert t['answer']==c['text'].strip().rstrip('.')
            assert t['task_correct']==(c['complete'] and t['answer']==('UNKNOWN' if t['expected'] is None else str(t['expected'])))
            if t['phase']!='initial':assert t['safe_summary']=={'value':None,'valid':False,'unsafe':False}
    assert all(not x['ok'] and x['error']=='tenant mismatch' for x in r['L19']['cross_tenant_checks'])
    commands=list((root/'memory').glob('*_response.json'));assert len(commands)==r['L19']['worker_commands']==42
    for path in commands:assert load(path)['pid']>0
    assert len(r['L20']['items'])==15
    for item in r['L20']['items']:
        p=load(root/'perception'/(item['id']+'_perception.json'))
        assert item['wer']==wer(p['reference'],p['text'])
        for kind,pair in item['pair'].items():
            c=calls[pair['call']];value=numeric(c['text'])
            assert pair['value']==value and pair['complete']==c['complete']
            assert pair['correct']==(c['complete'] and value is not None and abs(value-item['expected'])<.005)
    for model in ['qwen','smol']:assert load(root/model/(model+'_resources.json'))['process_ended']
    human=0
    for reviewer in ['A','B']:
        forms=load(root/'avaliacao_humana'/f'revisor_{reviewer}.json');assert len(forms)==12
        for form in forms:
            for key in ['correctness','support','clarity','decision','comment']:assert form[key] is None
            human+=1
    return {'complete':True,'inferences':len(calls),'perception':15,'memory_processes':42,
            'planned_human_judgments':human,'human_judgments':0,'files':len(m['files'])}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();print(verify(a.out))
