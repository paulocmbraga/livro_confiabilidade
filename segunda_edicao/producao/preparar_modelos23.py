"""Baixa somente pesos/configuração públicos, sem código remoto ou API paga."""
from pathlib import Path
import argparse,json,shutil,sys,zipfile
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from laboratorios.l23.core import sha

def materialize_runtime(lock,directory):
    directory.mkdir(parents=True,exist_ok=True)
    for a in lock['artifacts']:
        if a['id'] not in ('q4_k_m','llama_cpp_cpu'):continue
        target=directory/a['filename']
        if not target.exists():
            partial=target.with_suffix(target.suffix+'.partial')
            with urlopen(a['url'],timeout=90) as src,partial.open('wb') as dst:
                shutil.copyfileobj(src,dst,length=1024*1024)
            if sha(partial)!=a['sha256']:raise ValueError('Download divergente')
            partial.rename(target)
        if sha(target)!=a['sha256']:raise ValueError('Artefato divergente: '+str(target))
        if a['id']=='llama_cpp_cpu':
            dest=directory/'runtime_b11669';dest.mkdir(exist_ok=True)
            with zipfile.ZipFile(target) as archive:
                for entry in archive.infolist():
                    resolved=(dest/entry.filename).resolve()
                    if not resolved.is_relative_to(dest.resolve()):raise ValueError('Caminho ZIP fora do destino')
                    if entry.is_dir():resolved.mkdir(parents=True,exist_ok=True);continue
                    data=archive.read(entry)
                    if resolved.exists():
                        if resolved.read_bytes()!=data:raise ValueError('Runtime existente divergente')
                    else:
                        resolved.parent.mkdir(parents=True,exist_ok=True);resolved.write_bytes(data)
    expected=next(a['sha256'] for a in lock['artifacts'] if a['id']=='llama_server_exe')
    if sha(directory/'runtime_b11669/llama-server.exe')!=expected:raise ValueError('Executável divergente')
    print('Runtime validado:',directory,flush=True)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime',type=Path,help='Materializar também o gerador e llama.cpp nesse diretório')
    args=parser.parse_args()
    from huggingface_hub import snapshot_download
    cache=ROOT/'.modelos';cache.mkdir(exist_ok=True)
    lock=ROOT/'materiais/l23/modelos.lock.json'
    if lock.exists():
        frozen=json.loads(lock.read_text(encoding='utf-8'))
        for a in frozen['artifacts']:
            if 'files' not in a:continue
            directory=Path(snapshot_download(a['repository'],revision=a['revision'],local_dir=cache/a['id'],
                token=False,allow_patterns=list(a['files']),max_workers=3))
            for rel,expected in a['files'].items():
                if sha(directory/rel)!=expected:raise ValueError('Modelo divergente: '+rel)
            print(a['id'],a['revision'],'validado',flush=True)
        if args.runtime:materialize_runtime(frozen,args.runtime.resolve())
        return
    raise FileNotFoundError('Lock obrigatório ausente: '+str(lock))

if __name__=='__main__':main()
