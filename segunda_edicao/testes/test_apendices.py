from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from laboratorios.apendices.core import *
from laboratorios.apendices.campaign import run

class Statistics(unittest.TestCase):
    def test_zero_not_certainty(self):
        lo,hi=wilson(0,200);self.assertAlmostEqual(lo,0);self.assertGreater(hi,.018)
    def test_all_success(self):
        lo,hi=wilson(200,200);self.assertAlmostEqual(hi,1);self.assertLess(lo,.982)
    def test_reference_interval(self):
        lo,hi=wilson(3,200);self.assertAlmostEqual(lo,.005114,places=5);self.assertAlmostEqual(hi,.043166,places=5)
    def test_invalid_counts(self):
        for k,n in [(0,0),(3,2),(-1,5),(True,5),(2,2.0)]:
            with self.assertRaises(ValueError):wilson(k,n)
    def test_zero_failure_design(self):
        self.assertEqual(zero_failure_n(.01),299)
        self.assertLessEqual(.99**299,.05);self.assertGreater(.99**298,.05)
    def test_cluster_weight(self):
        r=grouped_bootstrap({'a':[1]*100,'b':[0]});self.assertEqual(r['estimate'],.5)
    def test_cluster_determinism(self):
        g={'a':[1,0],'b':[0,0],'c':[-1,0]};self.assertEqual(grouped_bootstrap(g),grouped_bootstrap(g))
    def test_empty_group(self):
        with self.assertRaises(ValueError):grouped_bootstrap({'a':[],'b':[1]})
    def test_nonfinite(self):
        for x in [float('nan'),float('inf'),True]:
            with self.assertRaises(ValueError):finite(x)
    def test_bounds(self):
        self.assertEqual(outcome_bounds(80,10,10),dict(n=100,lower=.8,upper=.9,coverage=.9))
    def test_all_unknown(self):
        self.assertEqual(outcome_bounds(0,0,3)['upper'],1)
    def test_empty_outcomes(self):
        with self.assertRaises(ValueError):outcome_bounds(0,0,0)

class Contracts(unittest.TestCase):
    def setUp(self):
        self.row=dict(id='a',family='f',unit='hour',value=2,event_at='2026-01-01T00:00:00+00:00',
                      available_at='2026-01-01T00:01:00+00:00',predict_at='2026-01-01T00:02:00+00:00')
    def test_valid(self):self.assertEqual(validate_case(self.row),self.row)
    def test_future(self):
        self.row['available_at']='2026-01-02T00:00:00+00:00'
        with self.assertRaises(ValueError):validate_case(self.row)
    def test_timezone(self):
        self.row['event_at']='2026-01-01T00:00:00'
        with self.assertRaises(ValueError):validate_case(self.row)
    def test_unit(self):
        self.row['unit']='minute'
        with self.assertRaises(ValueError):validate_case(self.row)
    def test_retry_after_reopen(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'db';a=Receipts(p);r=a.commit('x',{'n':1});a.close()
            b=Receipts(p);self.assertEqual(r,b.commit('x',{'n':1}));self.assertEqual(b.db.execute('SELECT COUNT(*) FROM effects').fetchone()[0],1);b.close()
    def test_conflict(self):
        with TemporaryDirectory() as d:
            a=Receipts(Path(d)/'db');a.commit('x',{'n':1})
            with self.assertRaises(ValueError):a.commit('x',{'n':2})
            self.assertIsNotNone(a.lookup('x'));a.close()
    def test_missing_receipt(self):
        with TemporaryDirectory() as d:
            a=Receipts(Path(d)/'db');self.assertIsNone(a.lookup('unknown'));a.close()

class Operation(unittest.TestCase):
    def test_duplicate(self):
        r=reconcile(['a','b'],[dict(id='a',state='good')]*2)
        self.assertEqual((r['good'],r['unknown'],r['duplicates']),(1,1,1))
    def test_conflict(self):
        with self.assertRaises(ValueError):reconcile(['a'],[dict(id='a',state='good'),dict(id='a',state='bad')])
    def test_unexpected(self):
        with self.assertRaises(ValueError):reconcile(['a'],[dict(id='b',state='good')])
    def test_burn(self):self.assertAlmostEqual(burn(4,200,.99),2)
    def test_zero_traffic(self):
        with self.assertRaises(ValueError):burn(0,0,.99)
    def test_hold_not_reviewed(self):
        e=dict(identity_ok=True,population_ok=True,recovery_ok=True,semantic_review=None,valid_until='2026-11-01T00:00:00+00:00')
        self.assertEqual(assess(e,'2026-10-25T00:00:00+00:00')['reasons'],['semantic_review'])
    def test_expiry(self):
        e=dict(identity_ok=True,population_ok=True,recovery_ok=True,semantic_review=True,valid_until='2026-10-01T00:00:00+00:00')
        self.assertEqual(assess(e,'2026-10-25T00:00:00+00:00')['reasons'],['expired'])
    def test_zero_useful(self):self.assertIsNone(unit_cost(1,2,3,0)['per_useful'])
    def test_total_cost(self):self.assertEqual(unit_cost(20,60,10,30)['per_useful'],3)
    def test_full_campaign_no_overwrite(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'capture';r=run(p);self.assertTrue(r['receipts']['same'])
            with self.assertRaises(FileExistsError):run(p)

if __name__=='__main__':unittest.main()
