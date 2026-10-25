"""Inferência local identificada: bi-encoder, cross-encoder e llama.cpp."""
from pathlib import Path
from contextlib import contextmanager
import json,platform,socket,subprocess,threading,time
from urllib.request import Request,urlopen
from importlib.metadata import version
from .core import sha,bm25,rrf,eligible

ROOT=Path(__file__).resolve().parents[2]
def write(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def http(url,payload=None,timeout=90):
    req=Request(url,data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None,
                headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=timeout) as response:return json.load(response)

def verify_models(cache,lock):
    for a in lock['artifacts']:
        if 'files' in a:
            for rel,expected in a['files'].items():
                if sha(cache/a['id']/rel)!=expected:raise ValueError('Modelo divergente: '+rel)

def retrieve(corpus,queries,cache,out,lock):
    import torch,numpy as np,psutil
    from sentence_transformers import SentenceTransformer,CrossEncoder
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    verify_models(cache,lock);start=time.monotonic()
    encoder=SentenceTransformer(str(cache/'embedding'),device='cpu',local_files_only=True,trust_remote_code=False)
    texts=[d['text'] for d in corpus]
    vectors=encoder.encode(texts,normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
    qvectors=encoder.encode([q['question'] for q in queries],normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
    lengths=[len(encoder.tokenizer.encode(s)) for s in texts]
    qlengths=[len(encoder.tokenizer.encode(q['question'])) for q in queries]
    np.save(out/'document_vectors.npy',vectors);np.save(out/'query_vectors.npy',qvectors)
    encoder_meta={'max_seq_length':encoder.max_seq_length,'document_token_lengths':lengths,'query_token_lengths':qlengths,
                  'truncated_documents':sum(n>encoder.max_seq_length for n in lengths),'shape':list(vectors.shape)}
    del encoder
    cross=CrossEncoder(str(cache/'reranker'),device='cpu',max_length=256,local_files_only=True,trust_remote_code=False)
    index={d['id']:i for i,d in enumerate(corpus)};byid={d['id']:d for d in corpus};result=[]
    max_pair_len=0
    for qi,q in enumerate(queries):
        began=time.monotonic();allowed=[d for d in corpus if eligible(d,q)]
        lexical=bm25(q['question'],allowed)
        dense=sorted([{'id':d['id'],'score':float(vectors[index[d['id']]]@qvectors[qi])} for d in allowed],
                     key=lambda x:(-x['score'],x['id']))
        fused=rrf([lexical[:8],dense[:8]])[:8]
        pairs=[(q['question'],byid[r['id']]['text']) for r in fused]
        pair_lens=[len(cross.tokenizer.encode(a,b)) for a,b in pairs]
        max_pair_len=max(max_pair_len,*pair_lens)
        scores=cross.predict(pairs,batch_size=8,show_progress_bar=False,activation_fn=torch.nn.Identity(),convert_to_numpy=True)
        reranked=sorted([{'id':r['id'],'score':float(s)} for r,s in zip(fused,scores)],key=lambda x:(-x['score'],x['id']))
        result.append({'query_id':q['id'],'eligible_ids':[d['id'] for d in allowed],
                       'bm25':lexical,'dense':dense,'rrf_candidates':fused,'hybrid_rerank':reranked,
                       'pair_token_lengths':pair_lens,'elapsed_seconds':round(time.monotonic()-began,5)})
    write(out/'retrieval.json',result)
    memory=psutil.Process().memory_info()
    write(out/'retrieval_resources.json',{'elapsed_seconds':round(time.monotonic()-start,3),'rss_end_bytes':memory.rss,
          'peak_working_set_bytes':getattr(memory,'peak_wset',None),'encoder':encoder_meta,
          'reranker':{'max_length':256,'max_pair_tokens':max_pair_len,'activation':'Identity; score is not probability'},
          'device':'cpu','threads':4,'real_inference':True})
    return result

@contextmanager
def server(runtime,out,lock):
    import psutil
    model=next(a for a in lock['artifacts'] if a['id']=='q4_k_m')
    binary=next(a for a in lock['artifacts'] if a['id']=='llama_server_exe')
    exe=runtime/'runtime_b11669/llama-server.exe';weights=runtime/model['filename']
    if sha(exe)!=binary['sha256'] or sha(weights)!=model['sha256']:raise ValueError('Gerador/runtime divergente')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    args=[str(exe),'-m',str(weights),'--host','127.0.0.1','--port',str(port),'-t','4','-tb','4',
          '-c','2048','-np','1','-ngl','0','--no-webui','--alias','l23-qwen-q4']
    started=time.monotonic();samples=[];stop=threading.Event()
    with (out/'server.log').open('wb') as log:
        proc=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def monitor():
            p=psutil.Process(proc.pid)
            while not stop.wait(1):
                try:samples.append({'seconds':round(time.monotonic()-started,3),'rss':p.memory_info().rss,
                                    'cpu_seconds':sum(p.cpu_times()[:2]),'ram_available':psutil.virtual_memory().available})
                except psutil.Error:return
        thread=threading.Thread(target=monitor,daemon=True);thread.start()
        try:
            url=f'http://127.0.0.1:{port}'
            while True:
                if proc.poll() is not None or time.monotonic()-started>90:raise RuntimeError('llama.cpp não iniciou')
                try:
                    if http(url+'/health',timeout=1).get('status')=='ok':break
                except (OSError,ValueError):time.sleep(.25)
            yield url
        finally:
            stop.set();thread.join(2)
            if proc.poll() is None:proc.terminate()
            try:proc.wait(5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(5)
            write(out/'generation_resources.json',{'elapsed_seconds':round(time.monotonic()-started,3),
                  'rss_peak_bytes':max((s['rss'] for s in samples),default=0),'samples':samples,
                  'process_ended':proc.poll() is not None,'arguments':args[3:],'model_sha256':sha(weights),
                  'runtime_sha256':sha(exe),'device':'cpu','threads':4,'python':platform.python_version(),
                  'packages':{n:version(n) for n in ['numpy','torch','transformers','sentence-transformers','psutil']}})
