"""Confere hashes e recalcula saídas da captura; sem novo treino nem HTTP."""
from pathlib import Path
import argparse,json,math
from collections import Counter
from statistics import mean
from laboratorios.parte_i.common import load,check_manifest
from . import l05,l07,l08,stats


def require(condition,message):
    if not condition:raise ValueError(message)


def verify(out):
    out=Path(out);manifest=check_manifest(out)
    require(manifest['complete'],'Campanha computacional parcial')
    p=load(out/'materials/plano.json');catalog=load(out/'materials/catalog.json')
    require(load(out/'l05.json')==l05.run(catalog),'Divisão mudou')
    cov=load(out/'l06/coverage.json')
    require(cov==stats.coverage(**p['l06']),'Cobertura sem reconciliação')
    boot=load(out/'l06/bootstrap.json');groups=[[1.]*5]*16+[[0.]*5]*4
    require(boot['group']==stats.bootstrap_groups(groups),'Bootstrap agrupado mudou')
    require(boot['naive_rows']==stats.bootstrap_groups([[x] for g in groups for x in g]),'Bootstrap de linhas mudou')
    require(boot['zero_failures_30_upper']==stats.zero_upper(30) and
            boot['zero_failures_1pct_n']==stats.minimum_zero_sample(.01) and
            boot['missing_80_10_10']==[.8,.9],'Exemplos analíticos mudaram')
    d=out/'l07';cfg=p['l07'];train=load(d/'train.json');test=load(d/'test.json')
    require(train==l07.dataset(cfg['train_seed'],cfg['train_groups'],cfg['rows_per_group'],'D'),'Treino diferente do plano')
    require(test==l07.dataset(cfg['test_seed'],cfg['test_groups'],cfg['rows_per_group'],'T'),'Teste diferente do plano')
    require(not {x['family'] for x in train}&{x['family'] for x in test},'Família compartilhada')
    admitted=load(d/'admitted.json');obs=load(d/'observations.json')
    require(admitted==l07.schedule(test,cfg),'Admissões diferentes do plano')
    require(len(obs)==len(admitted),'Inferências ausentes')
    index={r['id']:r for r in test}
    models={k:load(d/'models'/(k+'.json')) for k in cfg['candidates']}
    for k,m in models.items():
        require(m['kind']==k and m['training_rows']==len(train) and m['epochs']==cfg['epochs'],'Identidade do modelo')
        require(len(m['loss_before_updates'])==cfg['epochs'] and all(math.isfinite(x) for x in m['weights']),'Treino não finito')
        require(len(m['weights'])==(3 if k=='linear' else 4),'Dimensão dos pesos')
    for job,row in zip(admitted,obs):
        require(all(row[k]==v for k,v in job.items()),'Par, ordem ou repetição alterados')
        require(math.isfinite(row['seconds']) and row['seconds']>=0,'Tempo inválido')
        if row['status']=='ok':
            # Reconcilia o cálculo da saída com pesos salvos; não executa o adaptador.
            x=index[row['case']]['x'];m=models[row['candidate']]
            terms=[1.,*x]+([x[0]*x[1]] if m['kind']=='interaction' else [])
            value=1/(1+math.exp(-sum(w*v for w,v in zip(m['weights'],terms))))
            require(abs(row['raw']['probability']-value)<1e-12,'Probabilidade não corresponde aos pesos')
            require(row['raw']['prediction']==int(value>=.5),'Classe trocada')
        else:require(row['status']=='error' and row['error'] and row['raw'] is None,'Falha não explicada')
    warm=load(d/'warmups.json');require(len(warm)==2*cfg['warmups_each'],'Aquecimento perdido')
    require(Counter(r['candidate'] for r in warm)=={k:cfg['warmups_each'] for k in cfg['candidates']},'Candidato sem aquecimento')
    require({r['case'] for r in warm}<={r['id'] for r in train},'Aquecimento usou teste')
    training=load(d/'training.json')
    require({r['candidate'] for r in training}==set(cfg['candidates']) and len(training)==2,'Treinos ausentes ou extras')
    require(all(math.isfinite(r['seconds']) and r['seconds']>=0 for r in training+warm),'Consumo inválido')
    result07=l07.analyze(test,obs,cfg);require(load(d/'summary.json')==result07,'Resumo L07 divergente')
    selection=load(d/'selection_simulation.json')
    require(selection==stats.selection_optimism(),'Simulação de seleção divergente')
    result07['selection_simulation']={'trials':len(selection),
        'mean_selected_development':mean(x['selected_dev'] for x in selection),
        'mean_independent_final':mean(x['independent_final_rate'] for x in selection)}
    d=out/'l08';cfg=p['l08'];rows=load(d/'cases.json');obs08=load(d/'observations.json')
    require(rows==l08.cases(),'Casos fatoriais trocados')
    jobs=l08.plan_requests(rows,cfg['order_seed']);require(load(d/'admitted.json')==jobs,'Plano fatorial alterado')
    require(len(obs08)==len(jobs),'Fatorial parcial');idx={c['id']:c for c in rows}
    ready=load(d/'ready.json')
    for job,row in zip(jobs,obs08):
        require(row['request']==job,'Ordem fatorial alterada')
        raw=row['response'];require(row['status']==200 and raw['pid']==ready['pid'] and row['client_pid']!=raw['pid'],'Serviço não separado')
        require(load(d/'audit'/(job['id']+'.json'))=={'request':job,'response':raw},'Auditoria do serviço não corresponde')
        expected=l08.decision(idx[job['case']],job['refresh'],job['validate'])
        require(all(raw[k]==v for k,v in expected.items()),'Decisão fatorial divergente')
    require({f.stem for f in (d/'audit').glob('*.json')}=={j['id'] for j in jobs},'Auditoria extra ou faltante')
    require(load(d/'process_exit.json')['exit_code'] is not None,'Serviço não encerrado')
    result08=l08.analyze(rows,obs08);require(result08==load(d/'summary.json'),'Resumo L08 mudou')
    seq=load(d/'sequential.json')
    require(seq==stats.sequential(cfg['sequential_seed'],cfg['trials'],cfg['looks'],cfg['alpha']),'Simulação sequencial mudou')
    require(load(d/'exposure.json')==l08.exposure(cfg['exposure_seed'],cfg['exposure_groups'],cfg['users_per_group']),'Exposição mudou')
    rates={key:{'false_positives':sum(r[key] for r in seq),'trials':len(seq),
               'rate':mean(r[key] for r in seq),'wilson_mc':stats.wilson(sum(r[key] for r in seq),len(seq))}
           for key in ('fixed','opportunistic','bonferroni')}
    require(load(out/'execution.json')['test_predictions']==len(admitted),'Custo de inferência incompleto')
    return {'L05':load(out/'l05.json'),'L06':{'trials':len(cov),
        'naive_coverage':mean(r['naive_covers'] for r in cov),
        'group_coverage':mean(r['group_covers'] for r in cov),
        'naive_mean_width':mean(r['naive'][1]-r['naive'][0] for r in cov),
        'group_mean_width':mean(r['group'][1]-r['group'][0] for r in cov),'bootstrap':boot},
        'L07':result07,'L08':result08,'sequential':rates,'human_review':'pending'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('capture',type=Path);a=p.parse_args()
    r=verify(a.capture);print(json.dumps(r,ensure_ascii=False,indent=2))
