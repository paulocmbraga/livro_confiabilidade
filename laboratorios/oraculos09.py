"""L09: avalia verificadores com casos válidos e defeitos rotulados pelo autor."""
from copy import deepcopy
from .dados_ii import write, lines, table


def base_case():
    return dict(intent='I09', principal='ana', sku='P1', quantity=2,
        before=5, after=3, now=8, approval_until=10,
        reservations=[dict(receipt='R09', intent='I09', principal='ana', sku='P1', quantity=2)],
        receipt='R09', ticket='closed', narrative='sucesso',
        operations=['stock', 'approval', 'reserve', 'receipt', 'close'])


def shared_stock(before, quantity):
    """Defeito deliberado: ignora quantity. Não reutilizar no oráculo de contrato."""
    return before - 1


def defects(state):
    """Contrato estreito, independente da função de estoque defeituosa."""
    errors = []
    qty = state.get('quantity')
    if type(qty) is not int or qty <= 0:
        errors.append('quantidade_intencao')
    reservations = state.get('reservations', [])
    if len(reservations) != 1:
        errors.append('unicidade')
    for reservation in reservations:
        for key in ('intent', 'principal', 'sku', 'quantity'):
            if reservation.get(key) != state.get(key):
                errors.append('vinculo_' + key)
        if type(reservation.get('quantity')) is not int:
            errors.append('tipo_quantidade')
        if not reservation.get('receipt') or reservation.get('receipt') != state.get('receipt'):
            errors.append('recibo')
    before, after = state.get('before'), state.get('after')
    quantities = [r.get('quantity') for r in reservations]
    if (type(before) is not int or type(after) is not int
        or any(type(q) is not int or q <= 0 for q in quantities)):
        errors.append('tipo_estoque')
    elif after < 0 or before - after != sum(quantities):
        errors.append('conservacao')
    if state.get('ticket') != 'closed':
        errors.append('chamado')
    if state['now'] > state['approval_until']:
        errors.append('prazo')
    ops = state.get('operations', [])
    required = ('stock', 'approval', 'reserve', 'receipt', 'close')
    if any(ops.count(name) != 1 for name in required):
        errors.append('eventos')
    elif not (max(ops.index('stock'), ops.index('approval')) < ops.index('reserve')
              < ops.index('receipt') < ops.index('close')):
        errors.append('precedencia')
    return sorted(set(errors))


def evaluate(state, evaluator):
    if evaluator == 'superficial':
        return state.get('narrative') == 'sucesso' and state.get('ticket') == 'closed'
    if evaluator == 'compartilhado':
        return state.get('after') == shared_stock(state['before'], state['quantity'])
    if evaluator == 'literal':
        return not defects(state) and state['operations'] == base_case()['operations']
    if evaluator == 'contrato':
        return not defects(state)
    raise ValueError('Avaliador desconhecido')


def cases():
    result = []
    def add(name, valid, category, change, reason):
        state = base_case(); change(state)
        result.append(dict(case_id=name, valid=valid, category=category,
                           reason=reason, state=state))
    add('V01', True, 'controle', lambda s: None, 'Reserva única com conservação e autoridade.')
    add('V02', True, 'equivalencia', lambda s: s.update(operations=['approval','stock','reserve','receipt','close']),
        'As duas leituras iniciais são independentes no contrato.')
    add('V03', True, 'equivalencia', lambda s: s.update(narrative='Reserva conferida no destino.'),
        'A redação não altera o efeito observado.')
    add('V04', True, 'equivalencia', lambda s: s['operations'].insert(2, 'log'),
        'Um evento de log sem efeito não modifica as dependências.')
    add('V05', True, 'fronteira', lambda s: s.update(now=10), 'Prazo inclusivo.')
    add('M01', False, 'estoque', lambda s: s.update(after=shared_stock(s['before'],s['quantity'])),
        'Duas unidades reservadas exigem redução de duas unidades.')
    add('M02', False, 'identidade', lambda s: s['reservations'][0].update(principal='bruno'),
        'O efeito pertence a outro principal.')
    add('M03', False, 'payload', lambda s: s['reservations'][0].update(quantity=1),
        'A quantidade não corresponde à intenção.')
    add('M04', False, 'unicidade', lambda s: s['reservations'].append(deepcopy(s['reservations'][0])),
        'Um segundo efeito viola a unicidade.')
    add('M05', False, 'recibo', lambda s: s.update(receipt='fantasma'), 'Recibo não identifica a reserva.')
    add('M06', False, 'precedencia', lambda s: s.update(operations=['stock','approval','reserve','close','receipt']),
        'O encerramento precede a confirmação exigida.')
    add('M07', False, 'prazo', lambda s: s.update(now=11), 'A autorização expirou.')
    add('M08', False, 'ausencia', lambda s: s.update(reservations=[],after=5),
        'Narrativa favorável sem reserva.')
    add('M09', False, 'tipo', lambda s: (s.update(quantity=True,after=4),s['reservations'][0].update(quantity=True)),
        'Booleano não é uma quantidade válida, mesmo sendo subclasse de int em Python.')
    add('M10', False, 'estado', lambda s: s.update(ticket='open'), 'A tarefa inclui encerrar o chamado.')
    add('M11', False, 'estoque', lambda s: s.update(after=-1), 'Estoque negativo.')
    return result


EVALUATORS = ('superficial', 'compartilhado', 'literal', 'contrato')


def trials(items=None):
    return [dict(case_id=c['case_id'], evaluator=e, valid=c['valid'], category=c['category'],
                 accepted=evaluate(c['state'],e), defects=defects(c['state']))
            for c in (cases() if items is None else items) for e in EVALUATORS]


def summarize(rows):
    result=[]
    for name in EVALUATORS:
        group=[r for r in rows if r['evaluator']==name]
        invalid=[r for r in group if not r['valid']]; valid=[r for r in group if r['valid']]
        result.append(dict(evaluator=name, cases=len(group), invalid=len(invalid), valid=len(valid),
            detected=sum(not r['accepted'] for r in invalid), escaped=sum(r['accepted'] for r in invalid),
            false_rejections=sum(not r['accepted'] for r in valid)))
    return result


def public_task(case):
    """Referência e versão do avaliador não atravessam a interface do sistema."""
    state=case['state']
    return {k:deepcopy(state[k]) for k in ('intent','principal','sku','quantity')}


def capture(folder):
    folder.mkdir(); items=cases(); rows=trials(items)
    lines(folder/'mutations.jsonl',items); lines(folder/'evaluator_trials.jsonl',rows)
    lines(folder/'public_tasks.jsonl',[public_task(c) for c in items])
    summary=summarize(rows); table(folder/'evaluator_confusion.csv',summary)
    (folder/'evaluator_card.md').write_text(
        '# Avaliadores L09-1.0\n\nCasos e rótulos são autorais, públicos e finitos. '
        'Positivo significa defeito detectado. O oráculo contrato não usa shared_stock. '
        'Sua independência é de implementação, não de autor ou de especificação. '
        'O registro de mutações conserva justificativas e alternativas válidas. '
        'Nenhum escore representa todos os defeitos possíveis.\n',encoding='utf8')
    write(folder/'summary.json',summary); return summary
