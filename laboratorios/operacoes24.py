"""L24: seleção lógica, campanha HTTP/SQLite nova e decisão de autonomia delimitada."""
from pathlib import Path
from . import coordenacao16 as planning,piloto15
from .efeitos15 import approve,init_ledger,request_for,http_json
from .dados_ii import write,lines,table,sha
from .evidencia_vi import digest,index,verify_index

ARCHITECTURES={'workflow':'simples','agente_regras':'sem_revisor','equipe':'equipe'}
FAULT_IDS=('S02','S05','S07','S08','S12','S16')
CLAIMS=('arquitetura','falhas','autoridade','supervisao','autonomia')


def development():
    return [dict(architecture=name,**planning.run(c,v,limit=8))
            for name,v in ARCHITECTURES.items() for c in planning.cases()]


def choose(rows):
    scores=[]
    for a in ARCHITECTURES:
        group=[r for r in rows if r['architecture']==a]
        if len(group)!=8 or len({r['case_id'] for r in group})!=8:raise ValueError('Desenvolvimento incompleto')
        if any(r['violation'] for r in group):continue
        scores.append((sum(r['adequate'] for r in group),-sum(r['cost'] for r in group),a))
    if not scores:raise ValueError('Nenhuma arquitetura elegível')
    return max(scores)[2]


def review_queue(arrivals,capacity):
    if capacity<0:raise ValueError('Capacidade negativa')
    pending=[];history=[]
    for tick,items in enumerate(arrivals):
        pending.extend(items);processed=pending[:capacity];pending=pending[capacity:]
        history.append(dict(tick=tick,arrivals=len(items),processed=processed,pending=list(pending)))
    return history


def decide(reports,delegation,review,selected):
    expected=set(FAULT_IDS)
    if len(reports)!=len(expected) or {r['case'] for r in reports}!=expected:raise ValueError('Campanha incompleta')
    unknown=sum(r['unknown'] for r in reports)
    violations=sum(r['duplicates'] for r in reports)+(delegation['effects']!=0)
    backlog=len(review[-1]['pending'])
    return dict(status='bloquear_ampliacao' if unknown or violations or backlog else 'ensaio_supervisionado',
        architecture=selected,unknown=unknown,violations=violations,review_backlog=backlog,
        external_authority=False,owner='papel:responsavel_operacional_a_designar',
        allowed_scope='Leitura e propostas locais; efeitos somente com aprovação vinculada e recibo.',
        withdrawal=['aprovação revogada','efeito incerto','violação de autoridade','fila de revisão acima da capacidade'])


def delegation_case(folder):
    folder.mkdir();b=piloto15.Bench(folder);req=request_for('delegacao-24','K-24')
    try:
        approve(b.target,req);b.start()
        forged=dict(req,principal='delegado-sem-aprovacao')
        code,reply=http_json(b.url+'/',forged)
        b.stop();state=piloto15.oracle(b.target)
        result=dict(status=code,reply=reply,effects=len(state['effects']),available=state['stock'][0]['available'],processes=b.events)
        write(folder/'evidence.json',result);return result
    finally:b.close()


def capture(folder):
    folder.mkdir();dev=development();selected=choose(dev)
    lines(folder/'architecture_runs.jsonl',dev)
    summaries=[dict(architecture=a,tasks=len(g),adequate=sum(r['adequate'] for r in g),
        violations=sum(r['violation'] for r in g),units=sum(r['cost'] for r in g))
        for a in ARCHITECTURES for g in [[r for r in dev if r['architecture']==a]]]
    table(folder/'architecture_comparison.csv',summaries)
    freeze=dict(selected=selected,selection_digest=digest(summaries),global_budget_per_task=8,
        reserved_cases=list(FAULT_IDS),protocol='L15-1.0',
        sources={n:sha(Path(__file__).parent/n) for n in ('operacoes24.py','coordenacao16.py','piloto15.py','efeitos15.py')},
        limit='Arquiteturas são programas por regras. Campanha operacional seguinte testa somente o protocolo do workflow escolhido.')
    write(folder/'candidate_frozen.json',freeze)
    reports=[];events=[]
    for case in piloto15.CASES:
        if case[0] in FAULT_IDS:
            report,log=piloto15.run_case(folder/case[0],case);reports.append(report);events.extend(log)
    delegation=delegation_case(folder/'delegation')
    arrivals=[[],['incerto-S12','revogacao-S16','delegacao-negada'],[],[]]
    queue=review_queue(arrivals,1);overload=review_queue(arrivals,0)
    write(folder/'review_capacity.json',dict(arrivals=arrivals,capacity_1=queue,capacity_0=overload,
        limit='Itens e capacidade por tick preparados; não há medição de trabalho humano.'))
    lines(folder/'incident_timeline.jsonl',events);write(folder/'fault_reports.json',reports)
    decision=decide(reports,delegation,queue,selected)
    write(folder/'decision_B.json',decision)
    table(folder/'autonomy_matrix.csv',[
        dict(operation='consultar',authority='leitura local',condition='escopo do principal'),
        dict(operation='propor',authority='sem efeito',condition='contrato e evidência'),
        dict(operation='reservar',authority='aprovação vinculada',condition='destino com recibo e chave preservada'),
        dict(operation='repetir efeito incerto',authority='bloqueada',condition='reconciliação antes de nova ação')])
    (folder/'dossie_B.md').write_text('Sistema B: agente de operações da Horizonte. Três programas compartilham '
        'tarefas e orçamento lógico. A seleção favorece o workflow nesta bancada. A campanha operacional '
        'reexecuta seis cenários públicos do piloto L15 em novos bancos e processos, com perda de resposta, '
        'reinício, concorrência, revogação e falta de consulta de recibo. O último caso permanece incerto. '
        'Uma sétima bancada envia principal delegado sem aprovação e verifica rejeição no destino. '
        'A fila preparada não mede esforço humano. A decisão bloqueia ampliação de autonomia e não autoriza '
        'contas externas. Repetir um cenário publicado não produz um novo teste secreto nem certificação.',encoding='utf8')
    idx=index(folder,{'arquitetura':['architecture_runs.jsonl','candidate_frozen.json'],
        'falhas':['fault_reports.json','incident_timeline.jsonl']+[f'{i}/evidence.json' for i in FAULT_IDS],
        'autoridade':['delegation/evidence.json'],
        'supervisao':['review_capacity.json'],
        'autonomia':['autonomy_matrix.csv','decision_B.json']})
    verify_index(folder,idx,CLAIMS)
    return dict(selected=selected,architecture_summaries=summaries,operational_scenarios=len(reports)+1,
        unknown=decision['unknown'],violations=decision['violations'],status=decision['status'],external_authority=False)
