"""Confere os arquivos distribuídos, sem modificar dados ou executar laboratórios."""
from pathlib import Path
import hashlib,json

ROOT=Path(__file__).resolve().parent

def main():
    manifest=json.loads((ROOT/'MANIFESTO_PUBLICO.json').read_text(encoding='utf-8'))
    for row in manifest['files']:
        path=(ROOT/row['path']).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError('Arquivo ausente ou fora do pacote: '+row['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Arquivo divergente: '+row['path'])
    print(json.dumps({'files_verified':len(manifest['files']),'edition':2,
        'scope':'Integridade dos arquivos distribuídos; arquivos novos do leitor são ignorados.'},ensure_ascii=False))

if __name__=='__main__':main()
