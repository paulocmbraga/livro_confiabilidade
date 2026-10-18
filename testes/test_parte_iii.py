"""Contraprovas dos mecanismos, cálculos e fronteiras dos laboratórios L09-L12."""
from copy import deepcopy
import json
import unittest
from laboratorios import oraculos09 as o, anotacao10 as a, juizes11 as j, experimentos12 as e
from laboratorios.parte_iii import unique
from laboratorios.recuperacao06 import queries, public_query


class Oracles(unittest.TestCase):
    def test_shared_bug_accepts_broken_stock(self):
        s=o.base_case();s['after']=o.shared_stock(s['before'],s['quantity'])
        self.assertTrue(o.evaluate(s,'compartilhado'));self.assertIn('conservacao',o.defects(s))

    def test_all_author_labels(self):
        for c in o.cases():
            with self.subTest(c=c['case_id']):self.assertEqual(o.evaluate(c['state'],'contrato'),c['valid'])

    def test_swap_reads(self):
        s=o.base_case();s['operations'][:2]=reversed(s['operations'][:2])
        self.assertTrue(o.evaluate(s,'contrato'));self.assertFalse(o.evaluate(s,'literal'))

    def test_narrative_independent(self):
        s=o.base_case();before=o.defects(s);s['narrative']='Falha alegada sem mudança de estado'
        self.assertEqual(o.defects(s),before)

    def test_critical_order(self):
        s=o.base_case();s['operations'][-2:]=reversed(s['operations'][-2:])
        self.assertIn('precedencia',o.defects(s))

    def test_boolean_quantity(self):
        s=o.base_case();s.update(quantity=True,after=4);s['reservations'][0]['quantity']=True
        self.assertIn('tipo_quantidade',o.defects(s))

    def test_expiry_boundary(self):
        s=o.base_case();s['now']=10;self.assertFalse(o.defects(s))
        s['now']=11;self.assertIn('prazo',o.defects(s))

    def test_public_excludes_reference(self):
        c=o.cases()[0];public=o.public_task(c)
        self.assertNotIn('valid',public);self.assertNotIn('reservations',public)
        public['principal']='bruno';self.assertEqual(c['state']['principal'],'ana')

    def test_unknown_evaluator(self):
        with self.assertRaises(ValueError):o.evaluate(o.base_case(),'inventado')


class Annotation(unittest.TestCase):
    def test_kappa_known(self):
        result=a.agreement([(1,1),(1,0),(0,0),(0,1)])
        self.assertEqual(result['observed'],.5);self.assertEqual(result['kappa'],0)

    def test_unanimous_degenerate(self):
        result=a.agreement([(2,2)]*6)
        self.assertEqual(result['observed'],1);self.assertIsNone(result['kappa'])

    def test_missing_not_zero(self):
        result=a.agreement([(0,0),(None,2)])
        self.assertEqual((result['admitted'],result['complete'],result['missing']),(2,1,1))
        self.assertEqual(result['observed'],1)

    def test_all_missing(self):
        self.assertIsNone(a.agreement([(None,None)])['observed'])

    def test_partition_families(self):
        c=a.cases();left={r['family'] for r in c if r['partition']=='calibracao'}
        self.assertFalse(left & {r['family'] for r in c if r['partition']=='teste_publico'})

    def test_adjudication_preserves(self):
        rows=a.annotations();before=deepcopy(rows);decisions=a.adjudications(rows)
        self.assertEqual(rows,before);self.assertTrue(decisions)
        self.assertTrue(any(d['status']=='pendente' for d in decisions))

    def test_blind_packages(self):
        for row in a.assignments():
            self.assertNotIn('reference',row);self.assertNotIn('reference_kind',row)
        self.assertNotEqual([r['case_id'] for r in a.assignments() if r['rater']=='revisor_1'],
                            [r['case_id'] for r in a.assignments() if r['rater']=='revisor_2'])

    def form(self):
        allocation=a.assignments()
        return [dict(rater=r['rater'],case_id=r['case_id'],rubric=r['rubric'],dimension=d,
                     score='2',reason='Conferido na evidência.',seconds='20') for r in allocation for d in a.DIMENSIONS]

    def test_import_complete(self):
        self.assertEqual(a.validate_annotations(self.form(),a.assignments())['rows'],72)

    def test_import_duplicate(self):
        rows=self.form();rows[-1]=rows[0]
        with self.assertRaises(ValueError):a.validate_annotations(rows,a.assignments())

    def test_import_missing_reason(self):
        rows=self.form();rows[0]['reason']=''
        with self.assertRaises(ValueError):a.validate_annotations(rows,a.assignments())

    def test_import_missing_assignment(self):
        with self.assertRaises(ValueError):a.validate_annotations(self.form()[:-1],a.assignments())

    def test_import_bad_time(self):
        for value in ('nan','-1','inf'):
            rows=self.form();rows[0]['seconds']=value
            with self.assertRaises(ValueError):a.validate_annotations(rows,a.assignments())


class Judges(unittest.TestCase):
    def req(self,reverse=False):return j.request(j.cases()[0],'base',reverse)

    def test_reconcile_identity(self):
        for reverse,choice in ((False,'A'),(True,'B')):
            raw=json.dumps(dict(choice=choice,confidence=.8,reason='evidência'))
            self.assertEqual(j.parse(raw,self.req(reverse))['winner'],'J01a')

    def test_broken_json(self):
        self.assertFalse(j.parse('{"choice":"A"',self.req())['valid'])

    def test_bad_score_and_extra(self):
        for score in (True,float('nan'),float('inf'),-1,2,'0.9'):
            self.assertFalse(j.parse(json.dumps(dict(choice='A',confidence=score,reason='x')),self.req())['valid'])
        self.assertFalse(j.parse('{"choice":"A","confidence":1,"reason":"x","extra":1}',self.req())['valid'])

    def test_no_reference_in_request(self):
        self.assertNotIn('reference',self.req());self.assertNotIn('partition',self.req())

    def test_injection_fixture(self):
        req=j.request(j.cases()[0],'instrucao')
        self.assertEqual(j.parse(j.judge(req,'vulneravel'),req)['winner'],'J01b')
        self.assertEqual(j.parse(j.judge(req,'regra'),req)['winner'],'J01a')

    def test_style_does_not_change_claims(self):
        left=self.req();right=j.request(j.cases()[0],'verbosidade')
        self.assertEqual([c['claim'] for c in left['candidates']],[c['claim'] for c in right['candidates']])

    def test_gate_disagreement(self):
        left=dict(valid=True,winner='x',confidence=.9);right=dict(valid=True,winner='y',confidence=.9)
        self.assertEqual(j.gate(left,right,'comum',.5)['reason'],'posicao')

    def test_gate_critical(self):
        p=dict(valid=True,winner='x',confidence=1)
        self.assertEqual(j.gate(p,p,'alto',.5)['reason'],'risco')

    def test_calibration_rejects_test(self):
        ps=j.paired(j.trials());test=[p for p in ps if p['partition']=='teste_publico']
        with self.assertRaises(ValueError):j.calibrate(test)

    def test_zero_auto_undefined(self):
        pair=j.paired(j.trials())[0]
        result=j.policy_metrics([pair],1)
        self.assertEqual(result['automatic'],0);self.assertIsNone(result['error_given_automatic'])


class Experiments(unittest.TestCase):
    def test_balanced_order(self):
        for task in queries():
            for condition in ('frio','quente'):
                for k,g in e.VARIANTS:
                    ps=[p['position'] for p in e.plan() if (p['query_id'],p['cache'],p['k'],p['generator'])==
                        (task['query_id'],condition,k,g)]
                    self.assertEqual(sorted(ps),[1,2,3,4])

    def test_cache_key_isolates_identity_and_time(self):
        q=public_query(queries()[0]);before=e.cache_key(q)
        q['identity']='comercial';self.assertNotEqual(before,e.cache_key(q))
        q=public_query(queries()[0]);q['day']='2026-11-01';self.assertNotEqual(before,e.cache_key(q))

    def test_cache_copy(self):
        q=public_query(queries()[0]);cache={};ranking,calls=e.retrieve(q,cache)
        ranking.clear();again,hits=e.retrieve(q,cache)
        self.assertTrue(again);self.assertEqual((calls,hits),(1,0))

    def test_warmup_accounted(self):
        q=queries()[0];cold=e.run_once(q,2,'compor','frio');warm=e.run_once(q,2,'compor','quente')
        self.assertEqual(cold['response'],warm['response'])
        self.assertEqual(warm['retrieval_calls'],0);self.assertEqual(warm['warmup_calls'],1)
        self.assertEqual(cold['retrieval_calls'],1)

    def test_factorial_interaction(self):
        result=e.effects(e.factorial())
        self.assertEqual(result['context_given_first'],0)
        self.assertEqual(result['context_given_compose'],3/8)
        self.assertEqual(result['interaction'],3/8)

    def test_naive_tasks_differ(self):
        rows=e.naive();left={r['query_id'] for r in rows if r['variant']=='anterior'}
        right={r['query_id'] for r in rows if r['variant']=='nova'}
        self.assertNotEqual(left,right)

    def test_clusters_not_mixed(self):
        rows=e.online_simulation()
        for team in range(12):
            group=[r for r in rows if r['team']==team]
            self.assertEqual(len({r['assigned'] for r in group}),1)
            self.assertEqual(len({r['alternating_assignment'] for r in group}),2)

    def test_abandonment_preserved(self):
        rows=e.online_simulation();self.assertEqual(len(rows),48)
        self.assertEqual(sum(r['status']=='abandono' for r in rows),12)

    def test_exact_p(self):
        self.assertEqual(e.binomial_p(0,5),1/16);self.assertEqual(e.binomial_p(5,10),1)

    def test_sequential_seed_and_nesting(self):
        rows=e.sequential_simulation(30)
        self.assertEqual(rows,e.sequential_simulation(30))
        self.assertTrue(all(not r['bonferroni'] or r['peek'] for r in rows))
        self.assertTrue(all(not r['fixed'] or r['peek'] for r in rows))

    def test_identity_audit(self):
        with self.assertRaises(ValueError):unique([dict(id=1),dict(id=1)],('id',),[(1,),(2,)])
        with self.assertRaises(ValueError):unique([dict(id=1)],('id',),[(1,),(2,)])


if __name__=='__main__':unittest.main()
