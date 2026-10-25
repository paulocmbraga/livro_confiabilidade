"""Contratos independentes do modelo e métricas com denominadores explícitos."""
import hashlib,json,math,re,unicodedata

def identity(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,
        separators=(',',':'),allow_nan=False).encode()).hexdigest()

def strict_json(text):
    def pairs(xs):
        d={}
        for k,v in xs:
            if k in d:raise ValueError('duplicate key')
            d[k]=v
        return d
    def constant(x):raise ValueError('nonfinite')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=constant)

def order_contract(text,complete,expected_config,received_config):
    if not complete:return {'accepted':False,'reason':'incomplete'}
    if expected_config!=received_config:return {'accepted':False,'reason':'configuration'}
    try:q=strict_json(text)
    except (ValueError,TypeError):return {'accepted':False,'reason':'syntax'}
    if not isinstance(q,dict) or set(q)!={'quantity'} or type(q['quantity']) is not int:
        return {'accepted':False,'reason':'schema'}
    if not 1<=q['quantity']<=99:return {'accepted':False,'reason':'domain'}
    return {'accepted':True,'reason':'accepted','quantity':q['quantity']}

def commit(store,operation,value):
    fingerprint=identity(value)
    if operation in store:
        if store[operation]!=fingerprint:raise ValueError('operation conflict')
        return 'replayed'
    store[operation]=fingerprint;return 'created'

def policy_metrics(rows,policy):
    accepted=[];blocked=[]
    for r in rows:
        ok=policy=='all' or (policy=='evidence' and r['kind']=='answerable')
        if policy=='reject_all':ok=False
        (accepted if ok else blocked).append(r)
    errors=sum(not r['correct'] for r in accepted);n=len(rows)
    # Utility of a correct answer +1, error -4, refusal -0.2. Didactic costs.
    return dict(n=n,accepted=len(accepted),errors=errors,coverage=len(accepted)/n if n else None,
        conditional_error=errors/len(accepted) if accepted else None,
        false_blocks=sum(r['kind']=='answerable' for r in blocked),
        utility=(len(accepted)-5*errors-.2*len(blocked))/n if n else None)

def judge_release(qualification):
    return bool(qualification.get('independent_reviewers',0)>=2 and
        qualification.get('heldout_adjudicated',False) and
        qualification.get('scope_matches',False) and qualification.get('threshold_validated',False))

def normalized(text):
    return re.findall(r'\w+', ''.join(c for c in unicodedata.normalize('NFD',text.lower())
        if unicodedata.category(c)!='Mn'))

def edit_distance(a,b):
    row=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        nxt=[i]
        for j,y in enumerate(b,1):nxt.append(min(nxt[-1]+1,row[j]+1,row[j-1]+(x!=y)))
        row=nxt
    return row[-1]

def wer(reference,hypothesis):
    a,b=normalized(reference),normalized(hypothesis)
    return edit_distance(a,b)/len(a) if a else None

def numeric(text):
    try:
        q=strict_json(text)
        x=q['value']
        if type(x) not in (int,float) or not math.isfinite(x):return None
        return x
    except (ValueError,KeyError,TypeError):return None
