"""L10: trilha D com anotações autorais; pacote cego para uma futura trilha H."""
import argparse
from collections import Counter
import csv
from copy import deepcopy
import json
import math
from pathlib import Path
import random
from .dados_ii import write, lines, table

DIMENSIONS = ('suporte','completude','clareza')


def cases():
    specs=[
        ('troca','Qual o prazo para troca comum?', '30 dias.', 'Produto comum intacto: 30 dias.', [2,2,2]),
        ('reembolso','Qual prazo e meio do reembolso?', 'Cinco dias úteis.', 'Cinco dias úteis; meio original.', [2,1,2]),
        ('personalizado','Posso trocar personalizado por preferência?', 'Sim, em 30 dias.', 'Personalizados não admitem essa troca.', [0,0,2]),
        ('credito','Qual o crédito de cortesia?', 'São dez reais.', 'Dois avisos de mesma autoridade: dez e vinte.', [None,None,2]),
        ('frete','Quanto demora a entrega padrão?', 'Leva 7 dias úteis.', 'Entrega padrão em 7 dias úteis.', [2,2,2]),
        ('chat','Quando há atendimento?', 'Dias úteis, 9h às 18h.', 'Chat: dias úteis, das 9 às 18 horas.', [2,2,2]),
        ('garantia','Qual a duração da garantia adicional?', 'Doze meses.', 'Garantia adicional: 12 meses após a compra.', [2,2,2]),
        ('agendamento','Como reagendar e com qual antecedência?', 'Pelo portal.', 'Pelo portal, até 24 horas antes.', [2,1,2]),
        ('retirada','Outra pessoa pode retirar meu pedido?', 'Basta dizer seu nome.', 'Exige autorização e documento da pessoa.', [0,0,2]),
        ('entrega_especial','Qual a janela de entrega especial?', 'Pela manhã.', 'Sem registro da janela contratada.', [None,None,2]),
        ('contato','Qual canal confirma meu protocolo?', 'E-mail com o número do protocolo.', 'Confirmação por e-mail com número do protocolo.', [2,2,2]),
        ('cancelamento','Como cancelar antes da separação?', 'No portal antes da separação.', 'Cancelamento no portal antes da separação.', [2,2,2]),
    ]
    return [dict(case_id=f'N{i:02}',family=family,partition='calibracao' if i<=6 else 'teste_publico',
        question=q,response=a,evidence=source,reference=dict(zip(DIMENSIONS,ref)),
        reference_kind='anotacao_autoral',ambiguous=any(v is None for v in ref))
        for i,(family,q,a,source,ref) in enumerate(specs,1)]


def annotations():
    """Não são pessoas: A/B são colunas sintéticas que permitem auditar cálculos."""
    a1=[[2,2,2],[2,2,2],[2,2,2],[2,2,2],[2,2,2],[2,2,2],
        [2,2,2],[2,2,2],[2,2,2],[2,2,2],[2,2,2],[2,2,2]]
    b1=[[2,2,2],[2,1,2],[0,0,2],[None,None,2],[2,2,2],[2,2,1],
        [2,2,2],[2,1,2],[0,0,2],[None,None,2],[2,2,2],[2,2,1]]
    a2=[list(c['reference'].values()) for c in cases()]
    b2=deepcopy(a2); b2[7][1]=2; b2[10][2]=1
    result=[]
    for version,matrices in (('r1',[a1,b1]),('r2',[a2,b2])):
        for evaluator,values in zip(('A_preparado','B_preparado'),matrices):
            for index,(case,scores) in enumerate(zip(cases(),values),1):
                for dim,score in zip(DIMENSIONS,scores):
                    result.append(dict(annotation_id=f'{version}:{evaluator}:{case["case_id"]}:{dim}',
                        case_id=case['case_id'],rater=evaluator,rubric=version,dimension=dim,
                        score=score,reason='Sem referência suficiente.' if score is None else
                        'Julgamento preparado para testar divergência e agregação.',
                        seconds=20+index*2+(5 if version=='r2' else 0),
                        partition=case['partition'],source_kind='preparado'))
    return result


def agreement(pairs):
    """Kappa nominal, com pares completos e denominador de ausências declarado."""
    complete=[(a,b) for a,b in pairs if a is not None and b is not None]
    n=len(complete)
    if not n:return dict(admitted=len(pairs),complete=0,missing=len(pairs),observed=None,expected=None,kappa=None)
    left=Counter(a for a,b in complete);right=Counter(b for a,b in complete)
    po=sum(a==b for a,b in complete)/n
    pe=sum(left[k]*right[k] for k in set(left)|set(right))/(n*n)
    return dict(admitted=len(pairs),complete=n,missing=len(pairs)-n,observed=po,expected=pe,
                kappa=(po-pe)/(1-pe) if pe<1 else None)


def summarize(rows):
    result=[]
    for version in ('r1','r2'):
        for partition in ('calibracao','teste_publico'):
            for dim in DIMENSIONS:
                group=[r for r in rows if (r['rubric'],r['partition'],r['dimension'])==(version,partition,dim)]
                ids=sorted({r['case_id'] for r in group});index={(r['case_id'],r['rater']):r for r in group}
                pairs=[(index[(i,'A_preparado')]['score'],index[(i,'B_preparado')]['score']) for i in ids]
                result.append(dict(rubric=version,partition=partition,dimension=dim,**agreement(pairs),
                    synthetic_seconds=sum(r['seconds'] for r in group)))
    return result


def adjudications(rows):
    decisions=[]; refs={c['case_id']:c for c in cases()}
    for version in ('r1','r2'):
        for case in cases():
            for dim in DIMENSIONS:
                group=[r for r in rows if (r['rubric'],r['case_id'],r['dimension'])==(version,case['case_id'],dim)]
                if len({r['score'] for r in group})>1:
                    decisions.append(dict(decision_id=f'{version}:{case["case_id"]}:{dim}:adj1',
                        annotation_ids=[r['annotation_id'] for r in group],case_id=case['case_id'],dimension=dim,
                        rubric=version,score=refs[case['case_id']]['reference'][dim],
                        reason='Decisão autoral pela evidência indicada, sem apagar os julgamentos de origem.',
                        source_kind='preparado',status='pendente' if case['reference'][dim] is None else 'resolvido'))
    return decisions


def assignments():
    result=[]
    for index,rater in enumerate(('revisor_1','revisor_2')):
        public=[{k:c[k] for k in ('case_id','family','partition','question','response','evidence')} for c in cases()]
        random.Random(101+index).shuffle(public)
        for order,case in enumerate(public,1):
            result.append(dict(rater=rater,order=order,rubric='r2',**case))
    return result


def validate_annotations(rows, allocation):
    expected={(a['rater'],a['case_id'],a['rubric'],d) for a in allocation for d in DIMENSIONS}
    seen=set(); missing=0
    for row in rows:
        key=tuple(row.get(k) for k in ('rater','case_id','rubric','dimension'))
        if key not in expected or key in seen:raise ValueError('Identidade inválida ou duplicada')
        seen.add(key);score=row.get('score')
        if score not in ('','0','1','2',None,0,1,2) or isinstance(score,bool):raise ValueError('Nota inválida')
        if score in ('',None):missing+=1
        if not str(row.get('reason','')).strip():raise ValueError('Justificativa ausente')
        duration=float(row.get('seconds',0))
        if not math.isfinite(duration) or duration<=0:raise ValueError('Tempo inválido')
    if seen!=expected:raise ValueError('Atribuições incompletas')
    return dict(rows=len(rows),pending_scores=missing,structural_only=True,
                warning='O validador não comprova identidade, independência ou realidade do trabalho humano.')


def capture(folder):
    folder.mkdir(); rows=annotations(); allocation=assignments()
    lines(folder/'cases.jsonl',cases()); table(folder/'annotations.csv',rows)
    lines(folder/'annotations.jsonl',rows); lines(folder/'adjudication_log.jsonl',adjudications(rows))
    write(folder/'assignments.json',allocation)
    for name in ('revisor_1','revisor_2'):
        group=[a for a in allocation if a['rater']==name]
        lines(folder/f'pacote_{name}.jsonl',group)
        template=[dict(rater=name,case_id=a['case_id'],rubric='r2',dimension=d,score='',reason='',seconds='')
                  for a in group for d in DIMENSIONS]
        table(folder/f'formulario_{name}.csv',template)
    (folder/'annotation_guide.md').write_text(
        '# Rubrica r2 e protocolo H\n\nTrilha H ainda não executada. Dois revisores reais devem trabalhar '
        'separadamente, sem ver a identificação da variante, rótulos autorais ou notas do colega. '
        'Suporte: 0 contradito, 1 parcialmente sustentado, 2 inteiramente sustentado. '
        'Completude: 0 omissão essencial que invalida a orientação, 1 parcial, 2 suficiente. '
        'Clareza: 0 incompreensível, 1 exige inferência evitável, 2 ação e condições legíveis. '
        'Nota vazia significa pendente com motivo, não zero. Fluência não comprova suporte. '
        'Calibração e teste usam famílias diferentes. Revise r2 apenas na calibração; '
        'registre novas versões e aplique ao teste somente depois de congelar critérios. '
        'Preserve originais e adicione adjudicação. Registre tempo observado por dimensão; '
        'não use os tempos sintéticos como estimativa de produtividade.\n',encoding='utf8')
    summary=summarize(rows); table(folder/'agreement.csv',summary);write(folder/'summary.json',summary)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--validar',type=Path,required=True)
    parser.add_argument('--atribuicoes',type=Path,required=True);args=parser.parse_args()
    with args.validar.open(encoding='utf8',newline='') as file: rows=list(csv.DictReader(file))
    print(json.dumps(validate_annotations(rows,json.loads(args.atribuicoes.read_text(encoding='utf8'))),ensure_ascii=False))
