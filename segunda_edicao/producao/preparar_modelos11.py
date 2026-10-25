"""Materializa binários públicos fixados no lock, sem executar código remoto."""
from pathlib import Path
import argparse, shutil, sys, zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from laboratorios.l11.core import load,sha

def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime',type=Path,default=ROOT/'.modelos/l11');a=p.parse_args()
    a.runtime.mkdir(parents=True,exist_ok=True)
    lock=load(ROOT/'materiais/l11/modelos.lock.json')
    def download(item):
        dest=a.runtime/item['filename']
        if not dest.exists():
            partial=dest.with_suffix(dest.suffix+'.partial')
            with urlopen(item['url'],timeout=120) as src,partial.open('wb') as dst:
                shutil.copyfileobj(src,dst,1024*1024)
            if sha(partial)!=item['sha256']:raise ValueError('hash do download')
            partial.rename(dest)
        if sha(dest)!=item['sha256']:raise ValueError(str(dest))
        print('Verificado:',dest.name,flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(download,lock['downloads']))
    dest=(a.runtime/'runtime_b11669').resolve();dest.mkdir(exist_ok=True)
    archive=next(x for x in lock['downloads'] if x['id']=='runtime')
    with zipfile.ZipFile(a.runtime/archive['filename']) as z:
        for member in z.infolist():
            target=(dest/member.filename).resolve()
            if not target.is_relative_to(dest):raise ValueError('ZIP fora do destino')
            if member.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            data=z.read(member)
            if target.exists() and target.read_bytes()!=data:raise ValueError('binário existente divergente')
            target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():target.write_bytes(data)
    if sha(dest/'llama-server.exe')!=lock['server_sha256']:raise ValueError('servidor')

if __name__=='__main__':main()
