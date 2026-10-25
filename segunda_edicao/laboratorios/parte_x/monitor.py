"""L37: modelos efetivamente ajustados; coortes e atrasos em tempo lógico."""
import random,time
from .core import *


def run(out):
    out.mkdir();start=time.perf_counter();rng=random.Random(3701)
    training=[{'x':rng.uniform(-1,1)} for _ in range(600)]
    for r in training:r['y']=int(r['x']>0)
    baseline=fit(training);bad_model={**baseline,'threshold':-.5,'kind':'altered-alias'}
    rows=[]
    for c in range(120):
        for j in range(20):
            x=rng.uniform(-1,1);y=int(x>(0 if c<40 else .65))
            rows.append(dict(id=f'{c}:{j}',cohort=c,x=x,z=rng.gauss(2 if c>=20 else 0,.2),y=y,
                arrives=c+(8 if j%5==0 else 2),revised_at=c+10,
                provisional=1-y if j%7==0 else y,feedback=(j%3==0 and x>.7),
                audit=random.Random(370000+c*20+j).random()<.25))
    train_new=[{'x':r['x'],'y':label_at(r,60)} for r in rows if 40<=r['cohort']<50]
    assert all(r['y'] is not None for r in train_new)
    candidate=fit(train_new)
    reserve=[r for r in rows if 50<=r['cohort']<55]
    reserve_error=sum(predict(candidate,r['x'])!=label_at(r,65) for r in reserve)/len(reserve)
    assert reserve_error<=.10
    save(out/'models.json',dict(baseline=baseline,candidate=candidate,alias_bad=bad_model))
    save(out/'training.json',dict(baseline=training,retrain=train_new,reserve_ids=[r['id'] for r in reserve]))
    timeline=[];streak=0;enabled=True;first_quality=None;sentinel_changes=[];seen=[]
    grid=[-.75,-.25,.25,.75]
    for c in range(130):
        if c==65:enabled=True
        if c==90:enabled=True
        actual=baseline if c<65 else bad_model if 75<=c<90 else candidate
        expected=baseline if c<65 else candidate
        sentinel=None
        if c<120 and c%5==0:
            sentinel=[predict(actual,x) for x in grid]!=[predict(expected,x) for x in grid]
            if sentinel:sentinel_changes.append(c);enabled=False
        v=mature(seen,c)
        alarm=v['n']>=100 and v['coverage']==1 and v['error']>.15
        streak=streak+1 if alarm else 0
        if streak>=2 and c<65:
            if first_quality is None:first_quality=c
            enabled=False
        batch=[r for r in rows if r['cohort']==c]
        for r in batch:
            r.update(prediction=predict(actual,r['x']),model_sha256=digest(actual),exposed=enabled)
        seen+=batch
        timeline.append(dict(now=c,quality=v,alarm=alarm,streak=streak,autonomy=enabled,sentinel=sentinel,
            z_alert=bool(batch and sum(r['z'] for r in batch)/len(batch)>1)))
    def score(selected):
        return dict(n=len(selected),bad=sum(r['prediction']!=r['y'] for r in selected),
            error=sum(r['prediction']!=r['y'] for r in selected)/len(selected) if selected else None)
    comparison=[r for r in rows if 40<=r['cohort']<65]
    paired=[dict(id=r['id'],old=predict(baseline,r['x'])==r['y'],new=predict(candidate,r['x'])==r['y']) for r in reserve]
    result=dict(tasks=len(rows),trained_models=2,first_quality_alarm=first_quality,
        quality_delay_cohorts=first_quality-40,quality_false_alarms_before_change=sum(t['alarm'] for t in timeline if t['now']<40),
        sentinel_mismatch_cohorts=sentinel_changes,covariate_first=next(t['now'] for t in timeline if t['z_alert']),
        covariate_shift_without_loss=score([r for r in rows if 20<=r['cohort']<40]),
        population=score(comparison),selected_feedback=score([r for r in comparison if r['feedback']]),
        random_audit=score([r for r in comparison if r['audit']]),
        raw=score(rows),exposed=score([r for r in rows if r['exposed']]),
        errors_before_quality_containment=sum(r['prediction']!=r['y'] for r in rows if 40<=r['cohort']<first_quality),
        reserve_error=reserve_error,paired_improvements=sum(not r['old'] and r['new'] for r in paired),
        paired_regressions=sum(r['old'] and not r['new'] for r in paired),
        elapsed_wall_seconds=time.perf_counter()-start,logical_cohorts=120,
        limit='Dados sintéticos; regra de alarme heurística, sem garantia sequencial; nenhum humano ou LLM.')
    save(out/'events.json',rows);save(out/'timeline.json',timeline);save(out/'paired_reserve.json',paired);save(out/'result.json',result)
    return result
