"""Planejador, especialista A2A e ferramenta MCP compartilhando uma intenção."""
from contextlib import ExitStack
from pathlib import Path
import asyncio,json,time
import httpx,httpx2
from google.protobuf.json_format import MessageToDict
from laboratorios.parte_i.common import child,wait_file
from laboratorios.parte_vii.protocol_campaign import available
from .core import save,load,proposal
from .inference import infer,PLAN

async def run43(out,llm,model):
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from a2a.client import ClientFactory,ClientConfig
    from a2a.types import SendMessageRequest,Message,Part,Role,GetTaskRequest,TaskState
    out.mkdir();started=time.perf_counter();rows=[];h_mcp={'Authorization':'Bearer lab-mcp'}
    with ExitStack() as stack:
        def launch(kind,label):
            folder=out/label
            args=['--kind',kind,'--folder',folder,'--db',out/'ledger.sqlite','--llm',llm,'--model',model]
            proc=stack.enter_context(child('laboratorios.parte_xi.protocol',args,out/(label+'_process')))
            wait_file(folder/'ready.json',proc);return proc,load(folder/'ready.json')['url']
        mp,mu=launch('mcp','destination');ap,au=launch('a2a','specialist')
        await available(mu,'mcp');await available(au,'a2a')
        async with httpx.AsyncClient(headers=h_mcp,timeout=60) as admin,httpx.AsyncClient(headers={'Authorization':'Bearer lab-a2a'},timeout=90) as h:
            a2a=await ClientFactory(ClientConfig(streaming=True,httpx_client=h)).create_from_url(au)
            async def administrative(action,data):
                response=await admin.post(mu+'/admin/'+action,json=data);response.raise_for_status();return response.json()
            async def review(task,pause=False):
                req=SendMessageRequest(message=Message(message_id='M-'+task['intent'],role=Role.ROLE_USER,parts=[Part(text=json.dumps(dict(task,pause=pause)))]))
                stream=a2a.send_message(req);events=[];taskid=None
                try:
                    async for event in stream:
                        events.append(MessageToDict(event))
                        if event.HasField('task'):taskid=event.task.id
                        if event.HasField('status_update'):
                            taskid=event.status_update.task_id
                            if event.status_update.status.state==TaskState.TASK_STATE_WORKING:break
                finally:await stream.aclose()
                if not taskid:raise ValueError('missing delegated identity')
                if pause:
                    blocked=await administrative('migrate',{'to':'v2'})
                    save(out/'migration_while_delegated.json',blocked)
                    await h.post(au+'/release')
                for _ in range(900):
                    final=await a2a.get_task(GetTaskRequest(id=taskid))
                    if final.status.state==TaskState.TASK_STATE_COMPLETED:break
                    await asyncio.sleep(.1)
                else:raise TimeoutError('specialist')
                raw=MessageToDict(final);save(out/('delegated_'+task['intent']+'.json'),dict(events=events,final=raw))
                artifact=raw['artifacts'][0];binding=artifact['metadata']
                if binding['intent']!=task['intent'] or binding['contract']!=task['contract'] or binding['task_id']!=taskid:raise ValueError('artifact binding')
                return artifact['parts'][0]['text']
            async def reserve(task,lose=False):
                async with httpx2.AsyncClient(headers=h_mcp) as transport:
                    async with Client(streamable_http_client(mu+'/mcp',http_client=transport),mode='2026-07-28',cache=None) as client:
                        result=await client.call_tool('reserve',dict(intent=task['intent'],quantity=task['quantity'],contract=task['contract'],lose_reply=lose))
                        return result.model_dump(mode='json',by_alias=True)
            tasks=[dict(quantity=q,authorized=a) for q,a in [(1,True),(2,True),(1,False),(1,True),(1,True),(2,False)]]
            for mode in ['workflow','agent','team']:
                for i,base in enumerate(tasks):
                    task=dict(base,intent=f'{mode}-{i}',contract='v1');text=None;specialist=None
                    if mode=='workflow':decision=dict(accepted=base['quantity']==1 and base['authorized'],reason='deterministic_policy')
                    else:
                        result=infer(llm,model,'Reserve somente authorized=true e quantity=1. Caso contrario hold. Pedido: '+json.dumps(task),PLAN,out/f'planner_{mode}_{i}.json')
                        text=result['text'];decision=proposal(text,task)
                        if mode=='team':
                            specialist=await review(task);decision['accepted']=decision['accepted'] and proposal(specialist,task)['accepted']
                    receipt=None;tool=None
                    if decision['accepted']:
                        prepared=await administrative('prepare',task)
                        if not prepared['ok']:raise ValueError('prepare')
                        tool=await reserve(task)
                        receipt=await administrative('reconcile',task)
                        if receipt['receipt']:await administrative('ack',task)
                    rows.append(dict(mode=mode,task=task,planner=text,specialist=specialist,decision=decision,receipt=receipt,tool=tool))
            # Caso de recuperação predefinido, não condicionado ao acerto semântico dos modelos.
            task=dict(intent='fault-43',quantity=1,authorized=True,contract='v1')
            await administrative('prepare',task);specialist=await review(task,pause=True)
            save(out/'fault_specialist.json',dict(text=specialist,decision=proposal(specialist,task),authority='fixture explicit bounded intent; independent of LLM approval'))
            params={'name':'reserve','arguments':dict(intent=task['intent'],quantity=1,contract='v1',lose_reply=True),'_meta':{'io.modelcontextprotocol/protocolVersion':'2026-07-28','io.modelcontextprotocol/clientCapabilities':{},'progressToken':'P43'}}
            req={'jsonrpc':'2.0','id':43,'method':'tools/call','params':params}
            headers=dict(h_mcp,Accept='application/json, text/event-stream',**{'MCP-Protocol-Version':'2026-07-28','MCP-Method':'tools/call','MCP-Name':'reserve'})
            lines=[];t=time.perf_counter()
            async with admin.stream('POST',mu+'/mcp',headers=headers,json=req) as response:
                status=response.status_code
                async for line in response.aiter_lines():
                    lines.append(line)
                    if 'effect_committed' in line:break
            save(out/'lost_confirmation.json',dict(status=status,request=req,lines=lines,seconds=time.perf_counter()-t))
            before=await administrative('state',{});save(out/'before_restart.json',before)
            mp.terminate();mp.wait(5);mp,mu=launch('mcp','destination_restart');await available(mu,'mcp')
            after=await administrative('state',{});save(out/'after_restart.json',after)
            blocked=await administrative('migrate',{'to':'v2'});receipt=await administrative('reconcile',task)
            ack=await administrative('ack',task);migrated=await administrative('migrate',{'to':'v2'})
            old=await reserve(task);final=await administrative('state',{})
            save(out/'recovery.json',dict(blocked=blocked,receipt=receipt,ack=ack,migrated=migrated,old_contract=old,final=final,seconds=time.perf_counter()-t))
    save(out/'rows.json',rows);save(out/'summary.json',dict(seconds=time.perf_counter()-started,n=len(rows),
        useful={mode:sum(r['mode']==mode and bool(r['receipt'] and r['receipt']['receipt']) for r in rows) for mode in ['workflow','agent','team']},
        review_required={mode:sum(r['mode']==mode and not r['decision']['accepted'] for r in rows) for mode in ['workflow','agent','team']},
        human_executed=0,credential_profile='public fixture bearer tokens; no OAuth or TLS',a2a_task_store='memory, not restarted'))
