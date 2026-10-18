"""Índice local de evidências: integridade não equivale a autenticidade."""
from pathlib import Path
import hashlib
import json
from .dados_ii import sha, write


def digest(value):
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf8')).hexdigest()


def locate(folder,relative):
    root=Path(folder).resolve();path=(root/relative).resolve()
    if not path.is_relative_to(root) or path==root:
        raise ValueError('Caminho fora do pacote')
    return path


def index(folder,claims):
    entries=[]
    for claim,paths in claims.items():
        if not paths:raise ValueError('Alegação sem evidência')
        entries.append(dict(claim=claim,files=[dict(path=p,sha256=sha(locate(folder,p))) for p in paths]))
    result=dict(schema='livro.evidence/1',claims=entries,
        limit='Hashes ligam arquivos a alegações; não validam automaticamente a interpretação ou a origem.')
    write(Path(folder)/'evidence_index.json',result)
    return result


def verify_index(folder,record,required):
    claims=[r['claim'] for r in record['claims']]
    if len(claims)!=len(set(claims)) or set(claims)!=set(required):
        raise ValueError('Alegações ausentes, duplicadas ou inesperadas')
    for entry in record['claims']:
        if not entry['files']:raise ValueError('Evidência vazia')
        for ref in entry['files']:
            if sha(locate(folder,ref['path']))!=ref['sha256']:
                raise ValueError('Evidência alterada: '+ref['path'])
    return len(claims)
