"""Mechanism checks, independent examples and resealed-capture counterproofs."""
import copy,itertools,json,math,tempfile,unittest
from pathlib import Path
from laboratorios.parte_i.common import ROOT,digest,load,seal
from laboratorios.parte_iv.core import *
from laboratorios.parte_iv.calibration import *
from laboratorios.parte_iv.verify import verify

class DataTests(unittest.TestCase):
    def setUp(self):self.rows=generate(80,3,'unit');self.prep=preprocessor(self.rows);self.row=self.rows[0]
    def test_reproducible_generator(self):self.assertEqual(self.rows,generate(80,3,'unit'))
    def test_unique_entities(self):self.assertEqual(len({r['id'] for r in self.rows}),80)
    def test_preprocessor_training_only(self):self.assertEqual(self.prep['fit_ids'],digest([r['id'] for r in self.rows]))
    def test_asof_excludes_late_correction(self):self.assertEqual(asof(self.row)['id'],'initial')
    def test_future_reaches_outcome(self):self.assertEqual(asof(self.row,True)['id'],'outcome')
    def test_missing_point_in_time(self):
        r=copy.deepcopy(self.row);r['at']=-100
        with self.assertRaisesRegex(ValueError,'no_feature'):asof(r)
    def test_unit_guard(self):
        r=dict(self.row,unit='minute')
        with self.assertRaisesRegex(ValueError,'unit'):features(r,self.prep)
    def test_unknown_category(self):
        with self.assertRaisesRegex(ValueError,'category'):features(dict(self.row,channel='chat'),self.prep)
    def test_missing_uses_frozen_median(self):
        x=features(dict(self.row,age=None),self.prep);self.assertEqual(x[1],self.prep['median_age']/24);self.assertEqual(x[-1],1)
    def test_nan_rejected(self):
        with self.assertRaises(ValueError):features(dict(self.row,age=float('nan')),self.prep)
    def test_infinite_rejected(self):
        with self.assertRaises(ValueError):features(dict(self.row,age=float('inf')),self.prep)
    def test_bool_rejected(self):
        with self.assertRaises(ValueError):features(dict(self.row,age=True),self.prep)
    def test_negative_rejected(self):
        with self.assertRaises(ValueError):features(dict(self.row,age=-1),self.prep)
    def test_schema_identity(self):
        p=copy.deepcopy(self.prep);p['schema']['version']='v2'
        with self.assertRaises(ValueError):features(self.row,p)
    def test_target_not_required(self):
        row=copy.deepcopy(self.row);row.pop('y');row.pop('label_available')
        self.assertEqual(features(row,self.prep),features(self.row,self.prep))
    def test_group_guard(self):
        with self.assertRaises(ValueError):features(dict(self.row,group='unknown'),self.prep)
    def test_queue_type(self):
        r=copy.deepcopy(self.row);r['history'][0]['queue']=3.2
        with self.assertRaises(ValueError):features(r,self.prep)

class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=generate(80,5,'train');cls.prep=preprocessor(cls.rows)
        cls.model=fit(cls.rows,cls.prep,epochs=15)
    def test_gradient_finite_difference(self):
        x=[1,2,-1];w=[.3,-.2,.1];y=1;eps=1e-6
        def loss(v):p=sigmoid(sum(a*b for a,b in zip(v,x)));return -math.log(p)
        for k in range(3):
            a=w.copy();b=w.copy();a[k]+=eps;b[k]-=eps
            analytical=(sigmoid(sum(a*b for a,b in zip(w,x)))-y)*x[k]
            self.assertAlmostEqual((loss(a)-loss(b))/(2*eps),analytical,places=7)
    def test_training_changed_weights(self):self.assertGreater(max(map(abs,self.model['weights'])),.1)
    def test_same_seed_exact_weights_here(self):self.assertEqual(self.model['weights'],fit(self.rows,self.prep,epochs=15)['weights'])
    def test_distinct_seed(self):self.assertNotEqual(self.model['weights'],fit(self.rows,self.prep,seed=14,epochs=15)['weights'])
    def test_trace_finite(self):self.assertTrue(all(math.isfinite(v) for v in self.model['history_brier']))
    def test_all_predictions(self):self.assertEqual(len(predictions(self.model,self.rows)),80)
    def test_swapped_weights_rejected(self):
        model=copy.deepcopy(self.model);model['weights'][0]+=.1
        with self.assertRaisesRegex(ValueError,'artifact'):promote(model,identity(self.model),['train'])
    def test_test_access_rejected(self):
        with self.assertRaisesRegex(ValueError,'contamination'):promote(self.model,identity(self.model),['test'])
    def test_calibration_access_not_training_registration(self):
        with self.assertRaises(ValueError):promote(self.model,identity(self.model),['probcal'])
    def test_registration_not_release(self):self.assertFalse(promote(self.model,identity(self.model),['train','tune'])['operational_release'])
    def test_timing_not_model_identity(self):
        m=copy.deepcopy(self.model);m['seconds']+=9;self.assertEqual(identity(m),identity(self.model))
    def test_preprocessing_is_model_identity(self):
        m=copy.deepcopy(self.model);m['prep']['median_age']+=1;self.assertNotEqual(identity(m),identity(self.model))
    def test_empty_fit(self):
        with self.assertRaises(ValueError):fit([],self.prep)
    def test_independent_probability(self):
        m=copy.deepcopy(self.model);m['weights']=[math.log(3),0,0,0,0,0,0]
        self.assertAlmostEqual(predict(m,self.rows[0])['p'],.75)

class StatisticsTests(unittest.TestCase):
    def setUp(self):self.rows=[{'id':str(i),'y':v,'group':'vip'} for i,v in enumerate([0,1,0,1])];self.out=[{'id':str(i),'p':p,'group':'vip'} for i,p in enumerate([.1,.9,.2,.8])]
    def test_brier_hand(self):self.assertAlmostEqual(metrics(self.rows,self.out)['brier'],.025)
    def test_logloss_hand(self):self.assertAlmostEqual(metrics(self.rows,self.out)['log_loss'],(-math.log(.9)-math.log(.8))/2)
    def test_auc_perfect(self):self.assertEqual(auc([0,1],[.1,.9]),1)
    def test_auc_tie(self):self.assertEqual(auc([0,1],[.5,.5]),.5)
    def test_auc_undefined(self):self.assertIsNone(auc([1,1],[.1,.9]))
    def test_empty_metrics(self):self.assertIsNone(metrics([],[])['error'])
    def test_reordered_ids(self):
        with self.assertRaises(ValueError):metrics(self.rows,list(reversed(self.out)))
    def test_invalid_probability(self):
        out=copy.deepcopy(self.out);out[0]['p']=2
        with self.assertRaises(ValueError):metrics(self.rows,out)
    def test_zero_n_interval(self):self.assertIsNone(wilson(0,0))
    def test_zero_failures_upper_nonzero(self):self.assertGreater(wilson(0,30)[1],.1)
    def test_rank_finite_correction(self):self.assertEqual(quantile([.1,.2,.3,.4],.2),{'n':4,'rank':4,'q':.4,'alpha':.2})
    def test_rank_above_n_full_set(self):self.assertEqual(label_set(.99,quantile([.1],.1)['q']),[0,1])
    def test_empty_conformal(self):
        with self.assertRaises(ValueError):quantile([],.1)
    def test_invalid_alpha(self):
        with self.assertRaises(ValueError):quantile([.1],0)
    def test_boundary_included(self):self.assertEqual(label_set(.8,.2),[1])
    def test_empty_set_possible(self):self.assertEqual(label_set(.5,.1),[])
    def test_full_set_coverage(self):self.assertEqual(coverage(self.out,self.rows,{'q':1})['all']['coverage'],1)
    def test_no_acceptance_is_undefined_risk(self):self.assertIsNone(selective(self.out,self.rows,1)['risk'])
    def test_abstention_cost_all(self):self.assertAlmostEqual(selective(self.out,self.rows,1)['cost_per_admission'],.2)
    def test_selective_denominator(self):self.assertEqual(selective(self.out,self.rows,.85)['accepted'],2)
    def test_reliability_reconciles(self):self.assertEqual(sum(x['n'] for x in reliability(self.out,self.rows)),4)
    def test_calibrator_positive(self):self.assertGreater(fit_calibrator(self.out,self.rows)['a'],0)
    def test_calibration_identity(self):
        with self.assertRaises(ValueError):fit_calibrator(self.out,self.rows[::-1])
    def test_conformal_rank_enumeration(self):
        # All 5 possible ranks of held-out distinct score, 4 calibration values.
        covered=[]
        for held in range(5):
            values=[i/5 for i in range(5)];s=values.pop(held);covered.append(s<=quantile(values,.2)['q'])
        self.assertEqual(sum(covered)/len(covered),.8)

class CaptureTests(unittest.TestCase):
    capture=ROOT/'output/parte_iv_principal_v01'
    def test_full_capture(self):
        if not self.capture.exists():self.skipTest('capture not produced yet')
        self.assertEqual(verify(self.capture)['http'],240)

def mutation_test(filename,mutate):
    def test(self):
        if not self.capture.exists():self.skipTest('capture not produced yet')
        import shutil
        with tempfile.TemporaryDirectory() as folder:
            dest=Path(folder)/'capture';shutil.copytree(self.capture,dest)
            path=dest/filename;obj=load(path);mutate(obj);path.write_text(json.dumps(obj),encoding='utf-8')
            (dest/'manifesto.json').unlink();seal(dest,'mutated_but_resealed')
            with self.assertRaises((ValueError,AssertionError,KeyError)):verify(dest)
    return test

for name,file,mut in [
    ('lost_http','http_observed.json',lambda a:a.pop()),
    ('changed_probability','test_predictions.json',lambda a:a[next(iter(a))][0].update(p=.12345)),
    ('changed_weight','models.json',lambda a:a[next(iter(a))]['weights'].__setitem__(0,99)),
    ('duplicate_entity','data.json',lambda a:a['test'][0].update(id=a['train'][0]['id'])),
    ('future_partition','data.json',lambda a:a['train'][0].update(label_available=999999)),
    ('selected_seed','selection.json',lambda a:a.update(key='l2_0.001_seed_17')),
    ('wrong_quantile','calibration.json',lambda a:a['conformal'].update(q=.001)),
    ('stolen_calibration','calibration.json',lambda a:a['calibrator']['ids'].__setitem__(0,'test-0000')),
    ('mutated_aggregate','results.json',lambda a:a['L13']['correct'].update(rejected=999)),
    ('same_process','processes.json',lambda a:a.update(parent_pid=a['server_pid'])),
    ('lost_retention','interventions.json',lambda a:a['retention']['adapted'].pop()),
    ('false_promotion','promotion.json',lambda a:a['attacks'].update(swapped='NOT_REJECTED'))]:
    setattr(CaptureTests,'test_'+name,mutation_test(file,mut))

if __name__=='__main__':unittest.main()
