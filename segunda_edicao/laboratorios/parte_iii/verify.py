"""Conferência offline de identidades, inventário e relações; não repete efeitos."""
from pathlib import Path
from contextlib import closing
import argparse,json,sqlite3
from laboratorios.parte_i.common import ROOT,check_manifest,load,sha,digest
from . import l09,l10,l12

def verify(path):
    path=Path(path);manifest=check_manifest(path)
    if manifest.get('complete') is not True:raise ValueError('incomplete')
    assert load(path/'l09/operations.json')==l09.operations()
    summaries={}
    for variant in l09.VARIANTS:
        folder=path/'l09'/variant;rows=load(folder/'observations.json')
        assert len(rows)==40 and [r['request'] for r in rows]==l09.operations()
        summaries[variant]={'independent':l09.analyze(rows),'shared_rounding':l09.analyze(rows,True),
                            'self_consistency_only':all(r['observed']['balance']==r['state']['balance'] for r in rows)}
        with closing(sqlite3.connect(f'file:{(folder/"ledger.sqlite").as_posix()}?mode=ro',uri=True)) as db:
            assert db.execute('SELECT balance FROM account').fetchone()[0]==rows[-1]['state']['balance']
    assert summaries==load(path/'l09/summary.json')
    assert summaries['correct']['independent']['decision']=='pass'
    assert all(summaries[v]['independent']['decision']=='fail' for v in l09.VARIANTS[1:])
    assert summaries['rounding']['shared_rounding']['decision']=='pass'
    assert load(path/'l10_fixture.json')==l10.fixture()
    out=path/'l12';plan=load(path/'materials/plano.json')['L12'];cases=l12.cases()
    assert load(out/'private_cases.json')==cases
    budget=l12.Budget(plan['calls_budget'])
    for c in cases:assert budget.reserve(c['id'])=='reserved'
    assert budget.reserve('T09')=='quota_rejected'
    assert load(out/'budget.json')=={'limit':8,'events':budget.events}
    assert load(out/'not_admitted.json')=={'case':'T09','reason':'quota_rejected','calls_reserved':8}
    lock=load(out/'lock.json');identity=digest({'weights':lock['downloads'][0]['sha256'],'runtime':lock['server_sha256'],
          'request_code':sha(path/'code/l12.py'),'plan':plan})
    expected=[{'attempt':r['id']+'-1','case':r['id'],'candidate':identity,'judge':'exact-v1'} for r in cases]
    expected.append({'attempt':'T07-2','case':'T07','candidate':identity,'judge':'exact-v1'})
    assert load(out/'admitted.json')==expected
    assert load(out/'collector_config.json')=={'expected':expected}
    assert load(out/'evaluator_config.json')=={'cases':cases}
    collector=l12.Collector(expected);raws=[];callbacks=[]
    assert len(list(out.glob('T*/raw.json')))==8
    for case in cases:
        folder=out/case['id'];raw=load(folder/'raw.json');raws.append(raw)
        assert raw['request']==l12.request_for(case)
        assert raw['seconds']>=0
        mode=plan['faults'][case['id']];text=l12.consumed_text(raw,mode=='truncated_consumer')
        version='exact-v2' if mode=='judge_change' else 'exact-v1'
        evaluation=l12.evaluate(text,case,version)|{'judge':version,'case':case['id'],'input_sha256':digest(text)}
        evreq={'case':case['id'],'judge':version,'text':text}
        assert load(folder/'evaluation.json')=={'request':evreq,'response':evaluation}
        attempt=case['id']+'-2' if case['id']=='T07' else case['id']+'-1'
        callback=next(e for e in expected if e['attempt']==attempt)|{'judge':version,'output_sha256':digest(text),'valid':evaluation['valid'],'correct':evaluation['correct']}
        if mode=='candidate_mismatch':callback['candidate']='other-candidate'
        assert load(folder/'callback.json')==callback
        callbacks.append(callback)
        if mode!='delayed_callback':
            assert load(folder/'delivery.json')==collector.callback(callback)
            if mode=='duplicate_callback':assert load(folder/'duplicate_delivery.json')==collector.callback(callback)
    assert load(out/'before_close.json')==collector.snapshot()
    collector.closed=True;assert load(out/'closure.json')==collector.snapshot()
    assert load(out/'late_delivery.json')==collector.callback(callbacks[2])
    assert load(out/'final_collector.json')==collector.snapshot()
    # Registro independente do serviço confirma o que recebeu e devolveu.
    ev_events=[load(p) for p in sorted((out/'evaluator').glob('event_*.json'))]
    assert len(ev_events)==8
    for case,event in zip(cases,ev_events):
        evaluation=load(out/case['id']/'evaluation.json')
        assert event=={'path':'/evaluate',**evaluation}
    col_events=[load(p) for p in sorted((out/'collector').glob('event_*.json'))]
    assert len(col_events)==10
    events=collector.events
    assert [e['response'] for e in col_events if e['path']=='/callback']==events
    assert all(e['request']==e['response']['payload'] for e in col_events if e['path']=='/callback')
    processes=load(out/'processes.json');assert len(processes)==10
    assert sum(r['exit_code']==86 for r in processes)==1 and sum(r['exit_code']==87 for r in processes)==1
    assert sum(r['exit_code']==0 for r in processes)==8
    assert load(out/'T07/before_crash.json')['stage']=='before_inference'
    assert load(out/'T02/after_crash.json')['stage']=='durable_raw_before_callback'
    assert len({r['pid'] for r in processes})==10
    assert load(out/'qwen_resources.json')['process_ended'] is True
    states={r['id']:('evaluated' if any(p['valid'] for p in collector.received.values() if p['case']==r['id']) else 'invalid' if any(p['case']==r['id'] for p in collector.received.values()) else 'unknown') for r in cases}
    report={'identity':identity,'created':100,'expires':plan['expiry_logical'],'tasks':states,'human_semantic_qualification':False,
        'accepted_correct':sum(p['correct'] for p in collector.received.values()),'accepted_callbacks':len(collector.received),
        'attempts':9,'inference_requests':8,'worker_starts':10,'unknown_is_not_failure_rate':True,
        'attempt_states':l12.attempt_states(expected,collector.received)}
    report.update(release_now=l12.release(report,150,identity),release_later=l12.release(report,201,identity))
    assert report==load(out/'report.json')
    history=load(path/'historical_l11.json')
    assert history['manifest_sha256']==sha(ROOT/history['reuse']/'manifesto.json')
    execution=load(path/'execution.json')
    assert execution['new_llm_calls']==8 and execution['human_judgments']==0
    usage={'prompt_tokens':0,'completion_tokens':0,'missing_usage':0}
    for raw in raws:
        u=(raw.get('response') or {}).get('usage')
        if u is None:usage['missing_usage']+=1
        else:
            for k in ['prompt_tokens','completion_tokens']:usage[k]+=u[k]
    return {'L09':summaries,'L10':l10.fixture(),'L11':history,'L12':report,'L12_usage':usage,'execution':execution}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('capture',type=Path);a=p.parse_args();print(json.dumps(verify(a.capture),ensure_ascii=False,indent=2))
