"""Conferência offline: hashes, identidade, cardinalidade e relações observáveis."""
from pathlib import Path
from collections import Counter
import argparse,json,math
from .common import load,check_manifest
from . import l01,l02,l04

def service_contract(row):
    p=row['proposal'];c=row['context']
    return (type(p) is dict and set(p)=={'tenant','cents','revision'}
            and type(p['cents']) is int and 0<p['cents']<=c['limit']
            and p['tenant']==c['tenant'] and p['revision']==c['revision'] and c['authorized'])

def verify_service(root,plan,cases):
    rows=load(root/'requests.json');expected={(m,c['id']) for m in plan['modes'] for c in cases}
    keys=[(r['mode'],r['case']) for r in rows]
    if len(keys)!=len(set(keys)) or set(keys)!=expected:raise ValueError('Requisições incompletas')
    case_map={c['id']:c for c in cases};summary={}
    for mode in plan['modes']:
        violations=applied=preserved=blocked=compliant=missing_audit=0;previous=[];previous_audit=[]
        for row in [r for r in rows if r['mode']==mode]:
            case=case_map[row['case']]
            if row['request']!=case:raise ValueError('Entrada diferente do plano')
            obs=load(root/row['observation'])
            if obs['observer_pid']==row['service_pid']:raise ValueError('Observador não separado')
            own=[e for e in obs['effects'] if e[0]==case['id']]
            if any(e not in obs['effects'] for e in previous):raise ValueError('Efeito anterior desapareceu')
            if any(e not in obs['audit'] for e in previous_audit):raise ValueError('Auditoria desapareceu')
            added=[e for e in obs['effects'] if e not in previous]
            if added!=own:raise ValueError('Efeito fora da tarefa atual')
            if len(own)>1:raise ValueError('Efeito duplicado')
            valid=service_contract(case)
            allowed=valid and (case['collector_up'] or not case['audit_required_online'])
            allowed=allowed and len(previous_audit)<case['buffer_capacity']
            if own:
                applied+=1
                p=case['proposal']
                if own[0]!=[case['id'],p['tenant'],p['cents']]:raise ValueError('Efeito diverge da proposta')
                bad=not valid;violations+=bad;preserved+=not bad;compliant+=allowed
                missing_audit+=not any(x[0]==case['id'] for x in obs['audit'])
                if row['http']!=200:raise ValueError('Commit sem recibo neste contrato')
            else:blocked+=1
            if mode=='protected':
                if bool(own)!=allowed:raise ValueError('Política protegida divergiu do contrato')
                audit=[x for x in obs['audit'] if x[0]==case['id']]
                if bool(audit)!=bool(own):raise ValueError('Falta registro atômico')
                if audit and json.loads(audit[0][1])!={'proposal':case['proposal'],'context':case['context']}:
                    raise ValueError('Registro de auditoria trocado')
            previous=obs['effects'];previous_audit=obs['audit']
        if load(root/mode/'health_after.json')['status']!=200:raise ValueError('Serviço não respondeu depois')
        if load(root/mode/'process_exit.json')['exit_code'] is None:raise ValueError('Processo não encerrado')
        summary[mode]={'requests':10,'applied':applied,'valid_effects':preserved,
                       'domain_violations':violations,'without_effect':blocked,
                       'effects_allowed_by_full_policy':compliant,'effects_without_audit':missing_audit}
    return summary

def verify_workers(root,plan):
    check_manifest(root/'partial')
    data=load(root/'observed.json')['data'];partial=load(root/'partial/observed.json')['data']
    expected={x['id']:x for x in plan['cases']}
    for snap in (data,partial):
        if {r['id']:json.loads(r['payload']) for r in snap['cases']}!=expected:
            raise ValueError('Casos fora do plano')
    # Compara exportação com leitura independente do SQLite preservado.
    if l04.snapshot(root/'journal.sqlite')!=data:raise ValueError('Exportação não corresponde ao journal')
    if l04.snapshot(root/'partial/journal.sqlite')!=partial:raise ValueError('Snapshot parcial divergente')
    result=l04.reconcile(data,root)
    earlier=l04.reconcile(partial,root/'partial',False)
    if earlier['complete']:raise ValueError('Interrupção não atingida')
    try:l04.reconcile(partial,root/'partial',True)
    except ValueError:pass
    else:raise ValueError('Parcial aceita como completa')
    for key in ('attempts','results','events'):
        if any(row not in data[key] for row in partial[key]):raise ValueError('História sobrescrita')
    for cid in (plan['kill_before_raw'],plan['kill_after_raw']):
        attempts=[a for a in data['attempts'] if a['case_id']==cid]
        if len(attempts)!=2:raise ValueError('Retomada não preservou tentativas')
    orphan=root/'attempts'/(plan['kill_after_raw']+'-a1')/'raw.json'
    if not orphan.exists():raise ValueError('Saída órfã descartada')
    if (root/'attempts'/(plan['kill_before_raw']+'-a1')/'raw.json').exists():raise ValueError('Falha pré-raw não atingida')
    if not load(root/'barrier.json')['all_alive']:raise ValueError('Sobreposição não observada')
    processes=load(root/'processes.json')
    if len(processes)!=8 or sum(p['exit_code']!=0 for p in processes)!=2:raise ValueError('Mortes reais não reconciliadas')
    return {'final':result,'partial':earlier,'orphan_retained':True,'worker_processes':len(processes)}

def verify(root):
    root=Path(root);manifest=check_manifest(root);plan=load(root/'materials/plano.json')
    if not manifest['complete']:raise ValueError('Captura marcada incompleta')
    l1=load(root/'l01.json')
    if l1!=l01.summarize(load(root/'materials/l01_cases.json')):raise ValueError('L01 divergiu')
    sims=load(root/'l02.json')
    if len(sims)!=len(plan['l02']['scenarios']):raise ValueError('Cenário L02 perdido')
    for item,scenario in zip(sims,plan['l02']['scenarios']):
        if item['scenario']!=scenario:raise ValueError('Cenário trocado')
        q,r=scenario['q'],scenario['r'];exact=l02.enumerate_states(q,r)
        if item['enumeration']!=exact or item['analytic']!=l02.analytic(q,r):raise ValueError('Álgebra divergiu')
        if not math.isclose(sum(x['probability'] for x in exact),1):raise ValueError('Massa perdida')
        analytic=item['analytic']
        if not math.isclose(sum(x['probability'] for x in exact if x['series']),analytic['series']):raise ValueError('Fórmula série')
        if not math.isclose(sum(x['probability'] for x in exact if x['parallel_failure']),analytic['parallel_failure']):raise ValueError('Fórmula paralelo')
        if [s['seed'] for s in item['replicates']]!=plan['l02']['seeds']:raise ValueError('Semente perdida')
        for s in item['replicates']:
            if s['n']!=plan['l02']['n'] or s!=l02.simulate(q,r,s['n'],s['seed']):raise ValueError('Replay de cálculo divergiu')
    return {'L01':l1,'L02':{'drawn_episodes':sum(s['n'] for x in sims for s in x['replicates']),
                           'exact_states':sum(len(x['enumeration']) for x in sims)},
            'L03':verify_service(root/'l03',plan['l03'],load(root/'materials/l03_cases.json')),
            'L04':verify_workers(root/'l04',plan['l04'])}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path)
    print(json.dumps(verify(p.parse_args().root),ensure_ascii=False,indent=2))
