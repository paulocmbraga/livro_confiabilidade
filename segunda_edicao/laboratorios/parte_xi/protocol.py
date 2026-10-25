"""MCP 2026-07-28, A2A 1.0, SQLite; credenciais públicas de bancada."""
import argparse,asyncio,json,socket,sqlite3
from contextlib import closing
from pathlib import Path
import uvicorn
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.applications import Starlette
from laboratorios.parte_vii.protocol_server import LabAuth
from .core import save,load,proposal
from .inference import infer,PLAN

class Ledger:
    def __init__(self,path):
        self.path=path
        with closing(sqlite3.connect(path)) as db:
            db.executescript("CREATE TABLE IF NOT EXISTS cfg(v TEXT); INSERT INTO cfg SELECT 'v1' WHERE NOT EXISTS(SELECT 1 FROM cfg); CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY,quantity INTEGER,contract TEXT,status TEXT); CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,quantity INTEGER,contract TEXT);")
            db.commit()
    def call(self,action,data):
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory=sqlite3.Row;db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT v FROM cfg').fetchone()[0]
            row=db.execute('SELECT * FROM intents WHERE id=?',(data.get('intent',''),)).fetchone()
            receipt=db.execute('SELECT * FROM receipts WHERE id=?',(data.get('intent',''),)).fetchone()
            if action=='prepare':
                if data.get('contract')!=current:return {'ok':False,'reason':'contract'}
                if type(data.get('quantity')) is not int or data['quantity']!=1:return {'ok':False,'reason':'quantity'}
                if row:
                    return {'ok':row['quantity']==data['quantity'] and row['contract']==data['contract'],'reason':'existing'}
                db.execute('INSERT INTO intents VALUES(?,?,?,?)',(data['intent'],1,current,'open'));result={'ok':True}
            elif action=='reserve':
                if not row or data.get('contract')!=row['contract'] or data.get('quantity')!=row['quantity']:return {'ok':False,'reason':'binding'}
                if data['contract']!=current:return {'ok':False,'reason':'current_contract'}
                if not receipt:
                    if row['status']!='open':return {'ok':False,'reason':'closed'}
                    db.execute('INSERT INTO receipts VALUES(?,?,?)',(row['id'],row['quantity'],row['contract']))
                result={'ok':True,'receipt':dict(receipt) if receipt else {'id':row['id'],'quantity':row['quantity'],'contract':row['contract']}}
            elif action=='reconcile':return {'ok':True,'receipt':dict(receipt) if receipt else None,'current':current}
            elif action=='ack':
                if not receipt:return {'ok':False,'reason':'no_receipt'}
                db.execute("UPDATE intents SET status='done' WHERE id=?",(data['intent'],));result={'ok':True,'receipt':dict(receipt)}
            elif action=='migrate':
                if db.execute("SELECT count(*) FROM intents WHERE status='open'").fetchone()[0]:return {'ok':False,'reason':'open_obligations'}
                if data.get('to') not in ('v1','v2'):return {'ok':False,'reason':'schema'}
                db.execute('UPDATE cfg SET v=?',(data['to'],));result={'ok':True,'current':data['to']}
            elif action=='state':return {'current':current,'intents':[dict(x) for x in db.execute('SELECT * FROM intents ORDER BY id')],'receipts':[dict(x) for x in db.execute('SELECT * FROM receipts ORDER BY id')]}
            else:raise ValueError(action)
            db.commit();return result

def mcp_app(folder,db):
    from mcp.server import MCPServer
    from mcp.server.mcpserver.context import Context
    m=MCPServer('L43 reservas persistentes',version='1.0');ledger=Ledger(db)
    @m.tool()
    async def reserve(intent:str,quantity:int,contract:str,lose_reply:bool,ctx:Context)->dict:
        result=ledger.call('reserve',dict(intent=intent,quantity=quantity,contract=contract))
        if result['ok'] and lose_reply:
            await ctx.report_progress(1,2,'effect_committed')
            await asyncio.sleep(30)
        return result
    @m.tool()
    def reconcile(intent:str)->dict:return ledger.call('reconcile',{'intent':intent})
    async def admin(request):
        return JSONResponse(ledger.call(request.path_params['action'],await request.json()))
    app=m.streamable_http_app(host='127.0.0.1');app.routes.append(Route('/admin/{action}',admin,methods=['POST']))
    return LabAuth(app,'mcp')

def a2a_app(folder,url,llm,model):
    from a2a.server.agent_execution import AgentExecutor
    from a2a.server.tasks import TaskUpdater,InMemoryTaskStore
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
    from a2a.server.routes.agent_card_routes import create_agent_card_routes
    from a2a.types import AgentCard,AgentInterface,AgentCapabilities,AgentSkill,Task,TaskStatus,TaskState,Part
    gate=asyncio.Event()
    class Executor(AgentExecutor):
        async def execute(self,context,event_queue):
            request=json.loads(context.get_user_input());save(folder/('admission_'+context.task_id+'.json'),request)
            await event_queue.enqueue_event(Task(id=context.task_id,context_id=context.context_id,status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED)))
            updater=TaskUpdater(event_queue,context.task_id,context.context_id)
            await updater.update_status(TaskState.TASK_STATE_WORKING)
            if request.get('pause'):await gate.wait()
            prompt='Revise a reserva. Autorize somente authorized=true e quantity=1. Retorne action reserve ou hold e quantity. Pedido: '+json.dumps(request)
            result=await asyncio.to_thread(infer,llm,model,prompt,PLAN,folder/('inference_'+context.task_id+'.json'))
            binding=dict(task_id=context.task_id,context_id=context.context_id,intent=request['intent'],contract=request['contract'],audience='controller')
            await updater.add_artifact([Part(text=result['text'])],artifact_id='review-'+context.task_id,name='bounded_review',metadata=binding)
            await updater.update_status(TaskState.TASK_STATE_COMPLETED)
        async def cancel(self,context,event_queue):
            await TaskUpdater(event_queue,context.task_id,context.context_id).update_status(TaskState.TASK_STATE_CANCELED)
    card=AgentCard(name='Especialista L43',description='Revisão local com inferência',version='1.0',supported_interfaces=[AgentInterface(url=url+'/a2a',protocol_binding='JSONRPC',protocol_version='1.0')],capabilities=AgentCapabilities(streaming=True,push_notifications=False),default_input_modes=['text/plain'],default_output_modes=['text/plain'],skills=[AgentSkill(id='review',name='Review',description='Proposta limitada',tags=['lab'])])
    handler=DefaultRequestHandler(Executor(),InMemoryTaskStore(),card)
    async def release(request):gate.set();return JSONResponse({'released':True})
    return LabAuth(Starlette(routes=create_jsonrpc_routes(handler,'/a2a')+create_agent_card_routes(card)+[Route('/release',release,methods=['POST'])]),'a2a')

def main():
    p=argparse.ArgumentParser();p.add_argument('--kind',choices=['mcp','a2a'],required=True);p.add_argument('--folder',type=Path,required=True);p.add_argument('--db',type=Path);p.add_argument('--llm');p.add_argument('--model');a=p.parse_args()
    a.folder.mkdir(parents=True,exist_ok=False)
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128);url=f'http://127.0.0.1:{sock.getsockname()[1]}'
    app=mcp_app(a.folder,a.db) if a.kind=='mcp' else a2a_app(a.folder,url,a.llm,a.model)
    save(a.folder/'ready.json',dict(url=url,kind=a.kind));uvicorn.Server(uvicorn.Config(app,log_level='warning')).run(sockets=[sock])
if __name__=='__main__':main()
