import copy
import unittest
from statistics import mean
from laboratorios.estatistica import quantil, intervalo, parear, decidir, auditar_particoes
from laboratorios.piloto04 import catalogo, executar


class EstatisticaTests(unittest.TestCase):
    def test_quantil_oraculo_manual(self):
        self.assertEqual(quantil([0,10,20,30],0.25),7.5)
        self.assertEqual(quantil([4],0.9),4)

    def test_quantil_rejeita_nao_finito(self):
        for vals in ([],[float('nan')],[float('inf')]):
            with self.assertRaises(ValueError): quantil(vals,0.5)

    def test_bootstrap_dois_pontos_distribuicao_exata(self):
        # Para [-1,1] e tamanho 2: médias -1,0,1 têm probabilidades 1/4,1/2,1/4.
        ic = intervalo([-1,1],n_boot=2000)
        self.assertEqual((ic['inferior'],ic['superior']),(-1,1))
        self.assertEqual(ic['media'],0)

    def test_degenerado_sinalizado(self):
        ic = intervalo([1]*8,n_boot=100)
        self.assertTrue(ic['degenerado'])

    def test_seed_reproduz(self):
        self.assertEqual(intervalo([-1,0,1],n_boot=100),intervalo([-1,0,1],n_boot=100))

    def test_configuracao_invalida(self):
        with self.assertRaises(ValueError): intervalo([1],n_boot=100)
        with self.assertRaises(ValueError): intervalo([1,2],n_boot=10)

    def test_pesos_mudam_estimando(self):
        ts=catalogo(); pares,linhas=parear(ts,executar(ts))
        self.assertEqual(mean(p['delta'] for p in pares),0)
        self.assertAlmostEqual(mean(linhas),180/380)

    def test_balancear_preserva_media_tarefas(self):
        ts=catalogo(True); pares,linhas=parear(ts,executar(ts))
        self.assertEqual(mean(linhas),0)
        self.assertEqual(mean(p['delta'] for p in pares),0)

    def test_rejeita_omissao(self):
        ts=catalogo(); rows=executar(ts)
        with self.assertRaises(ValueError): parear(ts,rows[:-1])

    def test_rejeita_repeticoes_invalidas(self):
        for n in (0,-1,True,1.5):
            ts=catalogo(); ts[0]['repeticoes']=n
            with self.assertRaises(ValueError): parear(ts,[])

    def test_rejeita_duplicata(self):
        ts=catalogo(); rows=executar(ts)
        with self.assertRaises(ValueError): parear(ts,rows+[rows[0]])

    def test_rejeita_id_inesperado(self):
        ts=catalogo(); rows=executar(ts); rows[0]['task_id']='estranho'
        with self.assertRaises(ValueError): parear(ts,rows)

    def test_incerto_nunca_sucesso(self):
        ts=catalogo(); rows=executar(ts)
        self.assertEqual(sum(r['estado']=='efeito_incerto' for r in rows),5)
        r=next(r for r in rows if r['estado']=='efeito_incerto'); r['score']=1
        with self.assertRaises(ValueError): parear(ts,rows)

    def test_ordem_das_linhas_nao_importa(self):
        ts=catalogo(); rows=executar(ts)
        self.assertEqual(parear(ts,rows),parear(ts,list(reversed(rows))))

    def test_violacao_vence_media(self):
        self.assertEqual(decidir({'inferior':.1,'superior':.3},violacoes=1)['decisao'],'bloquear_por_invariante')

    def test_limite_nao_e_ganho(self):
        self.assertEqual(decidir({'inferior':.05,'superior':.2})['estatistica'],'inconclusivo')

    def test_estados_decisao(self):
        self.assertEqual(decidir({'inferior':.06,'superior':.2})['decisao'],'candidata_a_nova_validacao')
        self.assertEqual(decidir({'inferior':-.2,'superior':.04})['estatistica'],'ganho_abaixo_da_margem')

    def test_vazamento_familia(self):
        ts=catalogo(); clone=copy.deepcopy(ts[0]); clone['particao']='teste'
        with self.assertRaises(ValueError): auditar_particoes(ts+[clone])


if __name__ == '__main__': unittest.main()
