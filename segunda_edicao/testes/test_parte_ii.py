"""Contraprovas de estatística, unidades, modelos, desenho e evidência."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import copy,json,math,os,shutil,unittest
from laboratorios.parte_i.common import ROOT,save,load,seal
from laboratorios.parte_ii import l05,l07,l08,stats
from laboratorios.parte_ii.verify import verify


class StatisticalContracts(unittest.TestCase):
    def test_zero_denominator(self):
        with self.assertRaises(ValueError):stats.proportion(0,0)
    def test_boolean_count(self):
        with self.assertRaises(ValueError):stats.proportion(True,5)
    def test_negative_count(self):
        with self.assertRaises(ValueError):stats.proportion(-1,5)
    def test_more_successes_than_admitted(self):
        with self.assertRaises(ValueError):stats.proportion(6,5)
    def test_wilson_known(self):
        lo,hi=stats.wilson(5,10);self.assertAlmostEqual(lo,.2365930905,8);self.assertAlmostEqual(hi,.7634069095,8)
    def test_wilson_zero_not_zero_width(self):self.assertGreater(stats.wilson(0,30)[1],.1)
    def test_exact_zero_one_sided(self):self.assertAlmostEqual(stats.zero_upper(30),.0950338528553,10)
    def test_zero_precision_plan(self):
        n=stats.minimum_zero_sample(.01);self.assertEqual(n,299)
        self.assertLessEqual(stats.zero_upper(n),.01);self.assertGreater(stats.zero_upper(n-1),.01)
    def test_invalid_alpha(self):
        with self.assertRaises(ValueError):stats.wilson(1,10,1)
    def test_missing_bounds(self):self.assertEqual(stats.missing_bounds(80,10,10),[.8,.9])
    def test_missing_all(self):self.assertEqual(stats.missing_bounds(0,0,10),[0,1])
    def test_empty_quantile(self):
        with self.assertRaises(ValueError):stats.quantile([],.95)
    def test_nonfinite_quantile(self):
        with self.assertRaises(ValueError):stats.quantile([math.nan],.95)
    def test_quantile_interpolation(self):self.assertEqual(stats.quantile([0,10],.95),9.5)
    def test_family_estimand_not_row_mean(self):
        r=stats.bootstrap_groups([[1],[0]*9],100);self.assertEqual(r['estimate'],.5)
    def test_paired_cancellation(self):
        r=stats.bootstrap_groups([[0]*4]*5,100);self.assertEqual(r['interval'],[0,0])
    def test_empty_group(self):
        with self.assertRaises(ValueError):stats.bootstrap_groups([[1],[]])
    def test_single_group(self):
        with self.assertRaises(ValueError):stats.bootstrap_groups([[1,0]])
    def test_noninferior(self):self.assertEqual(stats.paired_decision([-.04,.1],.05),'noninferior_in_scope')
    def test_inconclusive_at_margin(self):self.assertEqual(stats.paired_decision([-.05,.1],.05),'inconclusive')
    def test_inferior(self):self.assertEqual(stats.paired_decision([-.2,-.06],.05),'inferior_in_scope')
    def test_exact_binomial(self):self.assertEqual(stats.binomial_two_sided_half(0,5),.0625)
    def test_binomial_center(self):self.assertEqual(stats.binomial_two_sided_half(5,10),1.)
    def test_unsorted_looks(self):
        with self.assertRaises(ValueError):stats.sequential(1,10,[20,10])
    def test_bonferroni_subset(self):
        rows=stats.sequential(1,100,[10,20]);self.assertTrue(all(not r['bonferroni'] or r['opportunistic'] for r in rows))
    def test_degenerate_bootstrap_not_certainty(self):
        lo,hi=stats.bounded_mean_interval([0]*20)
        self.assertLess(lo,-.05);self.assertGreater(hi,.05)
    def test_hoeffding_out_of_bounds(self):
        with self.assertRaises(ValueError):stats.bounded_mean_interval([2])
    def test_selection_max_is_data_dependent(self):
        rows=stats.selection_optimism(trials=10)
        self.assertTrue(all(r['dev_counts'][r['winner']]==max(r['dev_counts']) for r in rows))


class DataAndModels(unittest.TestCase):
    def test_catalog_ids_unique(self):
        c=l05.catalog();self.assertEqual(len(c),288);self.assertEqual(len({r['id'] for r in c}),288)
    def test_family_split_no_overlap(self):
        a,b=l05.split(l05.catalog(),'family');self.assertEqual(l05.audit_split(a,b)['family_overlap'],[])
    def test_entity_split_still_shared_families(self):
        a,b=l05.split(l05.catalog(),'entity');r=l05.audit_split(a,b)
        self.assertFalse(r['entity_overlap']);self.assertTrue(r['family_overlap'])
    def test_time_split_does_not_hide_group_overlap(self):
        a,b=l05.split(l05.catalog(),'time');r=l05.audit_split(a,b)
        self.assertLess(r['train_max_month'],r['test_min_month']);self.assertTrue(r['entity_overlap'])
    def test_duplicate_split_rejected(self):
        c=l05.catalog()
        with self.assertRaises(ValueError):l05.audit_split(c[:3],c[:3])
    def test_no_fake_human(self):
        with self.assertRaises(ValueError):l05.validate_human({'reviewer':None,'items':[]})
    def test_form_does_not_prove_independence(self):
        f={'reviewer':'teste','independence_statement':'declaração','items':[{'verdict':'adequate','reason':'teste'}]}
        self.assertFalse(l05.validate_human(f)['independence_verified'])
    def test_real_training_reduces_loss(self):
        rows=[{'x':[x,0],'y':int(x>0),'family':str(x)} for x in (-2,-1,1,2)]
        m=l07.fit(rows,'linear',80,.1,.01)
        self.assertLess(m['loss_before_updates'][-1],m['loss_before_updates'][0])
        self.assertEqual(l07.predict(m,[-2,0])['prediction'],0);self.assertEqual(l07.predict(m,[2,0])['prediction'],1)
    def test_fit_no_empty(self):
        with self.assertRaises(ValueError):l07.fit([],'linear',10,.1,.01)
    def test_unknown_candidate(self):
        with self.assertRaises(ValueError):l07.features([1,2],'guess')
    def test_nonfinite_feature(self):
        with self.assertRaises(ValueError):l07.features([math.inf,2],'linear')
    def test_inference_has_no_label_argument(self):
        m={'kind':'linear','weights':[0,1,1],'threshold':.5}
        self.assertGreater(l07.predict(m,[1,1])['probability'],.8)
    def test_schedule_balances_position(self):
        rows=l07.dataset(1,4);p={'order_seed':2,'repetitions':3,'candidates':['linear','interaction']}
        jobs=l07.schedule(rows,p)
        self.assertEqual(len(jobs),96)
        for k in p['candidates']:self.assertEqual(sum(j['candidate']==k and j['position']==0 for j in jobs),24)
    def test_inference_error_retained(self):
        rows=l07.dataset(1,1);job={'case':rows[0]['id'],'candidate':'absent','attempt':'one','position':0,'repetition':0}
        obs=l07.infer({},rows,[job]);self.assertEqual(obs[0]['status'],'error');self.assertIsNone(obs[0]['raw'])
    def test_factors_have_interaction(self):
        rows=l08.cases();jobs=l08.plan_requests(rows,2);index={c['id']:c for c in rows}
        obs=[{'request':j,'response':l08.decision(index[j['case']],j['refresh'],j['validate'])} for j in jobs]
        r=l08.analyze(rows,obs);self.assertEqual(r['interaction_difference_of_differences'],.5)
    def test_factorial_missing_cell(self):
        with self.assertRaises(ValueError):l08.analyze(l08.cases(),[])
    def test_group_exposure_total_effect(self):self.assertAlmostEqual(l08.exposure()['group']['difference'],.5)
    def test_individual_exposure_is_not_total_effect(self):self.assertLess(l08.exposure()['individual']['difference'],.5)


class Evidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.capture=Path(os.environ.get('PARTE_II_CAPTURE',ROOT/'output/parte_ii_principal_v01'))
    def test_principal_complete(self):
        r=verify(self.capture);self.assertEqual(r['L07']['unique_test_families'],80)
        self.assertEqual(r['human_review'],'pending')
    def damage(self,rel,change,reseal=True):
        with TemporaryDirectory() as t:
            d=Path(t)/'copy';shutil.copytree(self.capture,d)
            p=d/rel;obj=load(p);obj=change(obj);p.write_text(json.dumps(obj),encoding='utf-8')
            if reseal:(d/'manifesto.json').unlink();seal(d,'test',True)
            with self.assertRaises(ValueError):verify(d)
    def test_raw_hash_damage(self):self.damage('l07/observations.json',lambda a:a[:-1],False)
    def test_resealed_missing_inference(self):self.damage('l07/observations.json',lambda a:a[:-1])
    def test_resealed_duplicate_inference(self):self.damage('l07/observations.json',lambda a:[a[0]]+a[1:-1]+[a[0]])
    def test_resealed_wrong_prediction(self):
        def change(a):a[0]['raw']['prediction']=1-a[0]['raw']['prediction'];return a
        self.damage('l07/observations.json',change)
    def test_resealed_changed_test_label(self):
        def change(a):a[0]['y']=1-a[0]['y'];return a
        self.damage('l07/test.json',change)
    def test_resealed_test_warmup(self):
        def change(a):a[0]['case']='T000-R0';return a
        self.damage('l07/warmups.json',change)
    def test_resealed_missing_http(self):self.damage('l08/observations.json',lambda a:a[:-1])
    def test_resealed_changed_assignment(self):
        def change(a):a[0]['request']['refresh']=1-a[0]['request']['refresh'];return a
        self.damage('l08/observations.json',change)
    def test_resealed_fake_http_response(self):
        def change(a):a[0]['response']['allowed']=not a[0]['response']['allowed'];return a
        self.damage('l08/observations.json',change)
    def test_resealed_wrong_coverage(self):self.damage('l06/coverage.json',lambda a:a[:-1])
    def test_resealed_human_claim(self):
        def change(a):a['human_review']='completed';return a
        self.damage('l05.json',change)


if __name__=='__main__':unittest.main()
