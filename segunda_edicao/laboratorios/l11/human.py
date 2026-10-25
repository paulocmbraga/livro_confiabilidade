"""Ingestão humana explícita; campos vazios nunca se tornam rótulos negativos."""
from pathlib import Path
import argparse,csv,hashlib,html,json,shutil
from .core import ROOT,load,save,sha,gate,brier,wilson

VERDICTS={'X','Y','tie','review'}
FIELDS=['item','choice','support_X','support_Y','reason','evidence_ids','minutes']

def packet(out):
    out.mkdir(parents=True,exist_ok=False)
    pairs=load(ROOT/'materiais/l11/pares.json');mapping=[];items=[]
    # Sorteio determinístico oculto ao avaliador. Não entrega split, origem ou saída do juiz.
    ordered=sorted(pairs,key=lambda p:hashlib.sha256(('blind11:'+p['id']).encode()).hexdigest())
    for n,p in enumerate(ordered,1):
        reverse=hashlib.sha256(('order11:'+p['id']).encode()).digest()[0]%2
        cs=p['candidates'][::-1] if reverse else p['candidates']
        item=f'H{n:03}'
        mapping.append({'item':item,'pair':p['id'],'X':cs[0]['id'],'Y':cs[1]['id']})
        items.append({'item':item,'question':p['question'],'evidence':p['evidence'],
                      'X':cs[0]['text'],'Y':cs[1]['text']})
    save(out/'coordenador_nao_distribuir.json',mapping)
    for reviewer in ('revisor_1','revisor_2'):
        d=out/reviewer;d.mkdir()
        shutil.copy2(ROOT/'materiais/l11/RUBRICA_HUMANA.md',d/'RUBRICA.md')
        with (d/'formulario.csv').open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader()
            w.writerows(dict.fromkeys(FIELDS,'')|{'item':x['item']} for x in items)
        body=['<!doctype html><meta charset="utf-8"><title>L11: avaliação independente</title>',
              '<style>body{max-width:850px;margin:36px auto;font:18px/1.55 Georgia}pre{white-space:pre-wrap;font:15px/1.5 monospace;background:#f4f5f6;padding:16px}article{border-top:1px solid #999;margin-top:32px}</style>',
              '<h1>Avaliação L11</h1><p>Leia a rubrica. Não consulte o outro revisor, o mapa do coordenador nem os vereditos automáticos.</p>']
        for x in items:
            body.append('<article><h2>'+x['item']+'</h2><p>'+html.escape(x['question'])+'</p>')
            for key,label in [('evidence','Evidências'),('X','Resposta X'),('Y','Resposta Y')]:
                body.append('<h3>'+label+'</h3><pre>'+html.escape(x[key])+'</pre>')
            body.append('</article>')
        (d/'itens.html').write_text('\n'.join(body),encoding='utf-8')
    save(out/'participantes_pendente.json',{'reviewers':[
        {'pseudonym':'','experience':'','relationship_to_development':'','independent_collection_confirmed':False},
        {'pseudonym':'','experience':'','relationship_to_development':'','independent_collection_confirmed':False}],
        'collected':False})
    save(out/'manifesto.json',{'items':40,'initial_judgments_expected':80,'actual_human_judgments':0,
         'status':'pending','files':{p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()}})

def read_form(path,mapping):
    with Path(path).open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
    keys={r['item'] for r in rows}
    if len(rows)!=40 or len(keys)!=40 or keys!=set(mapping):raise ValueError('40 itens únicos obrigatórios')
    result={}
    for r in rows:
        if r['choice'] not in VERDICTS or not r['reason'].strip():raise ValueError('avaliação pendente/inválida')
        if r['support_X'] not in ('yes','no','unclear') or r['support_Y'] not in ('yes','no','unclear'):raise ValueError('suporte')
        minutes=float(r['minutes'])
        if not 0<minutes<1440 or not r['evidence_ids'].strip():raise ValueError('tempo/evidência')
        m=mapping[r['item']];result[m['pair']]=dict(r,canonical=m.get(r['choice'],r['choice']))
    return result

def references(packet_dir,adjudication=None):
    people=load(packet_dir/'participantes_pendente.json')
    rs=people['reviewers']
    if not people['collected'] or len(rs)!=2:raise ValueError('coleta humana pendente')
    if len({r['pseudonym'].strip() for r in rs})!=2 or any(
        not r['pseudonym'].strip() or not r['experience'].strip() or not r['relationship_to_development'].strip()
        or r['independent_collection_confirmed'] is not True for r in rs):raise ValueError('metadados de independência')
    mapping={r['item']:r for r in load(packet_dir/'coordenador_nao_distribuir.json')}
    a,b=[read_form(packet_dir/x/'formulario.csv',mapping) for x in ('revisor_1','revisor_2')]
    adjud=load(adjudication) if adjudication else {}
    result={};disagreements=[]
    for key in a:
        if a[key]['canonical']==b[key]['canonical']:result[key]=a[key]['canonical']
        else:
            disagreements.append(key);record=adjud.get(key)
            if record is None:result[key]=None
            elif record.get('choice') not in VERDICTS or not record.get('reason') or not record.get('adjudicator'):
                raise ValueError('adjudicação incompleta')
            else:result[key]=record['choice']
    return result,disagreements

def policy_curve(rows,pairs,refs):
    if any(p['split']!='calibration' for p in pairs):raise ValueError('ajuste somente na calibração')
    if any(refs.get(p['id']) not in ('X','Y','tie') for p in pairs):raise ValueError('referência incompleta/indecidível')
    curves=[]
    for threshold in (.5,.6,.7,.8,.9,1.):
        admitted=[]
        for p in pairs:
            vv=[r['parsed'] for r in rows if r['trial']['pair']==p['id'] and r['trial']['mode']=='base']
            g=gate(vv,p['risk'],threshold)
            if g['winner'] is not None:admitted.append(g['winner']!=refs[p['id']])
        curves.append(dict(threshold=threshold,automatic=len(admitted),total=len(pairs),
                           coverage=len(admitted)/len(pairs),errors=sum(admitted),
                           error_rate=sum(admitted)/len(admitted) if admitted else None,
                           wilson_descriptive=wilson(sum(admitted),len(admitted))))
    eligible=[c for c in curves if c['coverage']>=.25 and c['errors']==0]
    return {'threshold':min(c['threshold'] for c in eligible) if eligible else None,'curve':curves}

def evaluate(capture,packet_dir,adjudication=None):
    from .verify import verify
    verify(capture)
    if load(capture/'state.json')['smoke']:raise ValueError('campanha principal obrigatória')
    refs,disagreements=references(packet_dir,adjudication)
    pairs=load(capture/'materials/pares.json');rows=[load(p) for p in sorted((capture/'raw').glob('*.json'))]
    result={'human_disagreements':disagreements,'reference':refs,'judges':{},
            'warning':'Coleta declarada não prova independência; piloto não qualifica produção.'}
    for judge in ('qwen','smol'):
        selected=[r for r in rows if r['trial']['judge']==judge and r['trial']['mode']=='base']
        calibration=[p for p in pairs if p['split']=='calibration']
        if any(refs.get(p['id']) not in ('X','Y','tie') for p in calibration):
            result['judges'][judge]={'status':'reference_incomplete','calibration':None};continue
        fit=policy_curve(selected,calibration,refs);groups=[]
        strata=[('split',v) for v in ('calibration','test')]
        strata += [('family',v) for v in sorted({p['family'] for p in pairs})]
        strata += [('segment',v) for v in sorted({p['segment'] for p in pairs})]
        for dimension,value in strata:
            ps=[p for p in pairs if p[dimension]==value];gs=[];unresolved=0;valid_direct=[];automatic=0
            for p in ps:
                rr=[r for r in selected if r['trial']['pair']==p['id']]
                g=gate([r['parsed'] for r in rr],p['risk'],fit['threshold']) if fit['threshold'] is not None else {'winner':None}
                if g['winner'] is not None:automatic+=1
                if refs.get(p['id']) not in ('X','Y','tie'):unresolved+=1;continue
                valid_direct += [(r['parsed']['confidence'],int(r['parsed']['winner']==refs[p['id']]))
                                 for r in rr if r['parsed']['valid'] and r['parsed']['winner'] in ('X','Y')]
                if g['winner'] is not None:gs.append(int(g['winner']!=refs[p['id']]))
            groups.append(dict(dimension=dimension,stratum=value,total=len(ps),unresolved=unresolved,automatic=automatic,
                evaluated_automatic=len(gs),errors=sum(gs),error_rate=sum(gs)/len(gs) if gs else None,coverage=automatic/len(ps),
                brier_direct=brier(*map(list,zip(*valid_direct))) if valid_direct else None,
                brier_denominator=len(valid_direct)))
        result['judges'][judge]={'status':'descriptive_only','calibration':fit,'groups':groups}
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['packet','evaluate']);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--packet',type=Path);p.add_argument('--capture',type=Path);p.add_argument('--adjudication',type=Path);a=p.parse_args()
    if a.mode=='packet':packet(a.out)
    else:
        if a.out.exists():raise FileExistsError(a.out)
        save(a.out,evaluate(a.capture,a.packet,a.adjudication))

if __name__=='__main__':main()
