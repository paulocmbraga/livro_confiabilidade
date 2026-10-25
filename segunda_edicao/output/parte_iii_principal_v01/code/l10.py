"""Rubrica multidimensional e pacotes vazios; fixtures não são avaliações humanas."""
from pathlib import Path
from collections import Counter
import argparse,hashlib,html,json,math
from laboratorios.parte_i.common import ROOT,load,save,seal,sha

LABELS=(0,1,2,'U');DIMENSIONS=('support','sufficiency')

def agreement(a,b,weighted=False):
    if len(a)!=len(b) or not a:raise ValueError('paired nonempty')
    if any(type(x) is bool or x not in LABELS for x in a+b):raise ValueError('label')
    pairs=[(x,y) for x,y in zip(a,b) if x!='U' and y!='U'];n=len(pairs)
    if not n:return {'admitted':len(a),'comparable':0,'unknown':len(a),'agreement':None,'kappa':None}
    aa=Counter(x for x,_ in pairs);bb=Counter(y for _,y in pairs)
    weight=lambda x,y:1-abs(x-y)/2 if weighted else int(x==y)
    po=sum(weight(x,y) for x,y in pairs)/n
    pe=sum(aa[x]*bb[y]*weight(x,y) for x in range(3) for y in range(3))/n**2
    return {'admitted':len(a),'comparable':n,'unknown':len(a)-n,'agreement':po,'expected_agreement':pe,'kappa':None if pe==1 else (po-pe)/(1-pe),'weight':'linear' if weighted else 'nominal'}

def fixture():
    a=[2,2,1,1,0,0,2,1,0,2,1,0];b=[2,1,1,0,0,0,2,2,0,'U',1,0]
    return {'kind':'fixture_not_human','a':a,'b':b,'nominal':agreement(a,b),'linear':agreement(a,b,True),'actual_people':0}

def validate(form,ids,kind='human'):
    if form.get('kind')!=kind or form.get('rubric')!='L10-r1':raise ValueError('provenance/rubric')
    if kind=='human' and (not form.get('reviewer') or not form.get('collected_utc') or form.get('independent') is not True):raise ValueError('collection pending')
    rows=form.get('rows',[])
    if len(rows)!=len(ids) or {r['item'] for r in rows}!=set(ids):raise ValueError('cardinality')
    for r in rows:
        if any(type(r.get(d)) is bool or r.get(d) not in LABELS for d in DIMENSIONS):raise ValueError('pending rating')
        if not r.get('reason') or not r.get('evidence_ids'):raise ValueError('reason/evidence')
        sec=r.get('seconds')
        if type(sec) not in (int,float) or not math.isfinite(sec) or not 0<sec<=86400:raise ValueError('effort')
    return rows

def adjudicate(a,b,decisions):
    if len(a)!=len(b) or {r['item'] for r in a}!={r['item'] for r in b}:raise ValueError('pairing')
    second={r['item']:r for r in b};result=[]
    for r in a:
        other=second[r['item']]
        for dim in DIMENSIONS:
            key=r['item']+':'+dim;left,right=r[dim],other[dim]
            if left==right and left!='U':value=left;source='agreement'
            else:
                d=decisions.get(key)
                if d is None:value='U';source='unresolved'
                else:
                    if type(d.get('value')) is bool or d.get('value') not in LABELS or not d.get('reason') or not d.get('adjudicator'):raise ValueError('adjudication')
                    value=d['value'];source='adjudication'
            result.append({'item':r['item'],'dimension':dim,'original':[left,right],'reference':value,'source':source})
    return result

def packet(out):
    out.mkdir(parents=True,exist_ok=False)
    pairs=load(ROOT/'materiais/l11/pares.json');selected=[p for p in pairs if int(p['family'][1:])<=6 and p['id'].endswith(('Q1','Q2'))]
    raw=[]
    for p in selected:
        for c in p['candidates']:
            raw.append({'pair':p['id'],'family':p['family'],'split':p['split'],'candidate':c['id'],'question':p['question'],'evidence':p['evidence'],'answer':c['text'],'origin':c['origin'],'sha256':c['sha256']})
    raw.sort(key=lambda r:hashlib.sha256((r['pair']+r['candidate']+'L10').encode()).hexdigest())
    assert len(raw)==24
    mapping=[{'item':f'H{i:03}',**{k:r[k] for k in ['pair','family','split','candidate','origin','sha256']}} for i,r in enumerate(raw,1)]
    save(out/'coordenador_nao_distribuir.json',mapping)
    for n in (1,2):
        directory=out/f'revisor_{n}';directory.mkdir()
        items=[{'item':f'H{i:03}',**{k:r[k] for k in ['question','evidence','answer']}} for i,r in enumerate(raw,1)]
        # Ordem de apresentação diferente; IDs estáveis permitem parear depois.
        if n==2:items=items[::-1]
        save(directory/'itens.json',items)
        save(directory/'formulario.json',{'kind':'human','rubric':'L10-r1','reviewer':'','collected_utc':'','independent':False,'rows':[{'item':r['item'],'support':None,'sufficiency':None,'reason':'','evidence_ids':'','seconds':None} for r in items]})
        body=['<!doctype html><meta charset="utf-8"><title>L10: avaliação</title><style>body{max-width:900px;margin:32px auto;font:18px/1.6 Georgia}pre{white-space:pre-wrap;font:15px/1.5 monospace;background:#eee;padding:15px}article{border-top:1px solid #999}</style><h1>L10: avaliação independente</h1><p>Leia a rubrica. Não consulte o outro revisor, o coordenador ou os resultados dos modelos.</p>']
        for r in items:body.append('<article><h2>'+r['item']+'</h2>'+''.join('<h3>'+k+'</h3><pre>'+html.escape(r[k])+'</pre>' for k in ['question','evidence','answer'])+'</article>')
        (directory/'itens.html').write_text('\n'.join(body)+'\n',encoding='utf-8',newline='\n')
        (directory/'RUBRICA.md').write_text((ROOT/'materiais/parte_iii/RUBRICA_L10.md').read_text(encoding='utf-8'),encoding='utf-8',newline='\n')
    save(out/'estado.json',{'status':'pending','items':24,'planned_initial_judgments':48,'collected':0,'custodian':None,'original_L11_packet_unchanged':True})
    seal(out,'L10-human-packet-pending')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--packet',type=Path);p.add_argument('--check-form',type=Path);p.add_argument('--items',type=Path);a=p.parse_args()
    if a.packet:packet(a.packet)
    else:print(len(validate(load(a.check_form),[r['item'] for r in load(a.items)])))
