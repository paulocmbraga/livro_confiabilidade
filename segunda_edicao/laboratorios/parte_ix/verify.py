"""Recalcula os resultados a partir dos eventos e respostas preservados."""
from pathlib import Path
import argparse,json,math
from .core import *
from . import slo,serving,economics
from .campaign import flatten


def verify(root):
    root=Path(root);manifest=check_manifest(root)
    assert manifest['complete'] and load(root/'plan.json')['selection']=='all'
    counts={};report=load(root/'l33/result.json');spans=flatten(root/'l33/sink/traces.jsonl')
    assert spans==load(root/'l33/spans.json')
    for item in report:
        folder=root/'l33'/item['phase'];ledger=[];attempts=[]
        for role in ['client','service']:
            if (folder/role/'ledger.json').exists():
                ledger+=load(folder/role/'ledger.json');attempts+=load(folder/role/'exports.json')
        actual=reconcile(ledger,[s for s in spans if s['phase']==item['phase']],attempts)
        for key,value in actual.items():assert item[key]==value,(item['phase'],key)
        assert item['wrong_bindings']==0
    phases={r['phase']:r for r in report}
    assert phases['healthy']['received']==24 and phases['recovery']['received']==24
    assert phases['sampled']['planned_exclusions']==12 and phases['sampled']['lost']==0
    assert phases['outage']['received']==0 and phases['outage']['lost']==24
    assert phases['saturation']['lost']>0 and phases['saturation']['never_exported']>0
    assert load(root/'l33/cleanup.json')['removed']
    counts['traces_received']=len(spans)
    data=load(root/'l34/events.json');assert data==slo.events()
    views=load(root/'l34/evaluations.json')
    for row in views:assert row==dict(now=row['now'],**alert(data,row['now']))
    assert any(v['quality'] for v in views) and any(v['observation'] for v in views)
    assert not any(v['quality'] for v in views if v['now']<60)
    counts['event_rows']=len(data)
    serving_summary=load(root/'l35/result.json');inferences=0
    for item in serving_summary:
        folder=root/'l35'/item['mode'];rows=load(folder/'rows.json');calculated=serving.summary(rows)
        assert len(rows)==18 and {r['id'] for r in rows}=={t['id'] for t in serving.tasks()}
        for key,value in calculated.items():assert item[key]==value,(item['mode'],key)
        assert item['completed']+item['rejected']+item['errors']==18 and item['errors']==0
        assert load(folder/'runtime/resources.json')['ended']
        for row in rows:
            if row['status']!='completed':continue
            response=row['response'];assert response['usage']['completion_tokens']<=32
            assert response['ttft'] is not None and 0<=response['ttft']<=response['elapsed']
            assert response['finish'] in ['stop','length'];inferences+=1
    counts['serving_inferences']=inferences
    dataset=load(root/'l36/tasks.json');dev=load(root/'l36/development.json');threshold=load(root/'l36/threshold.json')
    calculated=economics.choose_threshold(dev,dataset['development'])
    for k,v in calculated.items():assert threshold[k]==v,k
    records=load(root/'l36/policies.json');summaries=load(root/'l36/result.json');calls=0
    for group,item in zip(records,summaries,strict=True):
        split=group['split'];indexed={t['id']:t for t in dataset[split]};rows=group['rows']
        assert len(rows)==14
        for row in rows:
            task=indexed[row['task'].removesuffix('-repeat')]
            choice=row['response']['choices'][0];value=json.loads(choice['message']['content'])['decisao']
            assert row['reference']==expected(task)
            assert row['review_required']==bool(task['complexity'])
            assert row['acceptable']==(choice['finish_reason']=='stop' and value==expected(task))
            assert row['value']==value
            assert row['model']==(route(task['complexity'],threshold['threshold']) if group['policy']=='routed_cache' else group['policy'])
            assert row['requested_ns']>threshold['frozen_ns']
            if not row['cache_hit']:calls+=1
        assert item==dict(split=split,policy=group['policy'],**economics.totals(rows))
    for m in ['qwen','smol']:assert load(root/'l36'/('runtime_'+m)/'resources.json')['ended']
    counts['economic_inferences']=len(dev)+calls
    counts['economic_policy_tasks']=sum(len(g['rows']) for g in records)
    counts['threshold_quality_gate_met']=threshold['quality_gate_met']
    return dict(manifest_sha256=sha(root/'manifesto.json'),files=len(manifest['files']),**counts)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('root',type=Path);a=ap.parse_args()
    print(json.dumps(verify(a.root),ensure_ascii=False))
