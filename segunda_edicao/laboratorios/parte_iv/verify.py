"""Offline reconciliation; no HTTP, training or external side effects."""
from pathlib import Path
import argparse,copy,math,statistics
from laboratorios.parte_i.common import load,digest,check_manifest
from laboratorios.parte_iv.core import by_group,metrics,identity,asof,features,preprocessor
from laboratorios.parte_iv.calibration import calibrate,conformal,coverage,selective,reliability

def analyze(root):
    root=Path(root);data=load(root/'data.json');plan=load(root/'plan.json');sel=load(root/'selection.json')
    models=load(root/'models.json');test=load(root/'test_predictions.json');http=load(root/'http_observed.json')
    cal=load(root/'calibration.json');domain=load(root/'domains.json');dp=load(root/'domain_predictions.json')
    interventions=load(root/'interventions.json');detector=load(root/'detector.json')
    chosen=test[sel['key']];result={'L13':{},'L14':{},'L15':{},'L16':{}}
    reference={r['id']:p for r,p in zip(data['test'],chosen)}
    for mode in plan['http_modes']:
        rows=[r for r in http if r['mode']==mode];ok=[r for r in rows if r['status']==200]
        ids={r['id'] for r in ok};source=[r for r in data['test'] if r['id'] in ids]
        outputs=[next(r['response'] for r in ok if r['id']==v['id']) for v in source]
        result['L13'][mode]={'admitted':len(rows),'rejected':len(rows)-len(ok),
            'feature_divergences':sum(r['response']['x']!=reference[r['id']]['x'] for r in ok),
            'prediction_changes':sum(r['response']['prediction']!=reference[r['id']]['prediction'] for r in ok),
            'accepted_metrics':by_group(source,outputs)}
    result['L13']['leaky_auc']=metrics(data['test'],test['leaky'])['auc']
    result['L13']['proper_auc']=metrics(data['test'],chosen)['auc']
    result['L13']['late_labels_example']={'admitted':len(data['train'][-20:]),
        'available_at_last_decision':sum(r['label_available']<=data['train'][-1]['at'] for r in data['train'][-20:])}
    for l2 in plan['l2']:
        scores=[metrics(data['test'],test[f'l2_{l2}_seed_{s}']) for s in plan['seeds']]
        result['L14'][str(l2)]={'seeds':scores,'mean_brier':statistics.mean(x['brier'] for x in scores),
            'sd_brier':statistics.stdev(x['brier'] for x in scores),'range_brier':[min(x['brier'] for x in scores),max(x['brier'] for x in scores)]}
    prior=statistics.mean(r['y'] for r in data['train'])
    result['L14']['constant_baseline']=metrics(data['test'],[{'id':r['id'],'p':prior} for r in data['test']])
    result['L14']['selected']=by_group(data['test'],chosen)
    for name,outputs in dp.items():
        calibrated=calibrate(outputs,cal['calibrator'])
        grouped={}
        for g,conf in cal['group_conformal'].items():
            grouped[g]=coverage([o for o in calibrated if o['group']==g],[r for r in domain[name] if r['group']==g],conf)[g]
        result['L15'][name]={'raw':by_group(domain[name],outputs),'calibrated':by_group(domain[name],calibrated),
            'global_conformal':coverage(calibrated,domain[name],cal['conformal']),
            'group_conformal':grouped,
            'reliability':reliability(calibrated,domain[name]),
            'selective':{str(t):selective(calibrated,domain[name],t,plan['abstention_cost']) for t in plan['selective_thresholds']}}
        alarms=sum(not detector['low']<=r['telemetry']<=detector['high'] for r in domain[name])
        result['L16'][name]={'n':len(domain[name]),'alarms':alarms,'alarm_rate':alarms/len(domain[name]),'metrics':by_group(domain[name],outputs)}
    result['L16']['interventions']={name:by_group(data['future'],o) for name,o in interventions['future'].items()}
    result['L16']['retention']={name:by_group(data['test'],o) for name,o in interventions['retention'].items()}
    return result

def assert_predictions(model,rows,outputs):
    if [r['id'] for r in rows]!=[o['id'] for o in outputs]:raise ValueError('prediction inventory')
    for r,o in zip(rows,outputs):
        x=features(r,model['prep'],model['future_join'])
        z=sum(a*b for a,b in zip(x,model['weights']))
        p=1/(1+math.exp(-max(-700,min(700,z))))
        if o['x']!=x or o['group']!=r['group'] or abs(o['p']-p)>1e-12 or o['prediction']!=int(p>=.5):raise ValueError('prediction relation')

def verify(root):
    root=Path(root);manifest=check_manifest(root)
    if not manifest['complete']:raise ValueError('partial capture')
    plan=load(root/'plan.json');data=load(root/'data.json');models=load(root/'models.json');sel=load(root/'selection.json')
    ids=[];last=-math.inf
    for name,n in plan['partitions'].items():
        rows=data[name]
        if len(rows)!=n or min(r['at'] for r in rows)<=last:raise ValueError('partition chronology')
        last=max(r['label_available'] for r in rows);ids.extend(r['id'] for r in rows)
    if len(ids)!=len(set(ids)):raise ValueError('entity leakage')
    tune=load(root/'tuning.json');tests=load(root/'test_predictions.json')
    for name,model in models.items():
        if name.startswith('l2_'):
            if model['prep']!=preprocessor(data['train']) or model['fit_data']!=digest(data['train']):raise ValueError('training lineage')
            assert_predictions(model,data['tune'],tune[name]);assert_predictions(model,data['test'],tests[name])
    losses={str(l2):statistics.mean(metrics(data['tune'],tune[f'l2_{l2}_seed_{s}'])['brier'] for s in plan['seeds']) for l2 in plan['l2']}
    l2=min(plan['l2'],key=lambda v:(losses[str(v)],v));key=f'l2_{l2}_seed_{plan["deployment_seed"]}'
    if sel['validation_brier']!=losses or sel['key']!=key or sel['identity']!=identity(models[key]):raise ValueError('selection')
    if load(root/'selected_model.json')!=models[key]:raise ValueError('served model')
    assert_predictions(models['leaky'],data['test'],tests['leaky'])
    raw=load(root/'http_observed.json');admissions=load(root/'http_admissions.json')
    expected=[f'{mode}-{i:03d}' for mode in plan['http_modes'] for i in range(plan['http_cases'])]
    if [r['attempt'] for r in raw]!=expected or [r['attempt'] for r in admissions]!=expected:raise ValueError('http admissions')
    receipts=list((root/'http/requests').glob('*.json'))
    if {p.stem for p in receipts}!=set(expected):raise ValueError('http receipts')
    ready=load(root/'http/ready.json');process=load(root/'processes.json')
    if process['alive_after'] or process['server_pid']==process['parent_pid'] or ready['model']!=sel['identity']:raise ValueError('process boundary')
    for i,row in enumerate(raw):
        receipt=load(root/'http/requests'/(row['attempt']+'.json'))
        if row['status']!=receipt['status'] or row['response']!=receipt['response']:raise ValueError('HTTP client/server disagreement')
        original=copy.deepcopy(data['test'][i%plan['http_cases']]);original.pop('y');original.pop('label_available')
        mode=row['mode']
        if mode.startswith('unit'):
            original['unit']='minute'
            if original['age'] is not None:original['age']*=60
        if mode=='category_guard':original['channel']='chat'
        if receipt['request']!={'attempt':row['attempt'],'mode':mode,'row':original}:raise ValueError('injection did not reach consumer')
        expected_status=422 if mode in ['unit_guard','category_guard'] else 200
        if row['status']!=expected_status:raise ValueError('guard outcome')
        if row['response']['pid']!=ready['pid']:raise ValueError('PID')
        if expected_status==200:
            x=features(original,models[key]['prep'],mode=='future_bad',mode=='unit_bad')
            z=sum(a*b for a,b in zip(x,models[key]['weights']));p=1/(1+math.exp(-max(-700,min(700,z))))
            if row['response']['x']!=x or abs(row['response']['p']-p)>1e-12:raise ValueError('served probability')
    cal=load(root/'calibration.json')
    assert_predictions(models[key],data['probcal'],cal['prob_raw']);assert_predictions(models[key],data['confcal'],cal['conf_raw'])
    if cal['calibrator']['ids']!=[r['id'] for r in data['probcal']]:raise ValueError('calibration lineage')
    if cal['conformal']!=conformal(calibrate(cal['conf_raw'],cal['calibrator']),data['confcal'],plan['alpha']):raise ValueError('conformal rank')
    for group,conf in cal['group_conformal'].items():
        if conf!=conformal([o for o in calibrate(cal['conf_raw'],cal['calibrator']) if o['group']==group],[r for r in data['confcal'] if r['group']==group],plan['alpha']):raise ValueError('group rank')
    domains=load(root/'domains.json');outputs=load(root/'domain_predictions.json')
    for name,rows in domains.items():assert_predictions(models[key],rows,outputs[name])
    for name in ['reference','benign','concept_same_x']:
        if [r['id'] for r in domains[name]]!=[r['id'] for r in data['test']]:raise ValueError('paired domain')
    for old,new in zip(data['test'],domains['concept_same_x']):
        expected=copy.deepcopy(old);expected['y']=1-old['y']
        if expected!=new:raise ValueError('concept pairing')
    for old,new in zip(data['test'],domains['benign']):
        expected=copy.deepcopy(old);expected['telemetry']+=5
        if expected!=new:raise ValueError('benign pairing')
    interventions=load(root/'interventions.json');noisy=load(root/'noisy_training.json')
    for name in ['adapted','retrained','noisy_retrained']:
        train=noisy if name=='noisy_retrained' else data['adapt_train']
        if models[name]['fit_data']!=digest(train):raise ValueError('intervention lineage')
        assert_predictions(models[name],data['future'],interventions['future'][name])
        assert_predictions(models[name],data['test'],interventions['retention'][name])
    assert_predictions(models[key],data['future'],interventions['future']['old'])
    assert_predictions(models[key],data['adapt_cal'],interventions['calibration_raw'])
    if interventions['recalibrator']['ids']!=[r['id'] for r in data['adapt_cal']]:raise ValueError('recalibration identity')
    if interventions['future']['recalibrated']!=calibrate(interventions['future']['old'],interventions['recalibrator']):raise ValueError('recalibration outputs')
    promotion=load(root/'promotion.json')
    if promotion['attacks']!={'swapped':'artifact_mismatch','test_access':'test_contamination'}:raise ValueError('promotion control')
    result=analyze(root)
    if load(root/'results.json')!=result:raise ValueError('aggregate disagreement')
    return {'partitions':{k:len(v) for k,v in data.items()},'models':len(models),'http':len(raw),'model_identity':sel['identity'],'results_reconciled':True}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('capture',type=Path);a=p.parse_args();print(verify(a.capture))
