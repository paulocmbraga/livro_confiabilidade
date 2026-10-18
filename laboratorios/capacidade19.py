"""Filas asyncio, relógio monotônico e dependência local com atrasos reais."""
import asyncio
from collections import Counter
import math
import platform
import time
from .dados_ii import write, lines, table


def profile():
    normal=[dict(task=f'N{i}', arrival=i*.05, phase='normal', kind='simples') for i in range(3)]
    burst=[dict(task=f'B{i:02}', arrival=.2+i*.002, phase='sobrecarga',
                kind='dificil' if i%3==0 else 'simples') for i in range(24)]
    recovery=[dict(task=f'R{i}', arrival=.9+i*.06, phase='recuperacao',kind='simples') for i in range(6)]
    return normal+burst+recovery


def percentile(values, q=.95):
    if not values:
        return None
    if not 0 < q <= 1:
        raise ValueError('percentil fora do intervalo')
    return sorted(values)[math.ceil(q*len(values))-1]


async def trial(policy, repetition=0):
    if policy not in ('baseline', 'limitado'):
        raise ValueError(policy)
    guarded=policy=='limitado'; clock=time.perf_counter; start=clock()
    queue=asyncio.Queue(maxsize=4 if guarded else 0)
    results=[]; calls=[]; active=0; peak_active=0; peak_queue=0
    async def dependency(row, attempt):
        nonlocal active,peak_active
        call=dict(task=row['task'],attempt=attempt,started=clock()-start,status='iniciada')
        calls.append(call)
        if active>=2:
            call.update(status='limite_dependencia',finished=clock()-start)
            return False
        active+=1;peak_active=max(peak_active,active)
        try:
            await asyncio.sleep(.1 if row['phase']=='sobrecarga' else .012)
            call['status']='ok';return True
        except asyncio.CancelledError:
            call['status']='cancelada';raise
        finally:
            active-=1;call['finished']=clock()-start
    async def worker():
        while True:
            row=await queue.get()
            if row is None:
                queue.task_done();return
            row['started']=clock()-start
            row['queue_ms']=(row['started']-row['admitted'])*1000
            attempts=0; status='falha';fallback=False
            try:
                if guarded and clock()-start>=row['deadline']:
                    status='expirado'
                elif (guarded and row['phase']=='sobrecarga'
                      and row['kind']=='simples' and queue.qsize()>=2
                      and clock()-start+.003<row['deadline']):
                    await asyncio.sleep(.003);status='fallback';fallback=True
                else:
                    for attempt in range(1,3 if guarded else 5):
                        remaining=row['deadline']-(clock()-start)
                        if guarded and remaining<=0:
                            status='expirado';break
                        attempts+=1
                        try:
                            operation=dependency(row,attempt)
                            ok=await asyncio.wait_for(operation,remaining) if guarded else await operation
                        except TimeoutError:
                            status='expirado';break
                        if ok:
                            status='sucesso';break
                        await asyncio.sleep(.004*attempt if guarded else .001)
                    # Fallback local só atende tarefas simples e respeita o prazo.
                    if guarded and status=='falha' and row['kind']=='simples':
                        if clock()-start+.003<row['deadline']:
                            await asyncio.sleep(.003);status='fallback';fallback=True
                finish=clock()-start
                if finish>row['deadline']:
                    status='expirado'
                row.update(finished=finish,attempts=attempts,status=status,fallback=fallback,
                           useful=status in ('sucesso','fallback'))
                results.append(row)
            finally:
                queue.task_done()
    workers=[asyncio.create_task(worker()) for _ in range(2 if guarded else 8)]
    for case in profile():
        await asyncio.sleep(max(0,start+case['arrival']-clock()))
        now=clock()-start
        row=dict(case,policy=policy,repetition=repetition,admitted=now,
                 deadline=case['arrival']+(.14 if case['phase']=='sobrecarga' else .2))
        try:
            queue.put_nowait(row);peak_queue=max(peak_queue,queue.qsize())
        except asyncio.QueueFull:
            row.update(started=None,queue_ms=None,finished=now,attempts=0,
                       status='rejeitado',fallback=False,useful=False)
            results.append(row)
    await queue.join()
    drained=clock()-start
    for _ in workers:
        await queue.put(None)
    await asyncio.gather(*workers)
    for row in results:
        row['latency_ms']=(row['finished']-row['arrival'])*1000
        row['generator_lag_ms']=(row['admitted']-row['arrival'])*1000
    summary=summarize(results,calls)
    summary.update(peak_active=peak_active,peak_queue=peak_queue,drained_at=drained,
                   remaining=queue.qsize()+active,policy=policy,repetition=repetition)
    return sorted(results,key=lambda r:r['task']),calls,summary


def summarize(rows,calls):
    useful=[r for r in rows if r['useful']]
    recovery=[r for r in rows if r['phase']=='recuperacao']
    end=max(r['finished'] for r in rows)
    return dict(offered=len(rows),useful=len(useful),statuses=dict(Counter(r['status'] for r in rows)),
                attempts=len(calls),amplification=len(calls)/len(rows),
                p95_useful_ms=percentile([r['latency_ms'] for r in useful]),
                p95_terminal_ms=percentile([r['latency_ms'] for r in rows]),
                useful_throughput=len(useful)/end,
                cancelled_calls=sum(c['status']=='cancelada' for c in calls),
                late_calls=sum(c['finished']>next(r['deadline'] for r in rows if r['task']==c['task'])
                               for c in calls),
                recovery_success=sum(r['useful'] for r in recovery),recovery_offered=len(recovery))


def capture(folder):
    folder.mkdir(); results=[];allrows=[]
    for repetition in range(3):
        order=('baseline','limitado') if repetition%2==0 else ('limitado','baseline')
        for policy in order:
            rows,calls,summary=asyncio.run(trial(policy,repetition))
            allrows.extend(rows);results.append(summary)
            lines(folder/f'{policy}_{repetition}_calls.jsonl',calls)
            lines(folder/f'{policy}_{repetition}_tasks.jsonl',rows)
    table(folder/'measurements.csv',allrows)
    write(folder/'load_profile.json',dict(cases=profile(),repetitions=3,
          clock='time.perf_counter; segundos reais',host=platform.platform(),
          dependency='corrotina local; limite 2; atraso real; sem HTTP ou LLM',
          quality='resposta determinística preparada; fallback apenas simples',
          observation='drenagem e seis sondas; não é estabilidade de longo prazo'))
    write(folder/'trial_summaries.json',results)
    (folder/'capacity_report.md').write_text(
        '# L19: ensaio local\n\n'+
        '\n'.join(f"- {r['policy']} / {r['repetition']}: {r['useful']}/{r['offered']} úteis; "
                  f"{r['attempts']} chamadas; pico da fila {r['peak_queue']}; "
                  f"recuperação {r['recovery_success']}/6." for r in results)+
        '\n\nTempos variam por host. Não extrapolar vazão para APIs ou clusters.\n',encoding='utf8')
    return results
