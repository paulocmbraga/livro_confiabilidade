"""Preços fictícios em milésimos de real; políticas por regras, sem inferência."""
from dataclasses import dataclass, field
from .dados_ii import write,table,lines

PRICES=dict(small=30,large=90,review=200,infrastructure=10)
POLICIES=('grande','barato','roteado')


def tasks():
    return [dict(task=f'T{i:02}',segment='simples' if i<14 else 'dificil',
                 reference=i*2,input=i) for i in range(20)]


def run(policy,prices=None):
    if policy not in POLICIES:
        raise ValueError(policy)
    prices=PRICES if prices is None else prices
    ledger=[];results=[]
    for task in tasks():
        hard=task['segment']=='dificil'
        model='large' if policy=='grande' or (policy=='roteado' and hard) else 'small'
        components=[('infrastructure',1),(model,1)]
        review=False;latency=2 if model=='large' else 1
        # Uma resposta errada do pequeno provoca retry e revisão preparada.
        output=task['reference'] if model=='large' or not hard else -1
        if output!=task['reference']:
            components.extend([('small',2),('review',1)]);latency+=6;review=True
            # Duas das seis revisões não resolvem a tarefa, por construção.
            output=task['reference'] if task['input']%3!=0 else -1
        for component,attempt in components:
            ledger.append(dict(receipt=f'{policy}:{task["task"]}:{component}:{attempt}',
                policy=policy,task=task['task'],component=component,attempt=attempt,
                quantity=1,unit_mBRL=prices[component],amount_mBRL=prices[component],
                known=True))
        results.append(dict(task=task['task'],segment=task['segment'],policy=policy,
                            correct=output==task['reference'],review=review,
                            logical_latency=latency,
                            expected_receipts=[f'{policy}:{task["task"]}:{c}:{a}' for c,a in components]))
    return results,ledger


def aggregate(results,ledger):
    expected={r['task'] for r in results}
    if len(expected)!=len(results) or expected!={r['task'] for r in tasks()}:
        raise ValueError('População omitida ou duplicada')
    if any(r['task'] not in expected for r in ledger):
        raise ValueError('Recibo órfão')
    receipts={}
    for row in ledger:
        key=row['receipt']
        if key in receipts and receipts[key]!=row:
            raise ValueError('Recibo conflitante')
        receipts[key]=row
    expected_receipts={key for r in results for key in r['expected_receipts']}
    if set(receipts)-expected_receipts:
        raise ValueError('Cobrança sem chamada registrada')
    total=sum(r['amount_mBRL'] for r in receipts.values() if r['known'])
    unknown=sum(not r['known'] for r in receipts.values())+len(expected_receipts-set(receipts))
    correct=sum(r['correct'] for r in results)
    return dict(tasks=len(results),correct=correct,quality=correct/len(results),
        known_mBRL=total,unknown_receipts=unknown,
        cost_per_correct_mBRL=total/correct if correct and not unknown else None,
        review=sum(r['review'] for r in results),
        mean_logical_latency=sum(r['logical_latency'] for r in results)/len(results),
        segments={s:sum(r['correct'] for r in results if r['segment']==s)/sum(r['segment']==s for r in results)
                  for s in ('simples','dificil')})


@dataclass
class Budget:
    limit: int
    settled: int=0
    pending: dict=field(default_factory=dict)
    completed: dict=field(default_factory=dict)

    def reserve(self,key,maximum):
        if maximum<0 or key in self.pending or key in self.completed:
            raise ValueError('Reserva inválida')
        if self.settled+sum(self.pending.values())+maximum>self.limit:
            return False
        self.pending[key]=maximum;return True

    def settle(self,key,actual):
        if key in self.completed:
            if self.completed[key]!=actual:
                raise ValueError('Liquidação conflitante')
            return
        if key not in self.pending or not 0<=actual<=self.pending[key]:
            raise ValueError('Fora da reserva; requer reconciliação')
        self.settled+=actual;self.completed[key]=actual;del self.pending[key]


def choose(reports,minimum=.95):
    eligible={k:v for k,v in reports.items() if not v['unknown_receipts']
              and v['quality']>=minimum and all(q>=minimum for q in v['segments'].values())}
    return min(eligible,key=lambda k:eligible[k]['known_mBRL']) if eligible else None


def valid_price(snapshot,day):
    return snapshot['currency']=='BRL' and snapshot['valid_from']<=day<=snapshot['valid_to']


def capture(folder):
    folder.mkdir();allledger=[];results={};summaries={}
    for policy in POLICIES:
        results[policy],ledger=run(policy);allledger.extend(ledger)
        summaries[policy]=aggregate(results[policy],ledger)
    table(folder/'cost_ledger.csv',allledger)
    lines(folder/'task_results.jsonl',[r for rows in results.values() for r in rows])
    snapshot=dict(currency='BRL',unit='mBRL = R$ 0,001',prices=PRICES,
       valid_from='2026-10-18',valid_to='2026-10-18',source='tabela fictícia autoral; não é cotação')
    write(folder/'price_snapshot.json',snapshot)
    sensitivity=[]
    for review_price in (0,50,200,500):
        for policy in POLICIES:
            rows,ledger=run(policy,dict(PRICES,review=review_price))
            summary=aggregate(rows,ledger)
            for volume in (20,2000):
                sensitivity.append(dict(policy=policy,review_mBRL=review_price,volume=volume,
                    projected_mBRL=summary['known_mBRL']*volume//20,
                    correct_fraction=summary['quality'],
                    assumption='mistura e produtividade fixas; custo linear'))
    table(folder/'sensitivity.csv',sensitivity)
    _,ledger=run('roteado');ledger[0]['known']=False
    unknown=aggregate(results['roteado'],ledger)
    budget=Budget(200);budget.reserve('A',140);blocked=not budget.reserve('B',90)
    budget.settle('A',80);after=budget.reserve('B',90)
    probes=dict(unknown=unknown,budget=dict(blocked_while_pending=blocked,
               admitted_after_settlement=after,settled=budget.settled,pending=budget.pending),
               expired_price_accepted=valid_price(snapshot,'2026-10-19'))
    write(folder/'fault_probes.json',probes)
    decision=choose(summaries)
    (folder/'routing_decision.md').write_text(
        '# Decisão na bancada\n\nPolítica: '+str(decision)+
        '. Piso preparado: 95% no total e em cada segmento.\n\n'
        'Sem inferência estatística de não inferioridade; sem cotação comercial ou ROI.\n',encoding='utf8')
    return dict(policies=summaries,decision=decision,probes=probes)
