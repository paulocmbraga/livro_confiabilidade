"""Contratos e medidas locais. Nenhuma proxy textual é tratada como semântica."""
import hashlib,json,threading

ACTION_SCHEMA={'type':'object','additionalProperties':False,'required':['action','item','quantity','version'],
 'properties':{'action':{'type':'string','enum':['inspect','reserve','finish','abstain']},
               'item':{'type':'string','enum':['A','B','']},'quantity':{'type':'integer'},'version':{'type':'integer'}}}
VOTE_SCHEMA={'type':'object','additionalProperties':False,'required':['approve','limit','source'],
 'properties':{'approve':{'type':'boolean'},'limit':{'type':'integer'},'source':{'type':'string'}}}

def parsed(response,schema):
    from jsonschema import validate
    c=response['choices'][0]
    if c['finish_reason']!='stop':raise ValueError('generation_not_completed')
    value=json.loads(c['message']['content']);validate(value,schema)
    return value

def choose(task,state):
    """Workflow determinístico recebe o mesmo estado observado disponível ao agente."""
    if state.get('receipt'):return dict(action='finish',item='',quantity=0,version=state['version'])
    for item in task['allowed']:
        if state['stock'][item]>=task['quantity'] and state['prices'][item]*task['quantity']<=task['ceiling']:
            return dict(action='reserve',item=item,quantity=task['quantity'],version=state['version'])
    return dict(action='abstain',item='',quantity=0,version=state['version'])

def admissible(task,state,proposal,observed):
    if not isinstance(proposal,dict) or set(proposal)!=set(ACTION_SCHEMA['required']):return 'schema'
    if proposal['action'] not in ACTION_SCHEMA['properties']['action']['enum']:return 'action'
    if proposal['item'] not in ['A','B','']:return 'item'
    if type(proposal['quantity']) is not int or type(proposal['version']) is not int:return 'type'
    if proposal['action']!='reserve':return None
    if not observed:return 'read_required'
    if proposal['item'] not in task['allowed']:return 'not_allowed'
    if proposal['quantity']!=task['quantity']:return 'quantity'
    if proposal['version']!=state['version']:return 'version_conflict'
    if state['prices'][proposal['item']]*proposal['quantity']>task['ceiling']:return 'ceiling'
    if state['stock'][proposal['item']]<proposal['quantity']:return 'stock'
    return None

def outcome(task,final,terminal):
    """Observador usa o destino; finish do modelo não decide sucesso."""
    effects=final['effects'];valid=[e for e in effects if e['intent']==task['id'] and
        e['item'] in task['allowed'] and e['quantity']==task['quantity'] and e['amount']<=task['ceiling']]
    other=[e for e in effects if e not in valid]
    feasible=any(final['stock'][x]>=task['quantity'] and final['prices'][x]*task['quantity']<=task['ceiling'] for x in task['allowed'])
    achieved=len(valid)==1 and not other
    correct_refusal=not effects and not feasible and terminal=='abstain'
    return {'goal_achieved':achieved,'correct_refusal':correct_refusal,'task_success':achieved or correct_refusal,
            'effects':len(effects),'duplicate_effects':max(0,len(valid)-1),'forbidden_effects':len(other),
            'false_finish':terminal=='finish' and not achieved}

def consensus(votes):
    valid=[v for v in votes if v is not None]
    # Quórum explícito: dois votos do mesmo sentido; ausência não é um voto negativo.
    yes=sum(v['approve'] for v in valid);no=len(valid)-yes
    return True if yes>=2 else False if no>=2 else None

def pair_error(votes,expected):
    errors=[None if v is None else v['approve']!=expected for v in votes]
    pairs=[(errors[a],errors[b]) for a in range(len(errors)) for b in range(a+1,len(errors)) if errors[a] is not None and errors[b] is not None]
    return {'errors':errors,'pairs':len(pairs),'both_wrong':sum(a and b for a,b in pairs)}

class Budget:
    """Reserva antes de admitir; confirma/reconcilia antes de reutilizar saldo."""
    def __init__(self,limit):
        if type(limit) is not int or limit<=0:raise ValueError('limit')
        self.limit=limit;self.held={};self.spent=0;self.lock=threading.Lock()
    def reserve(self,key,amount):
        with self.lock:
            if key in self.held or amount<=0 or type(amount) is not int:raise ValueError('reservation')
            if self.spent+sum(self.held.values())+amount>self.limit:return False
            self.held[key]=amount;return True
    def complete(self,key,used):
        with self.lock:
            if type(used) is not int or not 0<=used<=self.held[key]:raise ValueError('usage')
            self.held.pop(key);self.spent+=used
    def cancelled_before_call(self,key,process_ended):
        if not process_ended:raise ValueError('unconfirmed_cancellation')
        with self.lock:self.held.pop(key)

def artifact_binding(task,artifact):
    md=artifact.get('metadata',{})
    return all(md.get(k)==task[k] for k in ['task_id','context_id','intent','contract','audience'])

def apply_callback(state,event,expected):
    """Retorna nova cópia; autorização da conexão é verificada fora desta função."""
    if not artifact_binding(expected,event):return state,'binding_rejected'
    if event['event_id'] in state['seen']:return state,'duplicate'
    if type(event['sequence']) is not int or event['sequence']<=state['sequence']:return state,'old_event'
    if state['status'] in ['completed','cancelled'] and event['status']!=state['status']:return state,'terminal_regression'
    new={**state,'seen':state['seen']+[event['event_id']],'sequence':event['sequence'],'status':event['status']}
    return new,'accepted'
