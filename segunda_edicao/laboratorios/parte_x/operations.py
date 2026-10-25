"""L38-L40: cenários em processos locais e estado persistido."""
from contextlib import contextmanager,ExitStack
from pathlib import Path
import copy,json,sqlite3,time
from .core import *
from .service import request
from laboratorios.parte_i.common import child,wait_file


@contextmanager
def service(folder,role,**kwargs):
    args=['--role',role,'--out',folder/'server']
    for k,v in kwargs.items():
        if isinstance(v,bool):
            if v:args.append('--'+k)
        else:args+=['--'+k,str(v)]
    with child('laboratorios.parte_x.service',args,folder/'process') as proc:
        wait_file(folder/'server/ready.json',proc)
        url=load(folder/'server/ready.json')['url']
        try:yield url,proc
        finally:
            if proc.poll() is None:
                request(url+'/stop');assert proc.wait(10)==0


class Journal:
    def __init__(self):self.rows=[];self.start=time.perf_counter()
    def call(self,url,path,data=None):
        before=time.perf_counter()-self.start
        try:
            status,body=request(url+path,data)
            self.rows.append(dict(path=path,data=data,status=status,body=body,started=before,ended=time.perf_counter()-self.start))
            return status,body
        except Exception as e:
            self.rows.append(dict(path=path,data=data,status='transport_unknown',error=type(e).__name__,started=before,ended=time.perf_counter()-self.start))
            raise


def release(out,models):
    out.mkdir();j=Journal();save(out/'stable.json',models['baseline']);save(out/'candidate.json',models['alias_bad'])
    with ExitStack() as stack:
        sink,_=stack.enter_context(service(out/'store','store',db=out/'state.sqlite'))
        stable,_=stack.enter_context(service(out/'stable','model',model=out/'stable.json',destination=sink))
        cand,_=stack.enter_context(service(out/'candidate','model',model=out/'candidate.json',destination=sink))
        shadow,_=stack.enter_context(service(out/'shadow','model',model=out/'candidate.json',destination=sink,shadow=True))
        population=[dict(id=f't{i:02}',x=-.2 if i==8 else .8,critical=i==8) for i in range(20)]
        paired=[]
        for row in population:
            a=j.call(stable,'/predict',{'x':row['x']})[1];b=j.call(shadow,'/predict',{'x':row['x']})[1]
            denied=j.call(shadow,'/effect',{'id':row['id'],'capability':'active'})
            assert denied[0]==403
            paired.append({**row,'old':a['prediction'],'new':b['prediction'],'correct':b['prediction']==int(row['x']>0)})
        shadow_state=j.call(sink,'/state')[1];assert not shadow_state['effects']
        # O canário abaixo é um controle negativo autorizado só na bancada.
        exposure=[];stopped=False
        for i,row in enumerate(population):
            candidate=i%4==0 and not stopped;url=cand if candidate else stable
            pred=j.call(url,'/predict',{'x':row['x']})[1]
            j.call(sink,'/admit',{'id':row['id'],'amount':100,'priority':int(row['critical'])})
            if pred['prediction']:j.call(url,'/effect',{'id':row['id']});j.call(sink,'/resolve',{'id':row['id']})
            else:j.call(sink,'/resolve',{'id':row['id'],'decision':'cancel'})
            r={**row,'candidate':candidate,'correct':pred['prediction']==int(row['x']>0)};exposure.append(r)
            if candidate and r['critical'] and not r['correct']:stopped=True
        j.call(sink,'/admit',{'id':'inflight','amount':1250})
        blocked=j.call(sink,'/migrate');assert blocked[0]==409
        # Cópia deliberadamente incompatível: banco original permanece íntegro.
        source=sqlite3.connect(out/'state.sqlite');dest=sqlite3.connect(out/'unsafe-copy.sqlite')
        source.backup(dest);source.close();dest.execute("UPDATE tasks SET schema=2 WHERE id='inflight'");dest.commit();dest.close()
        with service(out/'unsafe-copy','store',db=out/'unsafe-copy.sqlite') as (unsafe,_):
            wrong_reader=j.call(unsafe,'/read',{'id':'inflight','supported':[1]});assert wrong_reader[0]==409
            assert j.call(unsafe,'/read',{'id':'inflight','supported':[1,2]})[1]['state']=='pending'
        j.call(sink,'/resolve',{'id':'inflight','decision':'cancel','reason':'operator_fixture_no_effect'})
        migrated=j.call(sink,'/migrate');assert migrated[0]==200
        binary_rollback=j.call(sink,'/read',{'id':'t00','supported':[1]});assert binary_rollback[0]==409
        compatible=j.call(sink,'/read',{'id':'t00','supported':[1,2]});assert compatible[0]==200
        final=j.call(sink,'/state')[1]
    result=dict(shadow_attempts=20,shadow_denied=20,shadow_effects=0,paired_gate=release_gate(paired),
        canary_exposed=sum(r['candidate'] for r in exposure),critical_errors=sum(r['critical'] and not r['correct'] for r in exposure),
        candidate_after_stop=sum(r['candidate'] for r in exposure[9:]),synthetic_effects=len(final['effects']),
        open_migration_status=blocked[0],unsafe_copy_reader_status=wrong_reader[0],binary_rollback_status=binary_rollback[0],
        compatible_reader_status=compatible[0],preserved_amount_cents=compatible[1]['amount'],
        wall_seconds=time.perf_counter()-j.start,limit='Canário negativo após gate reprovado apenas para medir contenção no sandbox.')
    save(out/'paired.json',paired);save(out/'exposure.json',exposure);save(out/'journal.json',j.rows);save(out/'final.json',final);save(out/'result.json',result)
    return result


def incident(out,model):
    out.mkdir();j=Journal();save(out/'model.json',model)
    with service(out/'store','store',db=out/'state.sqlite') as (sink,_):
        with service(out/'worker','model',model=out/'model.json',destination=sink) as (worker,proc):
            j.call(sink,'/admit',{'id':'unknown','amount':250})
            injection=time.perf_counter()-j.start
            try:j.call(worker,'/effect',{'id':'unknown','crash_after_receipt':True})
            except (OSError,ValueError):pass
            else:raise AssertionError('Falha não observada')
            assert proc.wait(5)==23;detected=time.perf_counter()-j.start
            assert j.call(sink,'/mode',{'mode':'hold'})[0]==200
            contained=time.perf_counter()-j.start
        attempts=[]
        for i in range(8):attempts.append(j.call(sink,'/admit',{'id':f'review{i}','amount':100,'priority':2 if i==2 else 0})[0])
        highest=j.call(sink,'/next_review')[1];assert highest['id']=='review2'
        early=j.call(sink,'/mode',{'mode':'auto'});assert early[0]==409
        cancel=j.call(sink,'/resolve',{'id':'unknown','decision':'cancel'});assert cancel[0]==409
        assert j.call(sink,'/resolve',{'id':'unknown'})[1]['state']=='done'
        before=j.call(sink,'/state')[1]
    # Reinicia o destino com o mesmo arquivo: retenção de hold e recibo observadas.
    with service(out/'store-restarted','store',db=out/'state.sqlite') as (sink,_):
        restored=j.call(sink,'/state')[1];assert restored==before and restored['config']['mode']=='hold'
        for i in range(3):j.call(sink,'/resolve',{'id':f'review{i}','decision':'cancel','reason':'automated_fixture_not_human'})
        no_retest=j.call(sink,'/mode',{'mode':'auto'});assert no_retest[0]==409
        with service(out/'worker-restarted','model',model=out/'model.json',destination=sink) as (worker,_):
            blocked=j.call(worker,'/effect',{'id':'unknown'});assert blocked[0]==423
            probe=j.call(worker,'/predict',{'x':.8})[1]
            assert probe['prediction']==1
            j.call(sink,'/retest',{'passed':True});assert j.call(sink,'/mode',{'mode':'auto'})[0]==200
            returned=time.perf_counter()-j.start
            j.call(sink,'/admit',{'id':'after','amount':50});assert j.call(worker,'/effect',{'id':'after'})[0]==201
            j.call(sink,'/resolve',{'id':'after'});final=j.call(sink,'/state')[1]
    human=out/'human';human.mkdir()
    save(human/'responses.json',[])
    save(human/'coordinator.json',dict(release_schedule=[0,4,8],truth='worker died after destination committed',
        rubric=['não repetir efeito desconhecido','conter autonomia','limitar admissões','reconciliar recibos','exigir reteste'],
        hidden_material='Não entregar esta pasta de coordenação nem a captura integral aos participantes.'))
    for role in ['coordenacao','operacao']:
        folder=human/role;folder.mkdir()
        save(folder/'briefing.json',dict(role=role,scenario='Resposta perdida para tarefa unknown; três pendências de revisão.',
            constraints=['Não há acesso ao gabarito.','Solicite evidências por ID ao facilitador.','Registre hold ou return e justificativa.']))
        save(folder/'form.json',dict(participant_id=None,role=role,source='human',consent=False,started=None,decided=None,
            decision=None,evidence_ids=[],rationale=None))
    save(human/'cards.json',[
        dict(id='E1',release=0,visible='Cliente perdeu a conexão. Estado da tarefa: pending.'),
        dict(id='E2',release=4,visible='Destino contém recibo unknown=250; fila de revisão 3; 5 admissões recusadas.'),
        dict(id='E3',release=8,visible='Hold persistiu após reinício; reconciliação confirmou 1 efeito; reteste ainda pendente.')])
    result=dict(worker_exit=23,unknown_receipt_count=sum(r['id']=='unknown' for r in final['effects']),
        review_admitted=attempts.count(201),review_rejected=attempts.count(429),priority_first=highest['id'],
        early_return=early[0],cancel_existing_receipt=cancel[0],return_without_retest=no_retest[0],
        hold_persisted=restored['config']['mode']=='hold',final_effects=len(final['effects']),
        detection_wall_seconds=detected-injection,containment_wall_seconds=contained-injection,
        automated_return_wall_seconds=returned-injection,human=human_results([]),
        limit='Retorno automatizado da bancada; participantes e tempos humanos pendentes; sem perda do host.')
    save(out/'journal.json',j.rows);save(out/'final.json',final);save(out/'result.json',result);return result


def assurance(out):
    out.mkdir();j=Journal()
    context=dict(candidate='candidate-v1',population='synthetic-reserve',environment='loopback-sqlite',evaluator='oracle-v1',contract='effects-v1')
    body=dict(**context,issued=10,expires=30,assumption_expires=25,observed_claim='no-open-effects',outcome='passed',unresolved=0)
    cases=[]
    variations=[('valid',{}),('old',{'expires':19}),('wrong_model',{'candidate':'candidate-v2'}),
        ('expired_assumption',{'assumption_expires':20}),('wrong_population',{'population':'development'}),
        ('wrong_evaluator',{'evaluator':'judge-v9'}),('failed',{'outcome':'failed'}),('open',{'unresolved':1}),
        ('wrong_environment',{'environment':'production'}),('future',{'issued':21}),('wrong_contract',{'contract':'effects-v2'})]
    for name,change in variations:
        b={**body,**change};e={'body':b,'digest':digest(b)}
        cases.append(dict(name=name,evidence=e,decision=assess('no-open-effects',e,context,20)))
    corrupt={'body':body,'digest':'0'*64};cases.append(dict(name='corrupt',evidence=corrupt,decision=assess('no-open-effects',corrupt,context,20)))
    with service(out/'store','store',db=out/'state.sqlite') as (sink,_):
        j.call(sink,'/admit',{'id':'committed','amount':300});j.call(sink,'/admit',{'id':'unsent','amount':400})
        j.call(sink,'/effect',{'id':'committed','capability':'active'})
        j.call(sink,'/drain');admission=j.call(sink,'/admit',{'id':'late','amount':500});assert admission[0]==503
        premature=j.call(sink,'/archive',{'dependencies_closed':True});assert premature[0]==409
        # Documento positivo não prevalece sobre obrigações atuais no destino.
        j.call(sink,'/resolve',{'id':'committed'});j.call(sink,'/resolve',{'id':'unsent','decision':'cancel'})
        dependency=j.call(sink,'/archive',{'dependencies_closed':False});assert dependency[0]==409
        archived=j.call(sink,'/archive',{'dependencies_closed':True});assert archived[0]==200
        write=j.call(sink,'/effect',{'id':'committed','capability':'active'});assert write[0]==423
        receipt=j.call(sink,'/read',{'id':'committed','supported':[1]});assert receipt[0]==200
        final=j.call(sink,'/state')[1]
    result=dict(evidence_cases=len(cases),supported=sum(c['decision']['supported'] for c in cases),
        rejected=sum(not c['decision']['supported'] for c in cases),premature_archive=premature[0],
        unresolved_dependency=dependency[0],late_admission=admission[0],archived_write=write[0],
        receipt_readable=receipt[0],final_effects=len(final['effects']),
        open_tasks=sum(r['state'] in ('pending','review') for r in final['tasks']),
        wall_seconds=time.perf_counter()-j.start,
        limit='Dependencies_closed é declaração do controlador; sem assinatura, auditor independente ou custódia externa.')
    save(out/'context.json',context);save(out/'cases.json',cases);save(out/'journal.json',j.rows);save(out/'final.json',final);save(out/'result.json',result);return result
