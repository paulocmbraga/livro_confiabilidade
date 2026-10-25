"""Serviços reais dos SDKs. Credenciais públicas de bancada, apenas loopback."""
import argparse,asyncio,json,socket
from pathlib import Path
import uvicorn
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.applications import Starlette
from starlette.authentication import SimpleUser,AuthCredentials
from laboratorios.parte_i.common import save,load

class LabAuth:
    def __init__(self,app,audience):self.app=app;self.audience=audience
    async def __call__(self,scope,receive,send):
        if scope['type']=='http':
            h=dict(scope['headers'])
            if h.get(b'authorization')!=('Bearer lab-'+self.audience).encode():
                return await JSONResponse({'error':'fixture_audience_or_token'},status_code=401)(scope,receive,send)
            scope['user']=SimpleUser('lab-author');scope['auth']=AuthCredentials(['authenticated'])
        await self.app(scope,receive,send)

def mcp_app(folder):
    from mcp.server import MCPServer
    from mcp.server.mcpserver.context import Context
    m=MCPServer('Confiabilidade L27',version='1.0');effects={};state={'contract':'v1'}
    async def reserve(intent:str,quantity:int,contract:str,ctx:Context)->dict:
        if contract!=state['contract']:raise ValueError('contract_changed')
        if quantity!=1:raise ValueError('quantity')
        if intent not in effects:
            effects[intent]=dict(intent=intent,quantity=quantity,contract=contract)
            save(folder/('effect_'+intent+'.json'),effects[intent])
        # Efeito antecede perda da resposta. Cancelar a tarefa Python não o desfaz.
        await ctx.report_progress(1,2,'effect_committed')
        try:await asyncio.sleep(30)
        except asyncio.CancelledError:
            save(folder/('cancel_'+intent+'.json'),{'cancelled':True});raise
        return effects[intent]
    m.tool(name='reserve')(reserve)
    @m.tool()
    def reconcile(intent:str)->dict:return {'receipt':effects.get(intent),'contract':state['contract']}
    @m.tool()
    def catalog()->dict:return dict(state)
    async def roll(request):
        state['contract']='v2';m.remove_tool('reserve')
        @m.tool(name='reserve')
        def reserve2(intent:str,units:int,contract:str)->dict:
            if contract!='v2' or units!=1:raise ValueError('v2_contract')
            return {'intent':intent,'units':units,'contract':contract,'dry_run':True}
        return JSONResponse(state)
    app=m.streamable_http_app(host='127.0.0.1');app.routes.append(Route('/roll',roll,methods=['POST']))
    return LabAuth(app,'mcp')

def a2a_app(folder,url):
    from a2a.server.agent_execution import AgentExecutor
    from a2a.server.tasks import TaskUpdater,InMemoryTaskStore
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
    from a2a.server.routes.agent_card_routes import create_agent_card_routes
    from a2a.types import AgentCard,AgentInterface,AgentCapabilities,AgentSkill,Task,TaskStatus,TaskState,Part
    gate=asyncio.Event();state={'contract':'v1'}
    class Executor(AgentExecutor):
        async def execute(self,context,event_queue):
            admission=dict(task_id=context.task_id,context_id=context.context_id,intent=context.get_user_input(),
                           contract=state['contract'],audience='review-consumer')
            save(folder/('admission_'+context.task_id+'.json'),admission)
            await event_queue.enqueue_event(Task(id=context.task_id,context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED)))
            updater=TaskUpdater(event_queue,context.task_id,context.context_id)
            await updater.update_status(TaskState.TASK_STATE_WORKING)
            await gate.wait()
            await updater.add_artifact([Part(text='Parecer da intenção '+admission['intent'])],
                artifact_id='artifact-'+context.task_id,name='decision',metadata=admission)
            await updater.update_status(TaskState.TASK_STATE_COMPLETED)
            save(folder/('completed_'+context.task_id+'.json'),admission)
        async def cancel(self,context,event_queue):
            await TaskUpdater(event_queue,context.task_id,context.context_id).update_status(TaskState.TASK_STATE_CANCELED)
    card=AgentCard(name='L27 local',description='Contrato e reconexão em bancada',version='1.0',
        supported_interfaces=[AgentInterface(url=url+'/a2a',protocol_binding='JSONRPC',protocol_version='1.0')],
        capabilities=AgentCapabilities(streaming=True,push_notifications=False),
        default_input_modes=['text/plain'],default_output_modes=['text/plain'],
        skills=[AgentSkill(id='review',name='Review',description='Revisão de fixture',tags=['lab'])])
    handler=DefaultRequestHandler(Executor(),InMemoryTaskStore(),card)
    async def release(request):
        state['contract']='v2';gate.set();return JSONResponse(state)
    routes=create_jsonrpc_routes(handler,'/a2a')+create_agent_card_routes(card)+[Route('/release',release,methods=['POST'])]
    return LabAuth(Starlette(routes=routes),'a2a')

def callback_app(folder):
    from .core import apply_callback
    expected=load(folder/'expected.json');state={'seen':[],'sequence':0,'status':'working'};count=0
    async def callback(request):
        nonlocal state,count
        event=await request.json();state,status=apply_callback(state,event,expected);count+=1
        record=dict(event=event,result=status,state=state);save(folder/f'callback_{count:02}.json',record)
        return JSONResponse(record)
    return LabAuth(Starlette(routes=[Route('/callback',callback,methods=['POST'])]),'callback')

def main():
    p=argparse.ArgumentParser();p.add_argument('--kind',choices=['mcp','a2a','callback']);p.add_argument('--folder',type=Path);a=p.parse_args()
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128);url=f'http://127.0.0.1:{sock.getsockname()[1]}'
    app=mcp_app(a.folder) if a.kind=='mcp' else a2a_app(a.folder,url) if a.kind=='a2a' else callback_app(a.folder)
    save(a.folder/'ready.json',dict(url=url,kind=a.kind))
    uvicorn.Server(uvicorn.Config(app,log_level='warning')).run(sockets=[sock])
if __name__=='__main__':main()
