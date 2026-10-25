"""Recontagem de evidências e relações; não é replicação independente."""
from contextlib import closing
import sqlite3
from .core import *


def verify(root):
    m=check_manifest(root);assert m['complete']
    results=load(root/'results.json');events=load(root/'l37/events.json');models=load(root/'l37/models.json')
    assert len(events)==2400 and len({r['id'] for r in events})==2400
    training=load(root/'l37/training.json')
    assert fit(training['baseline'])==models['baseline'] and fit(training['retrain'])==models['candidate']
    assert len(training['reserve_ids'])==100
    for r in events:
        actual=models['baseline'] if r['cohort']<65 else models['alias_bad'] if 75<=r['cohort']<90 else models['candidate']
        assert r['model_sha256']==digest(actual) and r['prediction']==predict(actual,r['x'])
        assert r['y']==int(r['x']>(0 if r['cohort']<40 else .65))
    timeline=load(root/'l37/timeline.json');assert len(timeline)==130
    for t in timeline:assert t['quality']==mature(events,t['now'])
    r=results['l37'];assert r['raw']['bad']==sum(x['prediction']!=x['y'] for x in events)
    assert r['exposed']['bad']==sum(x['prediction']!=x['y'] and x['exposed'] for x in events)
    assert r['quality_false_alarms_before_change']==0
    paired=load(root/'l38/paired.json');assert release_gate(paired)==results['l38']['paired_gate']
    assert results['l38']['paired_gate']=={'pass':False,'bad':1,'critical_bad':1,'n':20}
    exposure=load(root/'l38/exposure.json');assert len(exposure)==20
    assert sum(x['candidate'] for x in exposure)==results['l38']['canary_exposed']==3
    assert not any(x['candidate'] for x in exposure[9:])
    for lab in ['l38','l39','l40']:
        final=load(root/lab/'final.json');journal=load(root/lab/'journal.json')
        assert final==[r['body'] for r in journal if r['path']=='/state'][-1]
        with closing(sqlite3.connect(root/lab/'state.sqlite')) as db:
            db.row_factory=sqlite3.Row
            assert final['tasks']==[dict(x) for x in db.execute('SELECT * FROM tasks ORDER BY id')]
            assert final['effects']==[dict(x) for x in db.execute('SELECT * FROM effects ORDER BY id')]
            assert final['config']==dict(db.execute('SELECT k,v FROM cfg').fetchall())
        assert all(r['ended']>=r['started']>=0 for r in journal)
        assert results[lab]==load(root/lab/'result.json')
    incident=load(root/'l39/journal.json');assert sum(r['status']=='transport_unknown' for r in incident)==1
    assert results['l39']['worker_exit']==23 and results['l39']['unknown_receipt_count']==1
    assert load(root/'l39/worker/server/committed_before_crash.json')['body']['id']=='unknown'
    assert results['l39']['human']==human_results(load(root/'l39/human/responses.json'))
    assert results['l39']['review_admitted']==3 and results['l39']['review_rejected']==5
    offered=[r for r in incident if r['path']=='/admit' and r['data']['id'].startswith('review')]
    assert len(offered)==8 and sum(r['status']==201 for r in offered)==3 and sum(r['status']==429 for r in offered)==5
    for role in ['coordenacao','operacao']:
        form=load(root/'l39/human'/role/'form.json')
        assert form['participant_id'] is None and form['decision'] is None and not form['consent']
    context=load(root/'l40/context.json');cases=load(root/'l40/cases.json')
    assert len(cases)==12 and sum(c['decision']['supported'] for c in cases)==1
    for c in cases:assert c['decision']==assess('no-open-effects',c['evidence'],context,20)
    assert results['l40']['open_tasks']==0 and results['l40']['receipt_readable']==200
    assert results['l37']==load(root/'l37/result.json')
    return {'files':len(m['files']),'tasks_l37':len(events),'labs':4,'human':'pending','manifest_sha256':sha(root/'manifesto.json')}
