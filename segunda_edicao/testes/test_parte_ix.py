"""Contratos adversos: ausência, seleção, identidade e concorrência."""
import copy,unittest
from concurrent.futures import ThreadPoolExecutor
from laboratorios.parte_ix.core import *
from laboratorios.parte_ix.slo import events
from laboratorios.parte_ix.economics import tasks,choose_threshold,totals


class Observation(unittest.TestCase):
    def setUp(self):
        self.ledger=[dict(task='a',role='client',trace_id='1',span_id='2',parent_id=None,sampled=True),
                     dict(task='b',role='client',trace_id='3',span_id='4',parent_id=None,sampled=False)]
        self.received=[dict(self.ledger[0])];self.attempts=[dict(ids=[['1','2']])]
    def test_planned_is_not_loss(self):
        r=reconcile(self.ledger,self.received,self.attempts);self.assertEqual((r['lost'],r['planned_exclusions']),(0,1))
    def test_drop_is_loss(self):self.assertEqual(reconcile(self.ledger,[],self.attempts)['lost'],1)
    def test_queue_never_sent(self):self.assertEqual(reconcile(self.ledger,[],[])['never_exported'],1)
    def test_export_failure(self):self.assertEqual(reconcile(self.ledger,[],self.attempts)['attempted_not_received'],1)
    def test_wrong_task(self):
        self.received[0]['task']='other';self.assertEqual(reconcile(self.ledger,self.received,self.attempts)['wrong_bindings'],1)
    def test_wrong_parent(self):
        self.received[0]['parent_id']='bad';self.assertEqual(reconcile(self.ledger,self.received,self.attempts)['wrong_bindings'],1)
    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):reconcile(self.ledger,self.received*2,self.attempts)
    def test_orphan_rejected(self):
        self.received[0]['span_id']='alien'
        with self.assertRaises(ValueError):reconcile(self.ledger,self.received,self.attempts)


class Objectives(unittest.TestCase):
    def setUp(self):self.events=events()
    def test_http_can_be_perfect_while_quality_fails(self):
        r=cohort(self.events,102,30);self.assertEqual(r['availability'],1);self.assertAlmostEqual(r['quality_known'],.7)
    def test_missing_is_unknown(self):
        r=cohort(self.events,132,5);self.assertEqual((r['n'],r['known'],r['unknown']),(50,0,50))
    def test_missing_bounds(self):
        r=cohort(self.events,132,5);self.assertEqual((r['quality_lower'],r['quality_upper']),(0,1))
    def test_no_denominator_no_perfection(self):self.assertIsNone(cohort([],100,30)['quality_known'])
    def test_immature_excluded(self):self.assertEqual(cohort(self.events,20,5)['n'],50)
    def test_future_labels_not_used(self):
        r=cohort(self.events,10,5,lag=0);self.assertGreater(r['unknown'],0)
    def test_complex_segment_exposes_failure(self):self.assertEqual(cohort(self.events,102,30,segment='complex')['quality_known'],0)
    def test_simple_segment_remains_good(self):self.assertEqual(cohort(self.events,102,30,segment='simple')['quality_known'],1)
    def test_quality_alert(self):self.assertTrue(alert(self.events,90)['quality'])
    def test_observation_alert_separate(self):
        r=alert(self.events,132);self.assertTrue(r['observation']);self.assertFalse(r['quality'])
    def test_healthy_no_alert(self):
        r=alert(self.events,50);self.assertFalse(r['quality']);self.assertFalse(r['observation'])
    def test_bad_target(self):
        with self.assertRaises(ValueError):burn(cohort(self.events,50,5),target=1)
    def test_low_volume_suppressed(self):self.assertIsNone(burn(cohort(self.events[:1],20,30)))


class Economics(unittest.TestCase):
    def test_zero_useful_undefined(self):self.assertIsNone(useful_cost(12,0))
    def test_negative_rejected(self):
        with self.assertRaises(ValueError):useful_cost(-1,3)
    def test_cache_tenant_boundary(self):self.assertNotEqual(cache_key('a','p','m','v','s'),cache_key('b','p','m','v','s'))
    def test_cache_model_boundary(self):self.assertNotEqual(cache_key('a','p','m','v','s'),cache_key('a','p','n','v','s'))
    def test_cache_policy_boundary(self):self.assertNotEqual(cache_key('a','p','m','v','s'),cache_key('a','p','m','w','s'))
    def test_cache_schema_boundary(self):self.assertNotEqual(cache_key('a','p','m','v','s'),cache_key('a','p','m','v','z'))
    def test_budget_unknown_not_refunded(self):
        b=Budget(10);self.assertTrue(b.reserve('a',8));b.settle('a',None);self.assertFalse(b.reserve('b',3))
    def test_budget_reconcile(self):
        b=Budget(10);b.reserve('a',8);b.settle('a',7);self.assertTrue(b.reserve('b',3))
    def test_budget_overrun_rejected(self):
        b=Budget(10);b.reserve('a',8)
        with self.assertRaises(ValueError):b.settle('a',9)
        self.assertEqual(b.holds['a'],8)
    def test_budget_duplicate_settlement(self):
        b=Budget(10);b.reserve('a',8);b.settle('a',7)
        with self.assertRaises(ValueError):b.settle('a',7)
    def test_budget_concurrent_admission(self):
        b=Budget(100)
        with ThreadPoolExecutor(12) as pool:results=list(pool.map(lambda i:b.reserve(str(i),30),range(20)))
        self.assertEqual(sum(results),3);self.assertEqual(sum(b.holds.values()),90)
    def test_threshold_no_eligible_keeps_gate_red(self):
        data=tasks('development');rows=[dict(task=t['id'],model=m,acceptable=False,token_units=10) for t in data for m in ['smol','qwen']]
        result=choose_threshold(rows,data);self.assertFalse(result['quality_gate_met']);self.assertEqual(result['threshold'],-1)
    def test_threshold_cost_subject_to_quality(self):
        data=tasks('development');rows=[dict(task=t['id'],model=m,acceptable=m=='qwen' or t['complexity']==0,
            token_units=30 if m=='qwen' else 10) for t in data for m in ['smol','qwen']]
        self.assertEqual(choose_threshold(rows,data)['threshold'],0)
    def test_splits_disjoint(self):
        a,b,c=[{t['id'] for t in tasks(s)} for s in ['development','reserve','shift']]
        self.assertFalse(a&b or a&c or b&c)
    def test_shift_changes_complex_mix(self):self.assertEqual(sum(t['complexity'] for t in tasks('shift')),10)
    def test_invalid_approval_not_useful(self):
        row=dict(value='aprovar',acceptable=False,elapsed=1,cache_hit=False,response={'usage':{'total_tokens':4}})
        r=totals([row]);self.assertEqual(r['useful_automatic'],0);self.assertEqual(r['unsafe_approvals'],1)
    def test_review_is_pending_not_human_success(self):
        row=dict(value='revisar',acceptable=True,elapsed=1,cache_hit=False,response={'usage':{'total_tokens':4}})
        r=totals([row]);self.assertEqual((r['human_pending'],r['useful_automatic']),(1,0))
    def test_guard_blocks_complex_approval(self):
        row=dict(value='aprovar',acceptable=False,review_required=True,elapsed=1,cache_hit=False,
                 response={'usage':{'total_tokens':4}})
        r=totals([row]);self.assertEqual((r['human_pending'],r['unsafe_approvals']),(1,0))


class Capacity(unittest.TestCase):
    def test_percentile_empty(self):self.assertIsNone(percentile([],.95))
    def test_p99_small_sample_is_max(self):self.assertEqual(percentile(list(range(18)),.99),17)
    def test_quantile_invalid(self):
        with self.assertRaises(ValueError):percentile([1],0)
    def test_rejection_retained_in_denominator(self):
        from laboratorios.parte_ix.serving import summary
        rows=[dict(id='T00',status='rejected',start_lag=.1,tenant='a')]
        r=summary(rows);self.assertEqual((r['offered'],r['rejected'],r['within_4s']),(1,1,0))
if __name__=='__main__':unittest.main()
