"""Reconciliação offline: conferência de capturas, sem gerar ou repetir efeitos."""
from pathlib import Path
import json,collections
from laboratorios.parte_i.common import load,sha,check_manifest
from .core import outcome,consensus,pair_error
from .destination import inspect

def verify(root):
    root=Path(root);manifest=check_manifest(root);assert manifest['complete']
    plan=load(root/'plan.json');summary=load(root/'summary.json');rows=[];calls=0
    expected={f"{t['id']}_{s}_{a}" for t in plan['tasks25'] for s in plan['seeds25'] for a in plan['architectures25']}
    assert {p.name for p in (root/'l25').iterdir()}==expected
    for episode in sorted((root/'l25').iterdir()):
        task=load(episode/'task.json');result=load(episode/'result.json');observed=load(episode/'observer.json')
        assert inspect(episode/'destination.sqlite')==observed,'database_snapshot'
        assert all(result[k]==v for k,v in outcome(task,observed,result['terminal']).items()),'destination_outcome'
        records=list((episode/'calls').glob('*/parsed.json'));calls+=len(records)
        assert sum(load(p)['charged_output'] for p in records)==result['completion_tokens']<=512
        assert result['calls']==len(records) and result['process_ended']
        assert not result['duplicate_effects'] and not result['forbidden_effects']
        rows.append(result)
    for arch,totals in summary['l25'].items():
        rr=[r for r in rows if r['architecture']==arch]
        assert totals['episodes']==len(rr)==16
        for a,b in [('success','task_success'),('calls','calls'),('tokens','completion_tokens'),('false_finish','false_finish')]:assert totals[a]==sum(x[b] for x in rr)
    rows28=[]
    for case in plan['cases28']:
      for condition in plan['conditions28']:
        folder=root/'l28'/case['id']/condition;result=load(folder/'result.json')
        records=[load(p) for p in sorted(folder.glob('role*/parsed.json'))];votes=[r['value'] for r in records]
        decision=consensus(votes) if condition.startswith('team') else votes[0]['approve'] if votes[0] else None
        assert result['decision']==decision and result['expected']==(case['amount']<=case['current'])
        assert result['correct']==(decision is not None and decision==case['expected'])
        assert sum(r['charged_output'] for r in records)==result['completion_tokens']<=288
        for k,v in pair_error(votes,case['expected']).items():assert result[k]==v
        calls+=len(records);rows28.append(result)
    for condition,totals in summary['l28'].items():
        rr=[r for r in rows28 if r['condition']==condition]
        assert totals['episodes']==len(rr)==8
        for a,b in [('correct','correct'),('calls','calls'),('tokens','completion_tokens'),('both_wrong','both_wrong'),('pairs','pairs')]:assert totals[a]==sum(x[b] for x in rr)
    assert summary['calls']==calls and len(rows28)==48
    for p in root.rglob('request.json'):
        request=load(p);response=p.with_name('response.json');parsed=p.with_name('parsed.json')
        if response.exists():
            usage=load(response)['usage'];assert usage['completion_tokens']==load(parsed)['charged_output']<=request['max_tokens']
    cancel=load(root/'cancellation/result.json');assert cancel['process_ended'] and cancel['remaining']==288 and cancel['inference_calls']==0
    return dict(episodes25=len(rows),episodes28=len(rows28),calls=calls,files=len(manifest['files']),manifest_sha256=sha(root/'manifesto.json'))

def protocols(root):
    root=Path(root);m=check_manifest(root);assert m['complete']
    s=load(root/'summary.json');assert all(v is True for k in ['mcp','a2a'] for v in s[k].values())
    d=load(root/'mcp/disconnect.json');assert d['status']==200 and d['closed_before_final'] and any('effect_committed' in l for l in d['lines'])
    assert load(root/'mcp/effect_I27.json')['intent']=='I27'
    r=load(root/'mcp/reconciled.json');receipt=json.loads(r['content'][0]['text'])['receipt'];assert receipt==load(root/'mcp/effect_I27.json')
    assert load(root/'mcp/old_schema_result.json')['isError']
    task=load(root/'a2a/final_task.json');assert task['status']['state']=='TASK_STATE_COMPLETED'
    assert load(root/'a2a/independent_get.json')['body']['result']==task
    assert s['callback']['statuses']==['accepted','duplicate','binding_rejected','old_event','terminal_regression','binding_rejected']
    assert s['callback']['wrong_audience_status']==401
    return dict(files=len(m['files']),manifest_sha256=sha(root/'manifesto.json'),checks=s)
