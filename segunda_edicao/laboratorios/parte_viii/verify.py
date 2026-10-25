"""Verificação offline: integridade e relações entre evidências, sem abrir serviços."""
import argparse,json
from pathlib import Path
from .core import load,sha,check_manifest,digest

def require(condition,message):
    if not condition:raise ValueError(message)

def verify(root):
    root=Path(root);m=check_manifest(root);require(m['complete'],'incomplete')
    plan=load(root/'plan.json');require(plan['labs']==['L29','L30','L31','L32'],'labs')
    for rel,h in load(root/'inputs.json').items():
        if rel.endswith('.py'):require(sha(root/'source'/Path(rel).name)==h,'source')
    require(all(x['returncode']==0 for x in load(root/'cleanup.json')),'cleanup')
    infra=load(root/'infra.json');require(len(infra)==3 and len({x['name'] for x in infra})==3,'infrastructure')
    rows=load(root/'l29/results.json');stats=load(root/'l29/server_observation.json')
    require(len(rows)==14 and len({x['case'] for x in rows})==14,'http cardinality')
    for row in rows[:12]:
        s=stats[row['case']];attempts=row['attempts']
        require(s['calls']==len(attempts)==len(s['events']),'attempt reconciliation')
        require(len(s['effects'])<=1,'duplicate effect')
        useful=attempts[-1]['status']==200 and row['elapsed']<=row['deadline_seconds']
        require(useful==row['useful'],'useful deadline')
        if row['policy']=='budget':require(len(attempts)<=3,'global budget')
        if row['fault'] in ['always503','reject']:
            expected=27 if row['policy']=='layered' else 3 if row['fault']=='always503' else 1
            require(len(attempts)==expected,'retry amplification')
        if row['fault'] in ['drop_after','delay_after']:
            require(attempts[0]['status']==0 and len(s['effects'])==1,'ambiguous commit')
        if row['fault']=='rate' and row['policy']=='budget':
            require(all(s['events'][i+1]['at']-s['events'][i]['at']>=.99 for i in range(2)),'retry after')
    require(stats['hedge']['calls']==2 and rows[12]['loser_cancelled'] is False,'hedge loser')
    require(stats['breaker']['calls']==3 and rows[13]['rejected_open']==5,'breaker')
    require(rows[13]['admissions']==[True,True,False,False,False,False,False] and rows[13]['closed_after_probe'],'breaker transitions')
    offers=load(root/'l30/producer/result.json');before=load(root/'l30/before.json')
    inflight=load(root/'l30/inflight.json');after=load(root/'l30/after.json')
    actions=load(root/'l30/recovered/result.json')
    accepted=[x for x in offers if x['admitted']]
    require(len(offers)==10 and len(accepted)==8 and before['length']==8,'admission')
    require(inflight['pending']['pending']==1 and len(inflight['destination']['effects'])==1,'effect before ack')
    require(load(root/'l30/crash.json')['returncode']!=0,'consumer kill')
    require(any(x['source']=='claim' and x['intent']=='A1' and x['outcome']=='receipt' for x in actions),'redelivery')
    terminal=[x for x in actions if x['outcome']!='retry_pending']
    require(len(terminal)==8 and {x['message_id'] for x in terminal}=={x['message_id'] for x in accepted},'task conservation')
    expected={x['intent'] for x in accepted if x['kind']=='normal'}
    require({x['id'] for x in after['destination']['effects']}==expected,'effect conservation')
    require(after['length']==0 and after['pending']['pending']==0 and len(after['dead'])==1,'queue terminal states')
    poison=[x for x in actions if x['intent']=='P']
    require([x['deliveries'] for x in poison]==[1,2,3] and poison[-1]['outcome']=='dead_letter','poison bound')
    fair=load(root/'l30/fairness.json');require([x['first_b_position'] for x in fair]==[7,2],'fairness order')
    d=load(root/'l31/after.json');u=load(root/'l31/uncertain.json')
    require(len(u['source']['outbox'])==3 and not any(x['sent'] for x in u['source']['outbox']),'outbox pending')
    require('E0' in {x['id'] for x in u['destination']['effects']},'outbox remote committed')
    require([x['outcome'] for x in load(root/'l31/resumed/result.json')]==['duplicate','applied','applied'],'inbox replay')
    require(len(d['source']['jobs'])==3 and all(x['sent'] for x in d['source']['outbox']),'transaction conservation')
    require(d['optimistic']==dict(first=1,second=0),'optimistic conflict')
    for item in d['destination']['inbox']:
        require(item['body_hash']==digest(dict(id=item['event'],value='accepted')),'inbox body binding')
    require({x['event'] for x in d['destination']['inbox']}=={'E0','E1','E2'},'inbox membership')
    require(d['event_conflict_rejected'],'conflicting event')
    require(d['fencing'][0]['final']['value']=='old' and d['fencing'][1]['final']['value']=='new','fence value')
    require(d['fencing'][1]['old']['outcome']=='stale' and d['fencing'][1]['final']['token']==2,'fence token')
    require(d['reads'][0]['after']==d['reads'][0]['before']+1,'read committed')
    require(d['reads'][1]['after']==d['reads'][1]['before'],'repeatable read')
    require('E0-replay-control' in {x['id'] for x in d['destination']['effects']},'negative replay control')
    cat=load(root/'l32/catalog.json');a=load(root/'l32/after.json');b=load(root/'l32/before.json')
    restored=load(root/'l32/restored_before_reconcile.json');journal=load(root/'l32/admission_journal.json')
    require(sha(root/'l32/source.dump')==cat['database_hash'],'backup hash')
    require((root/'l32/source.dump').read_bytes().startswith(b'PGDMP'),'dump format')
    require(sha(root/'l32/index.json')==cat['index_hash'],'index hash')
    require(sha(root/'l32/corrupted.dump')!=cat['database_hash'] and a['corrupt_rejected'],'invalid backup')
    require(restored==b,'restore equality')
    lost=sorted({x['id'] for x in journal}-{x['id'] for x in restored['jobs']})
    require(a['lost_before_reconcile']==lost==['R0','R1'],'loss measurement')
    require(a['rpo_count_before']==len(lost) and a['rpo_count_after']==0,'rpo counts')
    require({x['id'] for x in a['source']['jobs']}=={'E0','E1','E2','R0','R1'},'recovery membership')
    require(all(x['status']=='confirmed' for x in a['source']['jobs']) and not a['backlog'],'recovery status')
    require(all(x['action']=='receipt_only' for x in a['actions']) and len(a['actions'])==3,'recovery no resend')
    require({x['id'] for x in a['destination']['effects']}==expected|{'E0','E1','E2','E0-replay-control','R0','R1'},'recovery effects')
    require(0<a['rto_database_seconds']<=a['rto_validated_seconds'],'rto boundary')
    require(load(root/'l32/rebuilt_index.json')=={x['id']:x['status'] for x in a['source']['jobs']},'rebuilt index')
    return dict(labs=4,http_policy_episodes=12,http_additional_experiments=2,
        queue_offers=10,queue_admitted=8,queue_effects=5,queue_dead_letter=1,exercises_expected=48,
        outbox_events=3,restored_jobs=5,rto_seconds=a['rto_validated_seconds'],
        limits=['One local host','One campaign, no population latency estimate','No power loss or broker restart',
                'Destination and journal survive database loss','No model inference','Independent reproduction pending'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('path',type=Path);a=p.parse_args()
    print(json.dumps(verify(a.path),ensure_ascii=False,indent=2))
