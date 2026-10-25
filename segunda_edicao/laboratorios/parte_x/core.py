"""Contratos puros: treinamento, evidência e aprovação condicionada."""
import math
from laboratorios.parte_i.common import save,load,sha,digest,seal,check_manifest


def fit(rows):
    """ERM de um stump 1D; desempate determinístico, sem biblioteca externa."""
    if not rows:raise ValueError('Treino vazio')
    values=sorted({r['x'] for r in rows})
    thresholds=[values[0]-1]+[(a+b)/2 for a,b in zip(values,values[1:])]+[values[-1]+1]
    threshold=min(thresholds,key=lambda t:(sum(int(r['x']>t)!=r['y'] for r in rows),abs(t),t))
    return {'kind':'decision-stump-v1','threshold':threshold,'training_sha256':digest(rows),'n':len(rows)}


def predict(model,x):
    if not math.isfinite(x):raise ValueError('Entrada não finita')
    return int(x>model['threshold'])


def label_at(row,now):
    if now<row['arrives']:return None
    if now<row['revised_at']:return row['provisional']
    return row['y']


def mature(rows,now,width=5,lag=10):
    cutoff=now-lag
    cohort=[r for r in rows if cutoff-width<=r['cohort']<cutoff]
    known=[r for r in cohort if label_at(r,now) is not None]
    bad=sum(r['prediction']!=label_at(r,now) for r in known)
    n=len(cohort)
    return dict(n=n,known=len(known),bad=bad,error=bad/len(known) if known else None,
                coverage=len(known)/n if n else 0,cutoff=cutoff)


def release_gate(rows):
    if not rows:return {'pass':False,'reason':'sem amostra'}
    bad=sum(not r['correct'] for r in rows)
    critical=sum(not r['correct'] and r['critical'] for r in rows)
    return {'pass':bad/len(rows)<=.10 and critical==0,'bad':bad,'critical_bad':critical,'n':len(rows)}


CONTEXT_FIELDS=('candidate','population','environment','evaluator','contract')


def assess(claim,evidence,context,now):
    """Verifica pertinência e vigência; não certifica a verdade dos relatos."""
    reasons=[]
    if evidence.get('digest')!=digest(evidence.get('body')):reasons.append('integrity')
    body=evidence.get('body',{})
    for key in CONTEXT_FIELDS:
        if body.get(key)!=context.get(key):reasons.append(key)
    if not body.get('issued',math.inf)<=now<body.get('expires',-math.inf):reasons.append('validity')
    if body.get('observed_claim')!=claim:reasons.append('claim')
    if body.get('outcome')!='passed':reasons.append('result')
    if body.get('assumption_expires',-math.inf)<=now:reasons.append('assumption')
    if body.get('unresolved',1)!=0:reasons.append('unresolved')
    return {'supported':not reasons,'reasons':reasons}


def human_results(responses,expected=('coordenacao','operacao')):
    """Não produz participantes nem preenche respostas ausentes."""
    if not responses:return {'status':'pending','participants':0,'return_time_seconds':None}
    roles=[r.get('role') for r in responses]
    ids=[r.get('participant_id') for r in responses]
    if sorted(roles)!=sorted(expected) or len(set(ids))!=len(ids) or not all(ids):
        raise ValueError('Papéis ou participantes inválidos')
    for r in responses:
        if r.get('source')!='human' or not r.get('consent') or not r.get('evidence_ids'):
            raise ValueError('Resposta sem origem, consentimento ou evidência')
        if r.get('decision') not in ('hold','return'):raise ValueError('Decisão inválida')
        if not 0<=r['started']<=r['decided']:raise ValueError('Cronologia inválida')
    return {'status':'collected_unadjudicated','participants':len(responses),
            'return_time_seconds':[r['decided']-r['started'] for r in responses],
            'limit':'Autodeclaração não autentica participação; coordenador deve verificar.'}
