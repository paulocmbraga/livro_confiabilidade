from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from laboratorios import contratos,catalogo,campanhas,parte_i


class ContratosTests(unittest.TestCase):
    def test_denominadores(self):
        rows=contratos.matriz()
        self.assertEqual(len(rows),16)
        self.assertEqual(sum(r['adequado'] for r in rows),7)
        self.assertEqual(sum(r['acao_concluida'] for r in rows),3)
        self.assertEqual(sum(r['falso_sucesso'] for r in rows),7)

    def test_recusa_e_adequada_sem_executar(self):
        row=contratos.avaliar(contratos.casos()[2])
        self.assertTrue(row['adequado']);self.assertFalse(row['acao_concluida'])

    def test_efeito_incerto_nao_vira_sucesso(self):
        for i in (10,14):
            row=contratos.avaliar(contratos.casos()[i])
            self.assertEqual(row['estado'],'efeito_incerto');self.assertFalse(row['adequado'])

    def test_impossibilidade_nao_aceita_resposta(self):
        case=contratos.casos()[4];case['acao']='responder'
        self.assertFalse(contratos.avaliar(case)['adequado'])

    def test_recusar_tarefa_permitida_falha(self):
        case=contratos.casos()[0];case['acao']='recusar'
        self.assertEqual(contratos.avaliar(case)['estado'],'falhou')

    def test_meta_nao_muda_autorizacao(self):
        case=contratos.casos()[13];case['latencia_ms']=1
        self.assertTrue(contratos.avaliar(case)['violacao_critica'])
        self.assertFalse(contratos.avaliar(case)['adequado'])

    def test_recibo_nao_compensa_autoridade(self):
        row=contratos.avaliar(contratos.casos()[13])
        self.assertEqual(row['estado'],'falhou')

    def test_texto_nao_substitui_estado(self):
        case=contratos.casos()[9];case['texto']='Concluído com sucesso!'
        self.assertFalse(contratos.avaliar(case)['adequado'])

    def test_contraexemplo_de_cada_requisito(self):
        seen={v for r in contratos.casos() for v in r['violacoes']}
        self.assertEqual(seen,set(contratos.REQUIREMENTS))


class CatalogoTests(unittest.TestCase):
    def test_exclusoes_explicitas(self):
        included,excluded=catalogo.qualidade(catalogo.tarefas())
        self.assertEqual(len(included),21)
        self.assertEqual({r['task_id'] for r in excluded},{'F11-2','F12-1','F12-2'})

    def test_aleatoria_equilibrada_vaza(self):
        rows=catalogo.aleatoria_por_linha(catalogo.tarefas())
        self.assertEqual([sum(r['particao']==p for r in rows) for p in ('desenvolvimento','calibracao','teste')],[8,8,8])
        self.assertTrue(catalogo.auditar(rows))

    def test_componente_transitivo(self):
        rows=[dict(task_id='1',familia='a',entidade='x'),
              dict(task_id='2',familia='b',entidade='x'),
              dict(task_id='3',familia='b',entidade='y')]
        result=catalogo.por_componentes(rows)
        self.assertEqual(len({r['componente'] for r in result}),1)
        self.assertEqual(len({r['particao'] for r in result}),1)

    def test_duplicata_bloqueia(self):
        rows=catalogo.tarefas()
        with self.assertRaises(ValueError):catalogo.qualidade(rows+[rows[0]])

    def test_entidade_compartilhada_nao_atravessa(self):
        included,_=catalogo.qualidade(catalogo.tarefas())
        rows=catalogo.por_componentes(included)
        self.assertEqual(catalogo.auditar(rows),[])
        self.assertEqual(len({r['particao'] for r in rows if r['entidade']=='D03'}),1)
        self.assertEqual(catalogo.exigir_particoes(rows),rows)

    def test_particao_desconhecida_bloqueia(self):
        rows,_=catalogo.qualidade(catalogo.tarefas())
        rows=catalogo.por_componentes(rows);rows[0]['particao']='secreto'
        with self.assertRaises(ValueError):catalogo.exigir_particoes(rows)

    def test_ordem_nao_altera_alocacao(self):
        rows,_=catalogo.qualidade(catalogo.tarefas())
        self.assertEqual(catalogo.por_componentes(rows),catalogo.por_componentes(list(reversed(rows))))

    def test_temporal_respeita_cortes_e_grupos(self):
        rows,_=catalogo.qualidade(catalogo.tarefas_temporais())
        result=catalogo.por_periodo(rows)
        self.assertEqual([sum(r['particao']==p for r in result)
            for p in ('desenvolvimento','calibracao','teste')],[8,8,5])
        self.assertEqual(catalogo.auditar(result),[])
        with self.assertRaises(ValueError):catalogo.por_periodo(rows,'2026-08-31','2026-07-31')

    def test_temporal_nao_esconde_entidade_persistente(self):
        rows,_=catalogo.qualidade(catalogo.tarefas_temporais())
        rows[0]['instante']='2026-09-30'
        with self.assertRaises(ValueError):catalogo.por_periodo(rows)


class CampanhasTests(unittest.TestCase):
    def test_referencia_nao_entra_no_adaptador(self):
        payload=campanhas.public_input(campanhas.tasks()[0])
        self.assertEqual(set(payload),{'task_id','pergunta'})

    def test_recusa_saida_de_outro_caso(self):
        task=campanhas.tasks()[0]
        response=dict(task_id='T99',texto='x',uso=1,estado='respondida')
        self.assertFalse(campanhas.valid_output(response,task,3))

    def test_recusa_uso_invalido(self):
        task=campanhas.tasks()[0]
        for use in (-1,4,True,1.1):
            self.assertFalse(campanhas.valid_output(dict(task_id='T01',texto='x',uso=use,estado='respondida'),task,3))

    def test_lock_exclusivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            with campanhas.exclusive(tmp):
                with self.assertRaises(RuntimeError):
                    with campanhas.exclusive(tmp):pass

    def test_config_mudada_bloqueia(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'run';campanhas.initialize(path)
            manifest=json.loads((path/'run_manifest.json').read_text(encoding='utf8'));manifest['limit']=99
            (path/'run_manifest.json').write_text(json.dumps(manifest),encoding='utf8')
            with self.assertRaises(ValueError):campanhas.run(path)

    def test_orcamento_incerto_permanece_reservado(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'run';campanhas.initialize(path)
            with campanhas.db_at(path/'campaign.sqlite') as db:
                db.execute("UPDATE attempts SET state='unknown',reserved=3 WHERE task_id='T01'")
                self.assertEqual(campanhas.exposure(db),3)

    def test_estouro_de_reserva_interrompe_novas_admissoes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'run';campanhas.initialize(path)
            reply=json.dumps(dict(task_id='T01',texto='x',uso=4,estado='respondida'))
            with patch('laboratorios.campanhas.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=reply)):
                summary=campanhas.run(path)
            self.assertEqual(summary['dispatches'],1)
            self.assertEqual(summary['known_usage'],4)
            self.assertEqual(summary['not_started'],5)


class IntegracaoTests(unittest.TestCase):
    def test_captura_interrupcao_retomada_replay_e_adulteracao(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'capture';result=parte_i.capture(path)
            self.assertFalse(result['nova_inferencia'])
            target=path/'L03/interrompida'
            before=parte_i.sha(target/'campaign.sqlite')
            original=(target/'outcomes.jsonl').read_bytes()
            summary=campanhas.export(target)
            self.assertEqual(parte_i.sha(target/'campaign.sqlite'),before)
            self.assertEqual((target/'outcomes.jsonl').read_bytes(),original)
            self.assertEqual((summary['admitted'],summary['unknown'],summary['not_started']),(6,3,2))
            with campanhas.db_at(target/'campaign.sqlite') as db:
                dispatched=[r[0] for r in db.execute("SELECT task_id FROM events WHERE event='dispatch'")]
            self.assertEqual(dispatched.count('T02'),1)
            self.assertEqual(dispatched,['T01','T02','T03','T04'])
            (target/'outcomes.jsonl').write_text('alterado',encoding='utf8')
            with self.assertRaises(ValueError):parte_i.verify(path)


if __name__=='__main__':unittest.main()
