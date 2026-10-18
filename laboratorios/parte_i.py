"""Captura L00-L03 e conferência sem novas chamadas; L04 mantém a captura do piloto."""
import argparse
from collections import Counter
import csv
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import time
from . import contratos,catalogo,campanhas

PROJECT=Path(__file__).resolve().parents[1]
SOURCES=['contratos.py','catalogo.py','worker03.py','campanhas.py','parte_i.py']


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,obj):Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8')
def lines(path,rows):Path(path).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf8')


def capture(folder):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=False);start=time.perf_counter()
    l00=folder/'L00';l00.mkdir()
    examples=[contratos.casos()[0],contratos.casos()[8]]
    lines(l00/'outcomes.jsonl',[dict(contratos.avaliar(r),attempt_id=r['task_id']+':1',trilha='D') for r in examples])
    write(l00/'ambiente.json',dict(python=platform.python_version(),sqlite=sqlite3.sqlite_version,
                                 platform=platform.platform(),dependencias_externas=[],trilha='D',inferencias=0,
                                 ambiente_isolado=sys.prefix!=sys.base_prefix,
                                 relogio_referencia='2026-09-30',credenciais_necessarias=False))
    l01=folder/'L01';l01.mkdir();rows=contratos.matriz()
    write(l01/'contratos.json',dict(version='L01-1.0',invariantes=contratos.REQUIREMENTS,
          meta=dict(latencia_ms=1000,unidade='caso preparado; não p95 de produção'),
          populacao='16 casos didáticos, sem representatividade externa'))
    lines(l01/'casos_L01.jsonl',contratos.casos())
    with (l01/'matriz_decisoes.csv').open('w',encoding='utf8',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    coverage={name:[r['task_id'] for r in contratos.casos() if name in r['violacoes']]
              for name in contratos.REQUIREMENTS}
    assert all(coverage.values())
    write(l01/'summary.json',dict(casos=len(rows),estados=dict(Counter(r['estado'] for r in rows)),
         adequados=sum(r['adequado'] for r in rows),acoes_concluidas=sum(r['acao_concluida'] for r in rows),
         falsos_sucessos=sum(r['falso_sucesso'] for r in rows),cobertura_contraexemplos=coverage))
    l02=folder/'L02';l02.mkdir();source=catalogo.tarefas()
    bad=catalogo.aleatoria_por_linha(source);included,excluded=catalogo.qualidade(source)
    good=catalogo.por_componentes(included);catalogo.exigir_particoes(good)
    lines(l02/'tarefas_origem.jsonl',source);lines(l02/'tarefas_admitidas.jsonl',good)
    temporal_source=catalogo.tarefas_temporais()
    temporal_included,temporal_excluded=catalogo.qualidade(temporal_source)
    temporal=catalogo.por_periodo(temporal_included)
    lines(l02/'tarefas_temporais.jsonl',temporal)
    write(l02/'temporal_manifest.json',dict(cenario='Separado da divisão por tamanho',
        corte_desenvolvimento='2026-07-31',corte_calibracao='2026-08-31',
        particoes=dict(Counter(r['particao'] for r in temporal)),excluidas=temporal_excluded,
        estratos=catalogo.estratos(temporal),origem_ausente_proporcao=1/24,
        limite='Meses e segmentos foram construídos juntos; não há generalização demonstrada.'))
    write(l02/'split_manifest.json',dict(version='L02-1.0',seed_baseline=2026,admitidas=len(good),
        excluidas=excluded,relacoes=['familia','entidade'],particoes=dict(Counter(r['particao'] for r in good)),
        estratos=catalogo.estratos(good),baseline_vazamentos=catalogo.auditar(bad),
        corrected_vazamentos=catalogo.auditar(good),exposicao='Todos os dados são públicos e didáticos'))
    with (l02/'auditoria_particoes.csv').open('w',encoding='utf8',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=['tipo','grupo','particoes']);w.writeheader();w.writerows(catalogo.auditar(bad))
    (l02/'dataset_card.md').write_text('# Catálogo didático Horizonte\n\n'
        'Origem: geração autoral sintética, versão L02-1.0. 24 linhas, 12 famílias, duas paráfrases por família. '
        'F03 e F04 compartilham entidade. A fonte de F12 é posterior à tarefa; F11-2 não tem origem registrada. '
        'Essas três linhas são excluídas com justificativa; restam 21.\n\n'
        'Finalidade: demonstrar auditoria de partições, sem representar tráfego real. '
        'As partições são públicas; teste é um papel no protocolo, não um conjunto secreto. '
        'Relógio: 2026-09-30. Autor: Paulo Cesar Braga. Sem dados de pessoas reais. '
        'Um cenário temporal separado usa julho, agosto e setembro, com cortes explícitos e os mesmos grupos. '
        'Acesso a teste deve ser registrado pelo leitor em uma campanha posterior.\n',encoding='utf8')
    write(l02/'access_log.json',[dict(event='publicacao_didatica',particao='teste',
                                    reason='Material integralmente visível ao leitor; não é holdout secreto')])
    l03=folder/'L03';l03.mkdir();interrupted=l03/'interrompida'
    campanhas.initialize(interrupted,limit=12)
    process=subprocess.run([sys.executable,'-m','laboratorios.campanhas','--saida',str(interrupted),
                            '--crash-after','T02'],cwd=PROJECT,capture_output=True,text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,timeout=25)
    if process.returncode!=83:raise RuntimeError('Falha injetada não observada: '+process.stderr)
    with campanhas.db_at(interrupted/'campaign.sqlite') as db:
        before=[dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY task_id')]
    write(l03/'after_interruption.json',dict(exit_code=process.returncode,attempts=before))
    result=campanhas.run(interrupted)
    assert result['unknown']==3 and result['not_started']==2 and result['completed']==1
    control=l03/'controle';campanhas.initialize(control,limit=18);result_control=campanhas.run(control)
    assert result_control['completed']==3 and result_control['unknown']==2 and result_control['failed']==1
    write(l03/'comparison.json',dict(interrompida=result,controle=result_control,
          baseline='Contar apenas completed omite tentativas desconhecidas e não iniciadas',
          limites='Fixtures D, não inferência; unidades de orçamento não são reais'))
    write(folder/'manifesto.json',dict(version='parte-I-1.0',utc=datetime.now(timezone.utc).isoformat(),
        python=platform.python_version(),duration_seconds=round(time.perf_counter()-start,3),
        calls_real_models=0,source={name:sha(PROJECT/'laboratorios'/name) for name in SOURCES},
        artifacts={p.relative_to(folder).as_posix():sha(p) for p in folder.rglob('*') if p.is_file()}))
    return verify(folder)


def verify(folder):
    folder=Path(folder);manifest=json.loads((folder/'manifesto.json').read_text(encoding='utf8'))
    for name,h in manifest['source'].items():
        if sha(PROJECT/'laboratorios'/name)!=h:raise ValueError('Código mudou: '+name)
    for name,h in manifest['artifacts'].items():
        if sha(folder/name)!=h:raise ValueError('Artefato mudou: '+name)
    admitted=[json.loads(line) for line in (folder/'L02/tarefas_admitidas.jsonl').read_text(encoding='utf8').splitlines()]
    catalogo.exigir_particoes(admitted)
    temporal=[json.loads(line) for line in (folder/'L02/tarefas_temporais.jsonl').read_text(encoding='utf8').splitlines()]
    if catalogo.por_periodo(temporal)!=temporal:raise ValueError('Partição temporal divergente')
    for name in ('interrompida','controle'):
        target=folder/'L03'/name
        # Confere o replay sem escrever nos artefatos originais.
        with campanhas.db_at(target/'campaign.sqlite') as db:
            cfg=campanhas.load_config(target,db)
            rows=[dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY task_id')]
            dispatches=[r['task_id'] for r in db.execute("SELECT task_id FROM events WHERE event='dispatch'")]
        if len(rows)!=len(cfg['admitted']) or len(dispatches)!=len(set(dispatches)):
            raise ValueError('Completude ou duplicação inválida')
        recorded=[json.loads(line) for line in (target/'outcomes.jsonl').read_text(encoding='utf8').splitlines()]
        if [{k:r[k] for k in rows[0]} for r in recorded]!=rows:raise ValueError('Resultado diverge do banco')
    return dict(laboratorios=['L00','L01','L02','L03'],artefatos=len(manifest['artifacts']),
                nova_inferencia=False,hashes='conferidos',manifest_sha256=sha(folder/'manifesto.json'))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--saida',type=Path,required=True)
    parser.add_argument('--conferir',action='store_true');args=parser.parse_args()
    print(json.dumps(verify(args.saida) if args.conferir else capture(args.saida),ensure_ascii=False))


if __name__=='__main__':main()
