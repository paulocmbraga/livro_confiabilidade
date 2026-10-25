"""Observador offline: não envia HTTP, não conecta bancos e não repete efeitos."""
import argparse
from collections import Counter
from pathlib import Path
from .core import digest, load, save, sha


def analyze(snapshot):
    destination=snapshot['destination'];client=snapshot['client']
    effects=destination['effects']
    counts=Counter((r['tenant'],r['intent'],r['action']) for r in effects)
    duplicates=sum(max(0,n-1) for n in counts.values())
    balance=10+sum(r['quantity']*(1 if r['action']=='release' else -1) for r in effects)
    assert destination['stock'][0]['available']==balance,'stock_conservation'
    assert destination['stock'][0]['version']==len(effects),'version_effect_count'
    assert balance>=0,'negative_stock'
    ids={r['id']:r for r in effects}
    released=set()
    for effect in effects:
        if effect['action']=='release':
            original=ids.get(effect['original'])
            assert original and original['action']=='reserve','missing_original'
            assert original['quantity']==effect['quantity'],'wrong_compensation_amount'
            assert original['tenant']==effect['tenant'],'cross_tenant_compensation'
            assert effect['original'] not in released,'double_compensation'
            released.add(effect['original'])
    outbox={r['id']:r for r in client['outbox']}
    for job in client['jobs']:
        assert job['id'] in outbox,'job_without_outbox'
        if job['state']=='confirmed':
            receipt=job['receipt'];effect=ids[receipt['effect_id']]
            assert receipt['hash']==digest(job['request']),'receipt_payload'
            assert effect['intent']==job['request']['intent'],'receipt_intent'
            assert effect['tenant']==job['request']['tenant'],'receipt_tenant'
            assert receipt['key']==job['request']['key'],'receipt_key'
            assert not outbox[job['id']]['pending'],'confirmed_outbox_pending'
        elif job['state']=='unknown':
            assert job['receipt'] is None,'unknown_with_confirmation'
            assert outbox[job['id']]['pending'],'uncertainty_discarded'
        elif job['state']=='rejected':
            assert job['receipt']['effect']=='not_applied','rejection_without_proof'
            assert job['receipt']['hash']==digest(job['request']),'rejected_payload'
    return dict(effects=len(effects),duplicates=duplicates,stock=balance,
                states=sorted(r['state'] for r in client['jobs']),
                unknown=sum(r['state']=='unknown' for r in client['jobs']),
                compensations=len(released))


def verify(capture):
    manifest=load(capture/'manifesto.json')
    for name,expected in manifest['files'].items():
        assert sha(capture/name)==expected,'hash:'+name
    plan=load(capture/'plan.json');ids=[x['id'] for x in plan['cases']]
    assert len(ids)==len(set(ids))==24,'case_cardinality'
    assert {p.name for p in capture.iterdir() if p.is_dir() and p.name.startswith('P')}==set(ids)
    rows=[]
    for spec in plan['cases']:
        path=capture/spec['id'];observed=analyze(load(path/'final.json'))
        assert observed['effects']==spec['effects'],spec['id']+':effects'
        assert observed['stock']==spec['stock'],spec['id']+':stock'
        assert observed['states']==sorted(spec['states']),spec['id']+':states'
        assert observed['duplicates']==int(spec['control']),spec['id']+':duplicates'
        timeline=load(path/'timeline.json')
        assert timeline[-1]['name']=='episode_complete','incomplete_episode'
        assert all(x['returncode'] is not None for x in load(path/'processes.json')),'live_process'
        rows.append(dict(id=spec['id'],name=spec['name'],control=spec['control'],
                         **observed,seconds=timeline[-1]['seconds']))
    def snap(case,stage):return load(capture/case/(stage+'.json'))
    for case,marker in [('P02','drop_reply.ready.json'),('P04','before_commit.ready.json'),
                         ('P05','after_commit.ready.json'),('P06','a1.before_send.json'),('P07','a1.after_receive.json')]:
        assert (capture/case/marker).exists(),case+':fault_not_hit'
    assert not snap('P04','after_first_phase')['destination']['effects'],'precommit_effect_survived'
    assert len(snap('P05','after_first_phase')['destination']['effects'])==1,'postcommit_effect_missing'
    assert snap('P07','after_first_phase')['client']['jobs'][0]['state']=='unknown'
    for case in ('P08','P09'):
        overlap=load(capture/case/'overlap.json')
        assert overlap and all(x['blockers'] for x in overlap),'no_observed_overlap'
        timeline=load(capture/case/'timeline.json')
        event=next(x for x in timeline if x['name']=='database_block_observed')
        assert len(set(event['pids']))==2,'not_two_workers'
    old=load(capture/'P19/a1.json');new=load(capture/'P19/a2.json')
    assert old['token']==1 and new['token']==2 and not old['ledger_updated']
    assert old['reply']['reason']=='stale_fence' and new['outcome']=='confirmed'
    assert snap('P19','successor_confirmed')['client']['jobs']==snap('P19','final')['client']['jobs']
    for case in ('P22','P24'):
        before=snap(case,'after_first_phase');after=snap(case,'after_restore')
        assert before['destination']==after['destination'],'restore_changed_external_effect'
        assert not after['client']['jobs'] and not after['client']['outbox'],'restore_not_observed'
    assert snap('P22','final')['client']['control'][0]['admission'] is False
    pending=snap('P21','outbox_after_remote_commit')
    assert len(pending['destination']['effects'])==1 and pending['client']['outbox'][0]['pending']
    assert load(capture/'P11/a3.json')['reply']['reason']=='retention_expired'
    assert load(capture/'P12/a2.json')['status']==501
    assert load(capture/'P13/a2.json')['status']==503
    assert load(capture/'P23/a3.json')['status']==503
    for attempt in ('a2','a3'):
        r=load(capture/'P01'/(attempt+'.json'))
        assert r['cached'] and r['mode']=='local' and r['outcome']=='confirmed'
    assert snap('P01','after_first_phase')['client']['jobs']==snap('P01','final')['client']['jobs']
    return {'capture':capture.name,'episodes':len(rows),'matched_expected':len(rows),
            'protected':sum(not r['control'] for r in rows),'unsafe_controls':sum(r['control'] for r in rows),
            'final_unknown_jobs':sum(r['unknown'] for r in rows),'rows':rows,
            'limits':['One scheduled run per case, not a random traffic sample.',
                      'Local HTTP and PostgreSQL; no external supplier, LLM, power-loss or network-partition trial.',
                      'Observer reads destination; client can use only its receipt contract.',
                      'Same implementation team; independent reproduction pending.']}


def main():
    p=argparse.ArgumentParser();p.add_argument('capture',type=Path);p.add_argument('--out',type=Path)
    a=p.parse_args();result=verify(a.capture)
    if a.out:save(a.out,result)
    print({k:v for k,v in result.items() if k not in ('rows','limits')})


if __name__=='__main__':main()
