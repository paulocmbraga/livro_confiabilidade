"""L34: replay determinístico de tempo de evento e atraso de rótulos."""
from .core import save,alert,cohort


def events():
    rows=[]
    for minute in range(180):
        for j in range(10):
            # Degradação de domínio entre 60 e 89; HTTP continua disponível.
            good=not (60<=minute<90 and j<3)
            # Observação cessa independentemente do domínio entre 110 e 129.
            observed=not 110<=minute<130
            label_at=None if (140<=minute<150 and j<2) else minute+(12 if j==9 else 3)
            rows.append(dict(id=f'{minute}-{j}',at=minute,segment='complex' if j<3 else 'simple',
                good=good,http_ok=True,observed=observed,label_at=label_at))
    return rows


def run(out):
    out.mkdir();data=events();save(out/'events.json',data)
    views=[dict(now=t,**alert(data,t)) for t in range(35,191)]
    save(out/'evaluations.json',views)
    # Episódios contíguos, não pontos repetidos, para contar notificações.
    def episodes(name):
        result=[];start=None
        for row in views:
            if row[name] and start is None:start=row['now']
            if not row[name] and start is not None:result.append([start,row['now']]);start=None
        if start is not None:result.append([start,views[-1]['now']+1])
        return result
    quality=episodes('quality');observation=episodes('observation')
    save(out/'result.json',dict(quality_episodes=quality,observation_episodes=observation,
        detection_delay=quality[0][0]-60 if quality else None,
        quality_false_episodes=sum(not (60<=a<105) for a,b in quality),
        quality_bad_tasks_before_detection=sum(not e['good'] and e['at']<(quality[0][0] if quality else 180) for e in data),
        final=cohort(data,192,180,lag=12),
        example_unknown=cohort(data,132,5),
        domain_window=cohort(data,102,30),
        truth_scope='authorial synthetic reference; no human labels or model judge'))
