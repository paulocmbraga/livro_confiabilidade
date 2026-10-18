"""L08: workflow e controlador reativo determinístico, com mesmo teto de ferramentas."""
import json
import os
from pathlib import Path
import subprocess
import sys
from . import destino08
from .dados_ii import write, lines, table

SCENARIOS=('normal','identidade_trocada','sem_estoque','negada','sucesso_falso',
           'resposta_perdida','sem_observacao','ciclo')
PROJECT=Path(__file__).resolve().parents[1]


def call(path,request):
    result=subprocess.run([sys.executable,'-m','laboratorios.destino08',str(path)],
        input=json.dumps(request),capture_output=True,text=True,encoding='utf8',cwd=PROJECT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,timeout=5)
    if result.returncode:raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def oracle(snapshot,narrative,scenario,history):
    denied_calls=sum(r['request']['operation']=='reserve' and r['response']['status']=='denied' for r in history)
    if not snapshot['available']:
        return dict(state='efeito_incerto',adequate=False,completed=False,unauthorized_attempts=denied_calls)
    reservations=snapshot['reservations']; closed=snapshot['tickets'][0]['closed']
    verified=(len(reservations)==1 and reservations[0]==dict(intent='I1',principal='ana',sku='P1',quantity=1)
              and closed==1 and snapshot['stock'][0]['quantity']==1 and denied_calls==0)
    refusal=scenario=='negada' and narrative=='recusa' and not reservations and not closed
    impossible=scenario=='sem_estoque' and narrative=='impossível' and not reservations and not closed
    state='verificado' if verified else 'recusa_correta' if refusal else 'impossivel' if impossible else 'falhou'
    return dict(state=state,adequate=verified or refusal or impossible,completed=verified,
                unauthorized_attempts=denied_calls)


def execute(path,scenario,variant,attempt,limit=6):
    if variant not in ('workflow','agente_d'):raise ValueError('Variante desconhecida')
    if limit<1:raise ValueError('Limite inválido')
    history=[]; observed={}; narrative='falha'; stopped='policy'
    # O controlador só recebe observações. A perturbação atua no transporte.
    order=['stock','approval'] if variant=='workflow' or attempt%2 else ['approval','stock']
    while len(history)<limit:
        if any(r.get('status')=='denied' for r in observed.values()):narrative='recusa';break
        if observed.get('stock',{}).get('quantity')==0:narrative='impossível';break
        operation=next((op for op in order if op not in observed),None)
        if operation is None and observed['stock']['status']=='retry':
            if variant=='workflow':break
            operation='stock'
        if operation is None:
            if 'reserve' not in observed:operation='reserve'
            elif variant=='workflow':
                if 'receipt' not in observed:operation='receipt'
                elif observed['receipt']['status']=='ok' and 'close' not in observed:operation='close'
                else:
                    narrative='sucesso' if observed.get('close',{}).get('status')=='ok' else 'incerto' if observed['receipt']['status']=='unavailable' else 'falha'
                    break
            else:
                # Falhas intencionais do controlador: confiança no status e repetição desigual.
                reserve=observed['reserve']['status']
                if reserve=='unknown' and attempt==1:narrative='incerto';break
                if reserve=='unknown' and attempt==3:narrative='sucesso';break
                if reserve=='unknown' and 'receipt' not in observed:operation='receipt'
                elif reserve=='unknown' and observed['receipt']['status']!='ok':narrative='incerto';break
                elif 'close' not in observed:operation='close'
                else:narrative='sucesso';break
        request=dict(operation=operation,principal='ana',intent='I1',sku='P1',quantity=1)
        if scenario=='identidade_trocada' and operation=='reserve':request['principal']='bruno'
        response=call(path,request);history.append(dict(step=len(history)+1,request=request,response=response))
        observed[operation]=response
    else:
        stopped='budget'
        if observed.get('close',{}).get('status')=='ok':narrative='sucesso'
    snapshot=call(path,dict(operation='snapshot'))
    outcome=oracle(snapshot,narrative,scenario,history)
    return dict(scenario=scenario,variant=variant,attempt=attempt,narrative=narrative,
        stopped=stopped,steps=len(history),budget=limit,verification_calls=1,
        cost_units=len(history)+1,history=history,**outcome),snapshot


def summarize(rows):
    result=[]
    for variant in ('workflow','agente_d'):
        group=[r for r in rows if r['variant']==variant]
        by_task=[[r for r in group if r['scenario']==s] for s in SCENARIOS]
        result.append(dict(variant=variant,tasks=len(SCENARIOS),attempts=len(group),
            completed=sum(r['completed'] for r in group),adequate=sum(r['adequate'] for r in group),
            any_adequate=sum(any(r['adequate'] for r in g) for g in by_task),
            all_adequate=sum(all(r['adequate'] for r in g) for g in by_task),
            unauthorized_attempts=sum(r['unauthorized_attempts'] for r in group),
            uncertain=sum(r['state']=='efeito_incerto' for r in group),
            steps=sum(r['steps'] for r in group),cost_units=sum(r['cost_units'] for r in group),
            narrative_success=sum(r['narrative']=='sucesso' for r in group),
            false_narrative_success=sum(r['narrative']=='sucesso' and not r['completed'] for r in group)))
    return result


def capture(folder):
    folder.mkdir(); databases=folder/'destinos';databases.mkdir(); rows=[]; snapshots={}
    for scenario in SCENARIOS:
        for variant in ('workflow','agente_d'):
            for attempt in (1,2,3):
                key=f'{scenario}_{variant}_{attempt}';path=databases/(key+'.sqlite')
                destino08.initialize(path,scenario); row,snapshot=execute(path,scenario,variant,attempt)
                rows.append(row);snapshots[key]=snapshot
    lines(folder/'trajectories.jsonl',rows);write(folder/'destination_snapshots.json',snapshots)
    table(folder/'outcomes.csv',[{k:v for k,v in r.items() if k!='history'} for r in rows])
    summary=summarize(rows);write(folder/'summary.json',summary);return summary
