"""L22: exercício com relógio lógico, sem equipe humana ou tráfego HTTP."""
from .dados_ii import write,lines,table


def service_view(rows,cutoff,target=.9):
    visible=[r for r in rows if r['tick']<=cutoff]
    if not visible:return dict(total=0,known=0,good=0,coverage=0,lower=None,upper=None,budget=None)
    known=[r for r in visible if r['label_at']<=cutoff]
    good=sum(r['good'] for r in known);n=len(visible);unknown=n-len(known)
    return dict(total=n,known=len(known),good=good,coverage=len(known)/n,
        lower=good/n,upper=(good+unknown)/n,
        budget=dict(allowed=n*(1-target),known_bad=len(known)-good,pending=unknown))


def may_reopen(evidence):
    required=('source_fixed','labels_mature','quality_pass','effects_reconciled','owner_ack')
    missing=[k for k in required if evidence.get(k) is not True]
    return dict(allowed=not missing,missing=missing)


def critical_stop(events):
    return any(r.get('kind') in ('unauthorized_effect','content_exposure') for r in events)


def run(policy='controlled'):
    if policy not in ('controlled','availability'):raise ValueError(policy)
    rows=[];timeline=[];mode='open';detected=None;contained=None;returned=None
    checks=[]
    for tick in range(12):
        if tick==3:timeline.append(dict(tick=tick,event='source_invalid',revision='bad-v2'))
        if tick==5:
            timeline.append(dict(tick=tick,event='quality_alert_dropped',case='Q03'))
        if tick==6 and policy=='controlled':
            # O poll encontra rótulos vencidos mesmo que a notificação se perca.
            bad=[r for r in rows if r['label_at']<=tick and not r['good']]
            if bad:
                detected=contained=tick;mode='contained'
                timeline.extend([dict(tick=tick,event='detected_by_reconciliation',cases=[r['task'] for r in bad]),
                                 dict(tick=tick,event='source_quarantined')])
        if tick==8:
            timeline.append(dict(tick=tick,event='source_repaired',revision='good-v3'))
            evidence=dict(source_fixed=True,labels_mature=False,quality_pass=True,
                          effects_reconciled=False,owner_ack=True)
            checks.append(dict(tick=tick,evidence=evidence,**may_reopen(evidence)))
            timeline.append(dict(tick=tick,event='return_denied',reason='labels_and_effects'))
        if tick==9:
            evidence=dict(source_fixed=True,labels_mature=True,quality_pass=True,
                          effects_reconciled=True,owner_ack=True)
            checks.append(dict(tick=tick,evidence=evidence,**may_reopen(evidence)))
            if policy=='controlled' and may_reopen(evidence)['allowed']:
                mode='open';returned=tick;timeline.append(dict(tick=tick,event='reopened'))
        blocked=mode=='contained'
        good=not blocked and not 3<=tick<8
        rows.append(dict(task=f'Q{tick:02}',tick=tick,revision='v1' if tick<3 else 'bad-v2' if tick<8 else 'good-v3',
            status=503 if blocked else 200,served=not blocked,good=good,
            label_at=tick if blocked else tick+2))
        timeline.append(dict(tick=tick,event='task_terminal',task=rows[-1]['task'],status=rows[-1]['status']))
    stats=dict(policy=policy,offered=len(rows),served=sum(r['served'] for r in rows),
        bad_answers=sum(r['served'] and not r['good'] for r in rows),
        held=sum(not r['served'] for r in rows),good=sum(r['good'] for r in rows),
        detection_delay=None if detected is None else detected-3,
        containment_delay=None if contained is None else contained-3,
        recovery_delay=None if returned is None else returned-3,
        complete_view=service_view(rows,13))
    return dict(tasks=rows,timeline=timeline,return_checks=checks,summary=stats)


def close_action(action,tests):
    test=tests.get(action.get('verification'))
    return bool(action.get('owner') and action.get('due') and test and test.get('passed') is True
                and test.get('revision')==action.get('revision'))


def capture(folder):
    folder.mkdir();runs={p:run(p) for p in ('availability','controlled')}
    for p,result in runs.items():
        lines(folder/f'{p}_tasks.jsonl',result['tasks'])
        lines(folder/f'{p}_timeline.jsonl',result['timeline'])
        write(folder/f'{p}_return_checks.json',result['return_checks'])
    table(folder/'quality_windows.csv',[dict(cutoff=t,**{k:v for k,v in service_view(runs['controlled']['tasks'],t).items() if k!='budget'}) for t in (4,6,8,11,13)])
    actions=[dict(id='A1',owner='papel:operacao',due=12,revision='v3',verification='alert_reconciliation'),
             dict(id='A2',owner='papel:dados',due=12,revision='v3',verification='corpus_revision')]
    tests={'alert_reconciliation':dict(passed=True,revision='v3'),
           'corpus_revision':dict(passed=True,revision='v2')}
    write(folder/'action_register.json',[dict(**a,closed=close_action(a,tests)) for a in actions])
    write(folder/'verification_results.json',tests)
    (folder/'slo_spec.md').write_text('População: doze tarefas admitidas no relógio lógico 0 a 11. '
        'Evento bom: resposta correta entregue; retenção segura é disponibilidade perdida, não sucesso. '
        'Meta didática: 90%. Rótulos chegam com atraso de dois ticks. Janela madura: corte 13. '
        'Intervalo lower/upper é limite de identificação para rótulos pendentes, não intervalo de confiança. '
        'Autoridade e exposição são invariantes separadas e não consomem orçamento de erro como permissão.',encoding='utf8')
    (folder/'runbook.md').write_text('1. Reconciliar o ledger com rótulos maduros. 2. Quarentenar a revisão da fonte. '
        '3. Preservar tarefas afetadas e novas demandas retidas. 4. Reparar fonte e executar casos de retorno. '
        '5. Confirmar efeitos pendentes e maturidade das referências. 6. Exigir reconhecimento do papel de operação. '
        'Os campos de confirmação deste exercício são preparados, não aprovações humanas reais.',encoding='utf8')
    (folder/'postmortem.md').write_text('O sintoma inicial manteve status 200 com fonte incorreta. A notificação do '
        'primeiro erro foi perdida; a reconciliação periódica detectou a dívida. Contenção interrompeu novas '
        'respostas da fonte, mas reteve três tarefas. A tentativa de retorno no tick 8 falhou por rótulos '
        'e efeitos pendentes; o retorno no tick 9 foi aceito sob evidências preparadas. A2 permanece aberta '
        'porque o teste registrado cobre v2 e a ação exige v3. O roteiro não mede desempenho de uma equipe.',encoding='utf8')
    return {p:r['summary'] for p,r in runs.items()}
