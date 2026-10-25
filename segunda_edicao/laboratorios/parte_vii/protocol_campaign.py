"""MCP moderno e A2A 1.0 reais; callback correlacionado é perfil da aplicação."""
from pathlib import Path
import argparse,asyncio,json,time,sys,platform
from importlib.metadata import version
import httpx,httpx2
from google.protobuf.json_format import MessageToDict
from laboratorios.parte_i.common import load,save,sha,seal,child,wait_file
from .core import artifact_binding
ROOT=Path(__file__).resolve().parents[2]

async def available(url,token):
    async with httpx.AsyncClient() as h:
        for _ in range(60):
            try:await h.get(url,headers={'Authorization':'Bearer lab-'+token},timeout=1);return
            except httpx.TransportError:await asyncio.sleep(.1)
    raise TimeoutError('service ready')

async def mcp_run(folder,url):
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    headers={'Authorization':'Bearer lab-mcp'}
    async with httpx2.AsyncClient(headers=headers) as transport:
      async with Client(streamable_http_client(url+'/mcp',http_client=transport),mode='2026-07-28',cache=None) as client:
        before=await client.list_tools();save(folder/'sdk_tools_before.json',before.model_dump(mode='json',by_alias=True))
        catalog=await client.call_tool('catalog',{});save(folder/'sdk_catalog.json',catalog.model_dump(mode='json',by_alias=True))
    # Cliente HTTP independente do SDK cliente: fecha o SSE após progresso do commit.
    params={'name':'reserve','arguments':{'intent':'I27','quantity':1,'contract':'v1'},
            '_meta':{'io.modelcontextprotocol/protocolVersion':'2026-07-28',
                     'io.modelcontextprotocol/clientCapabilities':{},'progressToken':'P27'}}
    req={'jsonrpc':'2.0','id':27,'method':'tools/call','params':params};save(folder/'raw_request.json',req)
    async with httpx.AsyncClient(timeout=40) as h:
        hh=dict(headers,Accept='application/json, text/event-stream',
                **{'MCP-Protocol-Version':'2026-07-28','MCP-Method':'tools/call','MCP-Name':'reserve'})
        lines=[]
        async with h.stream('POST',url+'/mcp',headers=hh,json=req) as response:
            status=response.status_code;response_headers=dict(response.headers)
            async for line in response.aiter_lines():
                lines.append(line)
                if 'effect_committed' in line:break
        save(folder/'disconnect.json',dict(status=status,headers=response_headers,lines=lines,
            closed_before_final=not any('"result"' in line for line in lines)))
        wrong=await h.post(url+'/mcp',headers=dict(hh,Authorization='Bearer lab-a2a'),json=req)
        save(folder/'wrong_audience.json',dict(status=wrong.status_code,body=wrong.json()))
        await h.post(url+'/roll',headers=headers)
    async with httpx2.AsyncClient(headers=headers) as transport:
      async with Client(streamable_http_client(url+'/mcp',http_client=transport),mode='2026-07-28',cache=None) as client:
        after=await client.list_tools();save(folder/'sdk_tools_after.json',after.model_dump(mode='json',by_alias=True))
        old=await client.call_tool('reserve',dict(intent='I28',quantity=1,contract='v1'))
        save(folder/'old_schema_result.json',old.model_dump(mode='json',by_alias=True))
        receipt=await client.call_tool('reconcile',{'intent':'I27'})
        save(folder/'reconciled.json',receipt.model_dump(mode='json',by_alias=True))
    return dict(schema_changed=before.model_dump()!=after.model_dump(),old_schema_rejected=old.is_error,
                wrong_audience_rejected=wrong.status_code==401,closed_after_commit=any('effect_committed' in l for l in lines),
                reconciled_effect=(folder/'effect_I27.json').exists(),
                no_session_header='mcp-session-id' not in response_headers)

async def a2a_run(folder,url):
    from a2a.client import ClientFactory,ClientConfig
    from a2a.types import SendMessageRequest,Message,Part,Role,GetTaskRequest,TaskState
    headers={'Authorization':'Bearer lab-a2a'}
    async with httpx.AsyncClient(headers=headers,timeout=15) as h:
        client=await ClientFactory(ClientConfig(streaming=True,httpx_client=h)).create_from_url(url)
        request=SendMessageRequest(message=Message(message_id='M27',role=Role.ROLE_USER,parts=[Part(text='intent-A27')]))
        save(folder/'send_request.json',MessageToDict(request))
        stream=client.send_message(request);events=[];task_id=None;context_id=None
        try:
            async for event in stream:
                data=MessageToDict(event);events.append(data)
                if event.HasField('task'):
                    task_id=event.task.id;context_id=event.task.context_id
                if event.HasField('status_update'):
                    task_id=event.status_update.task_id;context_id=event.status_update.context_id
                    if event.status_update.status.state==TaskState.TASK_STATE_WORKING:break
        finally:await stream.aclose()
        save(folder/'initial_stream.json',events)
        if not task_id:raise ValueError('task identity absent')
        await h.post(url+'/release')
        states=[]
        for _ in range(60):
            task=await client.get_task(GetTaskRequest(id=task_id));states.append(MessageToDict(task))
            if task.status.state==TaskState.TASK_STATE_COMPLETED:break
            await asyncio.sleep(.1)
        save(folder/'polls.json',states);final=MessageToDict(task);save(folder/'final_task.json',final)
        # Mesmo método por cliente HTTP, sem serializer/transport do SDK cliente.
        raw={'jsonrpc':'2.0','id':2,'method':'GetTask','params':{'id':task_id}}
        response=await h.post(url+'/a2a',json=raw,headers={'A2A-Version':'1.0'})
        save(folder/'independent_get.json',dict(request=raw,status=response.status_code,body=response.json()))
        wrong=await h.post(url+'/a2a',json=raw,headers={'Authorization':'Bearer lab-mcp','A2A-Version':'1.0'})
        save(folder/'wrong_audience.json',dict(status=wrong.status_code,body=wrong.json()))
        expected=dict(task_id=task_id,context_id=context_id,intent='intent-A27',contract='v1',audience='review-consumer')
        artifact=final['artifacts'][0]
        result=dict(completed_after_disconnect=task.status.state==TaskState.TASK_STATE_COMPLETED,
                    binding_ok=artifact_binding(expected,artifact),new_contract_rejected=not artifact_binding(dict(expected,contract='v2'),artifact),
                    wrong_audience_rejected=wrong.status_code==401,raw_client_agrees=response.json().get('result',{}).get('id')==task_id)
        return result,expected

async def callback_run(folder,url,expected):
    base=dict(metadata=expected,event_id='event1',sequence=1,status='completed')
    variants=[base,base,dict(base,event_id='foreign',metadata=dict(expected,task_id='another-task')),
              dict(base,event_id='older',sequence=0,status='working'),
              dict(base,event_id='regression',sequence=2,status='working'),
              dict(base,event_id='schema',sequence=2,metadata=dict(expected,contract='v2'))]
    statuses=[]
    async with httpx.AsyncClient(headers={'Authorization':'Bearer lab-callback'}) as h:
        for v in variants:
            r=await h.post(url+'/callback',json=v);r.raise_for_status();statuses.append(r.json()['result'])
        wrong=await h.post(url+'/callback',json=base,headers={'Authorization':'Bearer lab-a2a'})
    return dict(statuses=statuses,wrong_audience_status=wrong.status_code,
                profile='Application HTTP callback; native A2A pushNotifications is false and not tested')

async def run(out):
    out.mkdir(parents=True,exist_ok=False)
    save(out/'plan.json',dict(date='2026-10-24',mcp_protocol='2026-07-28',a2a_protocol='1.0',
        packages={n:version(n) for n in ['mcp','a2a-sdk','uvicorn','starlette','httpx','httpx2']},
        scenarios=['MCP schema before/after','MCP SSE lost after effect','MCP reconciliation','wrong audience',
                   'A2A disconnect while working','A2A GetTask after completion','A2A frozen contract','HTTP callback duplicate/binding/order'],
        scope='Loopback; static fixture credentials; no OAuth, TLS, native push, legacy session or production interoperability claim'))
    save(out/'inputs.json',{p.name:sha(p) for p in [Path(__file__),Path(__file__).with_name('protocol_server.py'),Path(__file__).with_name('core.py')]})
    results={};expected=None
    for kind in ['mcp','a2a','callback']:
        folder=out/kind;folder.mkdir()
        if kind=='callback':save(folder/'expected.json',expected)
        with child('laboratorios.parte_vii.protocol_server',['--kind',kind,'--folder',folder],folder/'process') as p:
            wait_file(folder/'ready.json',p);url=load(folder/'ready.json')['url'];await available(url,kind)
            if kind=='mcp':results[kind]=await mcp_run(folder,url)
            elif kind=='a2a':results[kind],expected=await a2a_run(folder,url)
            else:results[kind]=await callback_run(folder,url,expected)
        results[kind]['process_ended']=p.poll() is not None
    save(out/'summary.json',results)
    passed=all(v is True for k in ['mcp','a2a'] for v in results[k].values())
    seal(out,'parte_vii_protocols',complete=passed)
    print(json.dumps(results,ensure_ascii=False))
    if not passed:raise AssertionError('Protocolo: cenário não atingiu as condições predefinidas')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();asyncio.run(run(a.out.resolve()))

