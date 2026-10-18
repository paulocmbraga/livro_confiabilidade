from copy import deepcopy
import math
from pathlib import Path
import tempfile
import unittest
from laboratorios import respostas05 as a, recuperacao06 as r, memoria07 as m, agentes08 as g, destino08 as d
from laboratorios.dados_ii import corpus,allowed


class Answers(unittest.TestCase):
    def test_valid_citation_wrong_claim(self):
        result=a.evaluate(a.cases()[1]);self.assertTrue(result['baseline_citation']);self.assertFalse(result['adequate'])
    def test_incomplete_supported(self):
        result=a.evaluate(a.cases()[2]);self.assertTrue(result['claims'][0]['support']);self.assertFalse(result['complete'])
    def test_irrelevant_supported(self):
        result=a.evaluate(a.cases()[5]);self.assertTrue(result['claims'][0]['support']);self.assertFalse(result['adequate'])
    def test_denominator_zero_answered(self):
        result=a.aggregate([a.evaluate(t,1) for t in a.cases()])
        self.assertEqual(result['admitted'],12);self.assertIsNone(result['error_given_answer']);self.assertEqual(result['coverage'],0)
    def test_refusal_accounting(self):
        result=a.aggregate([a.evaluate(t,1) for t in a.cases()])
        self.assertEqual((result['correct_abstentions'],result['unnecessary_abstentions']),(4,8))
    def test_restricted_support(self):
        self.assertFalse(a.evaluate(a.cases()[10])['claims'][0]['support'])
    def test_expired_citation(self):
        task=a.cases()[0];task['candidate']['claims'][0]=dict(key='troca_comum',value='60 dias',citation='D06')
        self.assertFalse(a.evaluate(task)['claims'][0]['permitted'])
    def test_text_is_not_semantic_parser(self):
        task=a.cases()[0];task['candidate']['text']='paráfrase preparada'
        self.assertEqual(a.evaluate(task),a.evaluate(a.cases()[0]))
    def test_missing_document(self):
        task=a.cases()[0];task['candidate']['claims'][0]['citation']='inexistente'
        self.assertFalse(a.evaluate(task)['baseline_citation'])
    def test_bad_threshold(self):
        with self.assertRaises(ValueError):a.evaluate(a.cases()[0],1.1)


class Retrieval(unittest.TestCase):
    def test_acl_and_time_every_method(self):
        for q in r.queries():
            for method in ('lexical','vetor_manual','hibrida','rerank'):
                self.assertTrue(set(r.rank(q,method)).isdisjoint({'D05','D06','D07'}))
    def test_ndcg_known(self):
        result=r.retrieval_metrics(['b','a'],{'a':3,'b':1})
        self.assertAlmostEqual(result['ndcg'],(1+7/math.log2(3))/(7+1/math.log2(3)))
    def test_empty_relevance_undefined(self):
        result=r.retrieval_metrics([],{});self.assertIsNone(result['recall']);self.assertIsNone(result['ndcg'])
    def test_qrels_include_zero_grades(self):
        for q in r.queries():
            self.assertEqual(set(q['qrels']),{d['doc_id'] for d in corpus() if allowed(d)})
    def test_duplicate_ranking_rejected(self):
        with self.assertRaises(ValueError):r.retrieval_metrics(['a','a'],{'a':1})
    def test_reference_not_in_generator(self):
        self.assertNotIn('expected',r.public_query(r.queries()[0]));self.assertNotIn('qrels',r.public_query(r.queries()[0]))
    def test_exception_composition(self):
        q=r.queries()[0];docs=corpus()[:2]
        self.assertEqual(r.generate(r.public_query(q),docs),q['expected'])
        self.assertNotEqual(r.generate(r.public_query(q),docs,'primeiro'),q['expected'])
    def test_reference_still_bad_generator(self):
        result=r.compare(r.queries()[1],'hibrida','primeiro');self.assertFalse(result['reference_correct'])
    def test_conflict_abstains(self):
        q=r.queries()[-1];docs=[d for d in corpus() if d['doc_id'] in ('D10','D12')]
        self.assertEqual(r.generate(r.public_query(q),docs),{})
    def test_synonym_query_has_real_vector_signal(self):
        q=r.queries()[3];self.assertEqual(r.rank(q,'lexical'),[]);self.assertEqual(r.rank(q,'vetor_manual')[0],'D08')
    def test_future_boundaries(self):
        doc=next(d for d in corpus() if d['doc_id']=='D07')
        self.assertFalse(allowed(doc,day='2026-10-31'));self.assertTrue(allowed(doc,day='2026-11-01'))
    def test_valid_historical_intervals(self):
        self.assertTrue(all(d['valid_from']<=d['valid_to'] for d in corpus()))
        old=next(d for d in corpus() if d['doc_id']=='D06')
        self.assertTrue(allowed(old,day='2025-09-30'));self.assertFalse(allowed(old))


class Memory(unittest.TestCase):
    def test_selected_all_episodes(self):
        for episode in m.episodes():self.assertTrue(all(r['correct'] for r in m.run(episode,'selecionada')[0]))
    def test_stale_cache_after_correction(self):
        result=m.run(m.episodes()[0],'historico')[0];self.assertFalse(result[-1]['correct'])
    def test_deletion_all_live_stores(self):
        memory=m.Memory('selecionada');memory.store(m.put('email','x'));memory.retrieve(m.ask('email','x'))
        memory.delete('ana','email');snapshot=memory.snapshot()
        self.assertEqual(snapshot['records'],[]);self.assertEqual(snapshot['index'],{});self.assertEqual(snapshot['cache'],{})
    def test_summary_cache_survives(self):
        result=m.run(m.episodes()[2],'resumo')[0];self.assertFalse(result[-1]['correct'])
    def test_expiry_boundary(self):
        memory=m.Memory('selecionada');memory.store(m.put('frete','gratuito',until=5))
        self.assertEqual(memory.retrieve(m.ask('frete',None,5))[0],'gratuito')
        self.assertIsNone(memory.retrieve(m.ask('frete',None,6))[0])
    def test_summary_drops_condition(self):
        self.assertFalse(m.run(m.episodes()[3],'resumo')[0][0]['correct'])
    def test_cross_identity(self):
        self.assertTrue(m.run(m.episodes()[4],'historico')[0][0]['exposure'])
        self.assertFalse(m.run(m.episodes()[4],'selecionada')[0][0]['exposure'])
    def test_hostile_admission(self):
        result,events=m.run(m.episodes()[5],'selecionada');self.assertEqual(events[0]['status'],'rejeitado_origem')
        self.assertTrue(result[0]['correct'])
    def test_truncation_loses_valid_information(self):
        self.assertFalse(m.run(m.episodes()[6],'ultimos_dois')[0][0]['correct'])
    def test_revisions_survive_delete(self):
        memory=m.Memory('selecionada');memory.store(m.put('a','1'));memory.store(m.put('b','2'))
        memory.delete('ana','a');memory.store(m.put('c','3'));self.assertEqual(memory.records[-1]['revision'],3)


class Agent(unittest.TestCase):
    def trial(self,scenario,variant='workflow',attempt=1):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'destination.sqlite';d.initialize(path,scenario)
            return g.execute(path,scenario,variant,attempt)
    def test_normal_effect_independent_process(self):
        result,snapshot=self.trial('normal');self.assertTrue(result['completed']);self.assertEqual(len(snapshot['reservations']),1)
    def test_alternative_trajectory(self):
        first,_=self.trial('normal','agente_d',1);second,_=self.trial('normal','agente_d',2)
        self.assertNotEqual(first['history'][0]['request']['operation'],second['history'][0]['request']['operation'])
        self.assertTrue(first['completed'] and second['completed'])
    def test_false_text_not_effect(self):
        result,_=self.trial('sucesso_falso','agente_d');self.assertEqual(result['narrative'],'sucesso');self.assertFalse(result['completed'])
    def test_lost_response_workflow_reconciles(self):
        result,_=self.trial('resposta_perdida');self.assertTrue(result['completed']);self.assertEqual(result['steps'],5)
    def test_uncertain_distinct_from_absent(self):
        result,snapshot=self.trial('sem_observacao');self.assertEqual(result['state'],'efeito_incerto')
        self.assertEqual(len(snapshot['reservations']),1)
    def test_budget_stops_cycle(self):
        result,_=self.trial('ciclo','agente_d');self.assertEqual(result['steps'],6);self.assertEqual(result['stopped'],'budget')
    def test_unauthorized_attempt_blocked(self):
        result,snapshot=self.trial('identidade_trocada');self.assertEqual(result['unauthorized_attempts'],1)
        self.assertEqual(snapshot['reservations'],[])
    def test_refusal_not_completed(self):
        result,_=self.trial('negada');self.assertTrue(result['adequate']);self.assertFalse(result['completed'])
    def test_impossible_not_failure(self):
        result,_=self.trial('sem_estoque');self.assertEqual(result['state'],'impossivel')
    def test_payload_bound_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'d.sqlite';d.initialize(path,'normal')
            request=dict(operation='reserve',principal='ana',intent='I1',sku='P1',quantity=2)
            self.assertEqual(g.call(path,request)['status'],'denied')
    def test_idempotent_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'d.sqlite';d.initialize(path,'normal')
            request=dict(operation='reserve',principal='ana',intent='I1',sku='P1',quantity=1)
            g.call(path,request);g.call(path,request)
            snapshot=g.call(path,dict(operation='snapshot'));self.assertEqual(snapshot['stock'][0]['quantity'],1)


if __name__=='__main__':unittest.main()
