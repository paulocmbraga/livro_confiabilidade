import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from laboratorios import observacao17 as o,monitoramento18 as m,capacidade19 as c,economia20 as e


class Observacao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs={p:o.run(p) for p in o.PROFILES}

    def test_denominator_independent(self):
        ledger,events,result=self.runs['sucessos']
        self.assertEqual(len(ledger),12);self.assertLess(result['complete'],12)
        self.assertEqual(sum(r['status']!='ok' for r in ledger),3)

    def test_failed_events_survive(self):
        _,events,_=self.runs['controlado']
        self.assertEqual(sum(r['status']!='ok' for r in events),6)

    def test_sampling_visible(self):
        _,_,result=self.runs['controlado']
        self.assertEqual(result['sampled'],11);self.assertEqual(result['complete'],11)
        self.assertEqual(result['sampled_coverage'],1)
        self.assertEqual(next(r['state'] for r in result['rows'] if r['task']=='T09'),'nao_amostrado')

    def test_loss_detected(self):
        result=self.runs['falhas'][2]
        self.assertFalse(next(r['complete'] for r in result['rows'] if r['task']=='T05'))

    def test_cross_tenant_detected(self):
        self.assertEqual(self.runs['falhas'][2]['identity_errors'],1)

    def test_orphan_detected(self):
        self.assertEqual(self.runs['falhas'][2]['orphans'],1)

    def test_no_secret_guarded(self):
        self.assertNotIn(o.SECRET,json.dumps(self.runs['controlado'][1]))

    def test_positive_privacy_control(self):
        self.assertIn(o.SECRET,json.dumps(self.runs['sucessos'][1]))

    def test_allowlist_rejects_new_nested_fields(self):
        self.assertEqual(o.sanitize({'task':'T','unknown':{'secret':o.SECRET}}),{'task':'T'})

    def test_bad_parent_breaks_completeness(self):
        ledger,events,_=deepcopy(self.runs['controlado'])
        events[0]['parent']='wrong'
        self.assertEqual(o.audit(ledger,events)['complete'],10)

    def test_duplicate_span_not_complete(self):
        ledger,events,_=deepcopy(self.runs['controlado']);events.append(events[0])
        self.assertEqual(o.audit(ledger,events)['complete'],10)

    def test_unknown_profile_rejected(self):
        with self.assertRaises(ValueError):o.run('silencioso')


class Monitoramento(unittest.TestCase):
    def setUp(self):
        self.rows=m.stream();self.selected=m.select_audit(self.rows)

    def test_population(self):
        self.assertEqual(len(self.rows),200);self.assertEqual(len({r['task'] for r in self.rows}),200)

    def test_assignment_before_labels(self):
        changed=[dict(r,correct=not r['correct']) for r in self.rows]
        self.assertEqual(m.select_audit(changed),self.selected)

    def test_reproducible_sampling(self):
        self.assertEqual(m.select_audit(self.rows),self.selected)
        self.assertEqual(len(self.selected),130)

    def test_no_future_label(self):
        for r in m.cohorts(self.rows,self.selected,0):
            self.assertEqual(r['labels'],0);self.assertIsNone(r['error'])

    def test_delay_preserves_cohort(self):
        early=next(r for r in m.cohorts(self.rows,self.selected,3) if r['cohort']==2 and r['segment']=='dificil')
        late=next(r for r in m.cohorts(self.rows,self.selected,5) if r['cohort']==2 and r['segment']=='dificil')
        self.assertFalse(early['complete']);self.assertTrue(late['complete']);self.assertEqual(late['error'],.8)

    def test_feedback_hides_failure(self):
        row=m.summarize(self.rows,self.selected)[2]
        self.assertEqual(row['feedback_quality'],1);self.assertEqual(row['fixture_quality'],.76)

    def test_drift_not_quality_alarm(self):
        alarms=m.monitor(self.rows,self.selected)
        self.assertEqual([a['kind'] for a in alarms if a['cohort']==1],['mudanca_entrada'])

    def test_detection_delay(self):
        quality=[a for a in m.monitor(self.rows,self.selected) if a['kind']=='qualidade']
        self.assertEqual([(a['cohort'],a['day']) for a in quality],[(2,5),(3,6)])

    def test_alert_actionable(self):
        for a in m.monitor(self.rows,self.selected):
            self.assertTrue(a['hypothesis'] and a['action'] and a['owner']);self.assertGreater(a['next_check'],a['day'])

    def test_strata_weighting(self):
        for r in m.cohorts(self.rows,self.selected,6):
            self.assertEqual(r['assigned']/r['population'],r['inclusion_probability'])


class Capacidade(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs={p:asyncio.run(c.trial(p)) for p in ('baseline','limitado')}

    def test_all_offered_accounted(self):
        for rows,_,summary in self.runs.values():
            self.assertEqual(len(rows),33);self.assertEqual(sum(summary['statuses'].values()),33)

    def test_bounded_queue(self):
        self.assertLessEqual(self.runs['limitado'][2]['peak_queue'],4)

    def test_dependency_limit(self):
        for _,_,summary in self.runs.values():self.assertLessEqual(summary['peak_active'],2)

    def test_rejected_not_deleted(self):
        self.assertGreater(self.runs['limitado'][2]['statuses'].get('rejeitado',0),0)

    def test_useful_requires_deadline(self):
        for rows,_,_ in self.runs.values():
            for r in rows:
                if r['useful']:self.assertLessEqual(r['finished'],r['deadline'])

    def test_calls_reconciled(self):
        for rows,calls,_ in self.runs.values():self.assertEqual(sum(r['attempts'] for r in rows),len(calls))

    def test_retry_bound(self):
        self.assertLessEqual(max(r['attempts'] for r in self.runs['limitado'][0]),2)

    def test_drain(self):
        for _,_,summary in self.runs.values():self.assertEqual(summary['remaining'],0)

    def test_recovery_probes_preserved(self):
        for _,_,summary in self.runs.values():self.assertEqual(summary['recovery_offered'],6)

    def test_fallback_only_eligible(self):
        for r in self.runs['limitado'][0]:
            if r['fallback']:self.assertEqual(r['kind'],'simples')

    def test_quantile_with_ties_and_empty(self):
        self.assertIsNone(c.percentile([]));self.assertEqual(c.percentile([1,2,2,90]),90)

    def test_quantile_invalid(self):
        with self.assertRaises(ValueError):c.percentile([1],0)


class Economia(unittest.TestCase):
    def setUp(self):
        self.reports={p:e.aggregate(*e.run(p)) for p in e.POLICIES}

    def test_full_cost_reverses_unit_price(self):
        self.assertGreater(self.reports['barato']['known_mBRL'],self.reports['grande']['known_mBRL'])

    def test_paired_population(self):
        for r in self.reports.values():self.assertEqual(r['tasks'],20)

    def test_routed_decision(self):
        self.assertEqual(e.choose(self.reports),'roteado');self.assertEqual(self.reports['roteado']['known_mBRL'],1160)

    def test_zero_success_is_undefined(self):
        rows,ledger=e.run('barato')
        for r in rows:r['correct']=False
        self.assertIsNone(e.aggregate(rows,ledger)['cost_per_correct_mBRL'])

    def test_unknown_receipt_blocks_choice(self):
        rows,ledger=e.run('roteado');ledger[0]['known']=False
        report=e.aggregate(rows,ledger)
        self.assertIsNone(report['cost_per_correct_mBRL']);self.assertIsNone(e.choose({'roteado':report}))

    def test_missing_receipt_not_zero(self):
        rows,ledger=e.run('roteado');ledger.pop()
        self.assertEqual(e.aggregate(rows,ledger)['unknown_receipts'],1)

    def test_duplicate_receipt_no_double_charge(self):
        rows,ledger=e.run('grande');ledger.append(dict(ledger[0]))
        self.assertEqual(e.aggregate(rows,ledger)['known_mBRL'],2000)

    def test_conflicting_receipt_rejected(self):
        rows,ledger=e.run('grande');ledger.append(dict(ledger[0],amount_mBRL=999))
        with self.assertRaises(ValueError):e.aggregate(rows,ledger)

    def test_difficult_tasks_cannot_disappear(self):
        rows,ledger=e.run('barato')
        with self.assertRaises(ValueError):e.aggregate(rows[:14],ledger)

    def test_reservation_limits_pending_spend(self):
        b=e.Budget(200);self.assertTrue(b.reserve('A',140));self.assertFalse(b.reserve('B',90))
        b.settle('A',80);self.assertTrue(b.reserve('B',90))

    def test_settle_idempotent_and_conflict(self):
        b=e.Budget(200);b.reserve('A',140);b.settle('A',80);b.settle('A',80)
        self.assertEqual(b.settled,80)
        with self.assertRaises(ValueError):b.settle('A',90)

    def test_over_reservation_fails_closed(self):
        b=e.Budget(200);b.reserve('A',140)
        with self.assertRaises(ValueError):b.settle('A',150)
        self.assertEqual(b.pending['A'],140)

    def test_expired_price_rejected(self):
        self.assertFalse(e.valid_price(dict(currency='BRL',valid_from='2026-10-18',valid_to='2026-10-18'),'2026-10-19'))

    def test_quality_constraint_survives_free_review(self):
        reports={p:e.aggregate(*e.run(p,dict(e.PRICES,review=0))) for p in e.POLICIES}
        self.assertEqual(e.choose(reports),'roteado')


if __name__=='__main__':unittest.main()
