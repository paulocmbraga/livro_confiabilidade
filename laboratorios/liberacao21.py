"""L21: gates vinculados a versões, shadow local e migração de checkpoints."""
from copy import deepcopy
import sqlite3
from .dados_ii import write,lines
from .evidencia_vi import digest

COMPONENTS=('code','model','prompt','corpus','policy','evaluator','config')
CASES=[dict(id=f'T{i:02}',segment='raro' if i>=16 else 'comum') for i in range(20)]
SUITES={'unit':('U1','U2'),'regression':('G1','G2'),'reserved':tuple(c['id'] for c in CASES)}
RISK={'code':set(SUITES),'model':set(SUITES),'prompt':{'regression','reserved'},
      'corpus':{'regression','reserved'},'policy':set(SUITES),
      'evaluator':set(SUITES),'config':set(SUITES)}


def manifest():
    components={k:digest(dict(component=k,version=2,mode='prepared')) for k in COMPONENTS}
    return dict(schema='livro.release/1',components=components,
                release_id=digest(components),changed=['code','prompt'],state_schema=2)


def package():
    m=manifest();subject=m['release_id']
    suites={name:dict(subject=subject,expected=list(ids),
        rows=[dict(id=i,passed=True) for i in ids]) for name,ids in SUITES.items()}
    return dict(manifest=m,suites=suites,
        observed_components=deepcopy(m['components']),
        migration=dict(subject=subject,old_reader_v2=False,pending_pinned_v1=True,
            identity_preserved=True,readers_agree=True),
        rollout=dict(subject=subject,shadow_effects=0,canary_denominator=10,
            candidate_tasks=2,return_drill=True))


def required_suites(changed):
    if any(c not in RISK for c in changed):return set(SUITES)
    return set().union(*(RISK[c] for c in changed)) if changed else set(SUITES)


def gate(p):
    m=p['manifest'];reasons=[];subject=m.get('release_id')
    components=m.get('components',{})
    if set(components)!=set(COMPONENTS):reasons.append('componentes_incompletos')
    if subject!=digest(components):reasons.append('identidade_invalida')
    if p.get('observed_components')!=components:reasons.append('execucao_divergente')
    scores={}
    for name in sorted(required_suites(m.get('changed',[]))):
        suite=p.get('suites',{}).get(name)
        if not suite:reasons.append('suite_ausente:'+name);continue
        if suite.get('subject')!=subject:reasons.append('sujeito_divergente:'+name)
        rows=suite.get('rows',[]);ids=[r['id'] for r in rows]
        # O denominador vem da política do gate, não do relatório candidato.
        if (set(ids)!=set(SUITES[name]) or len(ids)!=len(SUITES[name])
            or suite.get('expected')!=list(SUITES[name])):
            reasons.append('suite_incompleta:'+name)
        if name!='reserved' and not all(r['passed'] is True for r in rows):
            reasons.append('regressao:'+name)
        if name=='reserved':
            lookup={r['id']:r for r in rows}
            for segment in ('comum','raro'):
                group=[c for c in CASES if c['segment']==segment]
                good=sum(lookup.get(c['id'],{}).get('passed') is True for c in group)
                scores[segment]=dict(good=good,total=len(group),rate=good/len(group))
                if good/len(group)<.95:reasons.append('piso_segmento:'+segment)
    migration=p.get('migration',{});rollout=p.get('rollout',{})
    if migration.get('subject')!=subject:reasons.append('migracao_sem_vinculo')
    if not all(migration.get(k) is True for k in ('pending_pinned_v1','identity_preserved','readers_agree')):
        reasons.append('retorno_inseguro')
    if rollout.get('subject')!=subject:reasons.append('exposicao_sem_vinculo')
    if rollout.get('shadow_effects')!=0:reasons.append('efeito_em_shadow')
    if (rollout.get('canary_denominator')!=10 or rollout.get('candidate_tasks')!=2
            or rollout.get('return_drill') is not True):reasons.append('exposicao_incompleta')
    return dict(accepted=not reasons,reasons=reasons,scores=scores,subject=subject,
                scope='ensaio local preparado; não é autorização de produção')


def checkpoint_v2(old):
    if old['schema']!=1:raise ValueError('Esquema de origem')
    return dict(schema=2,intent=old['intent'],key=old['key'],status=old['status'],
                payload=dict(quantity=old['quantity']),origin_schema=1)


def read_checkpoint(value,reader):
    if reader==1 and value['schema']!=1:raise ValueError('Leitor antigo incompatível')
    if reader not in (1,2) or value['schema'] not in (1,2):raise ValueError('Esquema desconhecido')
    quantity=value['quantity'] if value['schema']==1 else value['payload']['quantity']
    return value['intent'],value['key'],quantity,value['status']


def rollout(path,unsafe=False):
    db=sqlite3.connect(path)
    try:
        db.execute('CREATE TABLE effects(task TEXT, key TEXT UNIQUE, version TEXT)')
        events=[]
        for i in range(10):
            task=f'C{i:02}';version='candidate' if i in (0,5) else 'baseline'
            db.execute('INSERT INTO effects VALUES(?,?,?)',(task,task,version))
            events.append(dict(task=task,channel='live_local',version=version,key=task))
            # Shadow constrói proposta, mas não ganha a capacidade de escrita.
            events.append(dict(task=task,channel='shadow',version='candidate',key=task))
            if unsafe:db.execute('INSERT INTO effects VALUES(?,?,?)',(task,task+'-shadow','candidate'))
        db.commit()
        count=db.execute('SELECT COUNT(*) FROM effects').fetchone()[0]
        return dict(offered=10,candidate_tasks=2,shadow_effects=count-10,
                    effects=count,duplicate_tasks=count-10,events=events)
    finally:db.close()


def scenarios():
    good=package();result={'completo':good}
    p=deepcopy(good);p['suites']['reserved']['rows'].pop();result['reservado_incompleto']=p
    p=deepcopy(good);p['suites']['reserved']['rows'][-1]['passed']=False;result['regressao_rara']=p
    p=deepcopy(good);p['observed_components']['model']=digest('outro');result['modelo_trocado']=p
    p=deepcopy(good);p['migration']['identity_preserved']=False;result['migracao_incompativel']=p
    p=deepcopy(good);p['suites']['reserved']['subject']='outra-versao';result['evidencia_antiga']=p
    p=deepcopy(good);p['rollout']['shadow_effects']=10;result['shadow_com_efeito']=p
    return result


def capture(folder):
    folder.mkdir();safe=rollout(folder/'rollout_safe.sqlite');unsafe=rollout(folder/'rollout_unsafe.sqlite',True)
    old=dict(schema=1,intent='I-21',key='K-21',status='unknown',quantity=2)
    new=checkpoint_v2(old);same=read_checkpoint(old,1)==read_checkpoint(new,2)
    try:read_checkpoint(new,1)
    except ValueError:old_reader=False
    else:old_reader=True
    migration=dict(subject=manifest()['release_id'],old_reader_v2=old_reader,
        pending_pinned_v1=True,identity_preserved=same,readers_agree=read_checkpoint(old,2)==read_checkpoint(new,2))
    packages=scenarios();packages['completo']['migration']=migration
    packages['completo']['rollout'].update(shadow_effects=safe['shadow_effects'],
        candidate_tasks=safe['candidate_tasks'],canary_denominator=safe['offered'])
    results={k:gate(v) for k,v in packages.items()}
    write(folder/'release_manifest.json',manifest());write(folder/'packages.json',packages)
    write(folder/'gate_results.json',results);write(folder/'rollout.json',dict(safe=safe,unsafe=unsafe))
    write(folder/'migration.json',dict(before=old,after=new,report=migration))
    (folder/'release_decision.md').write_text('Somente o pacote completo passa nos critérios didáticos. '
        'A suíte unitária passa também nas seis contraprovas. O gate exige evidências da mesma versão, '
        'completude e piso por segmento. Shadow seguro não escreve; o controle inseguro duplica dez tarefas. '
        'O leitor v1 não lê estado v2: voltar o binário exige preservar tarefas antigas ou outra estratégia ensaiada. '
        'Os relatórios de qualidade são preparados; hashes não são assinatura digital nem prova de origem.',encoding='utf8')
    return dict(packages=len(results),accepted=[k for k,v in results.items() if v['accepted']],
        unit_only_accepts=len(results),safe_effects=safe['effects'],unsafe_effects=unsafe['effects'],
        old_reader_v2=old_reader)
