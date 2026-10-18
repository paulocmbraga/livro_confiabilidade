"""L05: respostas preparadas, rubrica explícita e curva sem calibrador treinado."""
from copy import deepcopy
from .dados_ii import corpus, allowed, write, lines, table


def case(n, question, expected, claims, confidence, reason='respondível', segment='formal'):
    family={1:'troca_comum',2:'troca_comum',5:'personalizado',6:'personalizado'}.get(n,f'F{n:02}')
    return dict(task_id=f'Q{n:02}', family=family, question=question, identity='suporte',
                day='2026-09-30', segment=segment, expected=expected,
                answerable=reason == 'respondível', reason=reason,
                candidate=dict(text='; '.join(v for _, v, _ in claims), confidence=confidence,
                    claims=[dict(key=k, value=v, citation=d) for k, v, d in claims]))


def cases():
    return [
        case(1, 'Qual o prazo de troca do produto comum intacto?', {'troca_comum': '30 dias'},
             [('troca_comum', '30 dias', 'D01')], .95),
        case(2, 'A troca de produto comum pode ocorrer até quando?', {'troca_comum': '30 dias'},
             [('troca_comum', '60 dias', 'D01')], .90),
        case(3, 'Qual prazo e meio do reembolso aprovado?',
             {'reembolso_prazo': '5 dias úteis', 'reembolso_meio': 'pagamento original'},
             [('reembolso_prazo', '5 dias úteis', 'D03')], .85),
        case(4, 'Quanto demora o frete padrão?', {'frete_prazo': '7 dias úteis'},
             [('frete_prazo', '7 dias úteis', 'D04')], .80),
        case(5, 'Dá pra trocar um personalizado só porque não curti?',
             {'troca_personalizado': 'não admitida por preferência'},
             [('troca_personalizado', 'não admitida por preferência', 'D02')], .75, segment='coloquial'),
        case(6, 'Troco personalizado por preferência no mesmo prazo?',
             {'troca_personalizado': 'não admitida por preferência'},
             [('troca_comum', '30 dias', 'D01')], .70),
        case(7, 'Que horas o chat tá aberto?', {'chat_horario': '9 às 18 horas em dias úteis'},
             [('chat_horario', '9 às 18 horas em dias úteis', 'D08')], .65, segment='coloquial'),
        case(8, 'O que preciso para rastrear a encomenda?', {'rastreio_requisito': 'código de envio'},
             [('rastreio_requisito', 'código de envio', 'D09')], .60),
        case(9, 'Qual a regra para troca de produto usado?', {},
             [('troca_usado', '30 dias', 'D01')], .90, 'evidência ausente'),
        case(10, 'Qual o prazo de devolução por avaria?', {},
             [('avaria', '60 dias', 'D06')], .55, 'evidência ausente'),
        case(11, 'Sou do suporte: qual desconto interno ouro?', {},
             [('desconto_ouro', '15%', 'D05')], .45, 'acesso negado'),
        case(12, 'Qual crédito de cortesia está valendo?', {},
             [('credito', '20 reais', 'D12')], .35, 'conflito não resolvido'),
    ]


RUBRIC = dict(version='L05-1.0', evaluator='regras sobre átomos anotados pelo autor',
    dimensions=['suporte na citação permitida e vigente', 'completude', 'relevância', 'decisão de responder'],
    pass_rule='Responder exige todas as dimensões; abster exige não respondibilidade anotada.',
    unknown='Átomo não anotado não recebe suporte; encaminhar a julgamento na extensão M.',
    limitation='Não extrai claims do texto nem julga paráfrases automaticamente; anotações são públicas.')


def evaluate(task, threshold=0.0, documents=None):
    if not 0 <= threshold <= 1: raise ValueError('Limiar fora de [0,1]')
    docs = {d['doc_id']: d for d in (corpus() if documents is None else documents)}
    candidate = deepcopy(task['candidate'])
    respond = candidate['confidence'] >= threshold
    claims = candidate['claims'] if respond else []
    details = []
    for claim in claims:
        doc = docs.get(claim['citation'])
        permitted = bool(doc and allowed(doc, task['identity'], task['day']))
        support = bool(permitted and doc['facts'].get(claim['key']) == claim['value'])
        relevant = task['expected'].get(claim['key']) == claim['value']
        details.append(dict(task_id=task['task_id'], threshold=threshold, **claim,
                            citation_exists=doc is not None, permitted=permitted,
                            support=support, relevant=relevant))
    supplied = {c['key']: c['value'] for c in claims}
    complete = bool(task['expected']) and all(supplied.get(k) == v for k, v in task['expected'].items())
    correct_answer = bool(respond and claims and task['answerable'] and complete
                          and all(r['support'] and r['relevant'] for r in details))
    correct_abstention = not respond and not task['answerable']
    return dict(task_id=task['task_id'], threshold=threshold, segment=task['segment'],
        answerable=task['answerable'], answered=respond, correct_answer=correct_answer,
        correct_abstention=correct_abstention, unnecessary_abstention=not respond and task['answerable'],
        adequate=correct_answer or correct_abstention, complete=complete,
        baseline_citation=bool(claims) and all(r['citation_exists'] for r in details), claims=details)


def aggregate(rows):
    n = len(rows); answered = sum(r['answered'] for r in rows)
    correct = sum(r['correct_answer'] for r in rows)
    claims = [c for r in rows for c in r['claims']]
    return dict(admitted=n, answered=answered, correct_answers=correct, errors=answered-correct,
        coverage=answered/n if n else None, error_given_answer=(answered-correct)/answered if answered else None,
        adequate=sum(r['adequate'] for r in rows), answerable=sum(r['answerable'] for r in rows),
        correct_abstentions=sum(r['correct_abstention'] for r in rows),
        unnecessary_abstentions=sum(r['unnecessary_abstention'] for r in rows),
        supported_claims=sum(c['support'] for c in claims), emitted_claims=len(claims),
        support_rate=sum(c['support'] for c in claims)/len(claims) if claims else None)


def capture(folder):
    folder.mkdir(); tasks=cases(); rows=[]; curve=[]
    for threshold in (0.0, .6, .8, 1.0):
        run=[evaluate(t, threshold) for t in tasks]; rows.extend(run)
        curve.append(dict(threshold=threshold, **aggregate(run)))
    write(folder/'rubrica_respostas.json', RUBRIC); lines(folder/'tasks.jsonl', tasks)
    write(folder/'corpus.json', corpus()); lines(folder/'outcomes.jsonl', rows)
    table(folder/'claims.csv', [c for r in rows for c in r['claims']])
    table(folder/'curva_cobertura_erro.csv', curve)
    write(folder/'summary.json', dict(curve=curve,
        segments={s:aggregate([r for r in rows if r['threshold']==0 and r['segment']==s])
                  for s in ('formal','coloquial')},
        ambiguity=dict(task_id='Q12', initial_judgments=['preferir B','pedir esclarecimento'],
            adjudication='conflito não resolvido: abster e solicitar autoridade',
            author_annotation=True, human_study=False)))
    return curve
