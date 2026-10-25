"""Contraprovas de contratos, álgebra, estado e evidência adulterada."""
from pathlib import Path
from contextlib import closing
import copy,json,math,shutil,sqlite3,tempfile,unittest
from unittest.mock import patch
from laboratorios.parte_i.common import ROOT,load,save,sha,check_manifest,seal
from laboratorios.parte_i import l01,l02,l03,l04
from laboratorios.parte_i.verify import verify,verify_workers,verify_service

M=ROOT/'materiais/parte_i'
CAP=ROOT/'output/parte_i_principal_v01'
if not CAP.exists():CAP=ROOT/'output/parte_i_engenharia_v01'

class TaskContract(unittest.TestCase):
    def case(self,n):return copy.deepcopy(load(M/'l01_cases.json')[n-1])
    def test_all_admissions_reconciled(self):
        r=l01.summarize(load(M/'l01_cases.json'));self.assertEqual(sum(r['states'].values()),12)
    def test_success_with_lost_ack(self):
        r=l01.assess(self.case(9));self.assertEqual((r['state'],r['client_state']),('success','unknown'))
    def test_correct_refusal_not_success(self):self.assertEqual(l01.assess(self.case(5))['state'],'abstained')
    def test_wrong_refusal_failure(self):self.assertEqual(l01.assess(self.case(6))['state'],'failure')
    def test_pending_not_removed(self):self.assertEqual(l01.assess(self.case(7))['state'],'pending')
    def test_unknown_not_zero_effect(self):self.assertEqual(l01.assess(self.case(8))['state'],'unknown')
    def test_foreign_effect_overrides_fluent_text(self):self.assertEqual(l01.assess(self.case(3))['violations'],['foreign_effect'])
    def test_duplicate_critical(self):self.assertIn('duplicate',l01.assess(self.case(4))['violations'])
    def test_no_authority(self):self.assertIn('unauthorized_effect',l01.assess(self.case(12))['violations'])
    def test_unsupported_text(self):self.assertEqual(l01.assess(self.case(10))['state'],'failure')
    def test_late_effect(self):self.assertEqual(l01.assess(self.case(11))['state'],'failure')
    def test_http_success_is_wrong_in_seven(self):self.assertEqual(l01.summarize(load(M/'l01_cases.json'))['false_success'],7)
    def test_duplicate_admission_rejected(self):
        with self.assertRaises(ValueError):l01.summarize([self.case(1),self.case(1)])

class Composition(unittest.TestCase):
    def test_zero_failure(self):self.assertEqual(l02.analytic(0,0)['series'],1)
    def test_certain_common_failure(self):self.assertEqual(l02.analytic(1,.1)['series'],0)
    def test_certain_local_failure(self):self.assertEqual(l02.analytic(0,1)['series'],0)
    def test_bad_probability(self):
        for q in (-.01,1.01,float('nan')):
            with self.assertRaises(ValueError):l02.analytic(q,.1)
    def test_empty_simulation_refused(self):
        with self.assertRaises(ValueError):l02.simulate(0,.1,0,1)
    def test_independent_product(self):
        a=l02.analytic(0,.02);self.assertAlmostEqual(a['series'],a['naive_series'])
    def test_correlated_series_direction(self):
        a=l02.analytic(.1,.02);self.assertGreater(a['series'],a['naive_series'])
    def test_correlated_parallel_direction(self):
        a=l02.analytic(.1,.02);self.assertGreater(a['parallel_failure'],a['naive_parallel_failure'])
    def test_partition_paths(self):
        a=l02.analytic(.1,.02);self.assertAlmostEqual(a['series']+a['common_path']+a['local_path'],1)
    def test_enumeration_all_extremes(self):
        for q in (0,.1,1):
            for r in (0,.02,1):
                rows=l02.enumerate_states(q,r)
                self.assertEqual(len(rows),16);self.assertAlmostEqual(sum(x['probability'] for x in rows),1)
                self.assertAlmostEqual(sum(x['probability'] for x in rows if x['series']),l02.analytic(q,r)['series'])
    def test_seeded_replay(self):self.assertEqual(l02.simulate(.1,.02,1000,3),l02.simulate(.1,.02,1000,3))
    def test_simulation_denominator(self):
        c=l02.simulate(.1,.02,1000,3)['counts'];self.assertEqual(c['success']+c['common']+c['local'],1000)

class Consumer(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'state.sqlite';l03.initialize(self.db)
        self.case=copy.deepcopy(load(M/'l03_cases.json')[0])
    def tearDown(self):self.tmp.cleanup()
    def apply(self,c=None,mode='protected',up=True):
        with patch.object(l03,'request',return_value=(200 if up else 503,{})):
            return l03.apply(self.db,mode,c or self.case,'fixture://collector')
    def test_atomic_effect_and_audit(self):
        self.assertEqual(self.apply()[0],200);o=l03.observe(self.db)
        self.assertEqual(len(o['effects']),1);self.assertEqual(len(o['audit']),1)
    def test_boolean_is_not_amount(self):
        self.case['proposal']['cents']=True;self.assertEqual(self.apply()[0],422)
    def test_negative_rejected(self):
        self.case['proposal']['cents']=-1;self.assertEqual(self.apply()[0],422)
    def test_limit_rejected(self):
        self.case['proposal']['cents']=5001;self.assertEqual(self.apply()[0],422)
    def test_unknown_field_rejected(self):
        self.case['proposal']['skip_validation']=True;self.assertEqual(self.apply()[0],422)
    def test_foreign_tenant_rejected(self):
        self.case['proposal']['tenant']='b';self.assertEqual(self.apply()[0],422)
    def test_stale_revision_rejected(self):
        self.case['proposal']['revision']=3;self.assertEqual(self.apply()[0],422)
    def test_authority_not_in_model(self):
        self.case['context']['authorized']=False;self.assertEqual(self.apply()[0],422)
    def test_optional_failure_preserves_effect(self):self.assertEqual(self.apply(up=False)[0],200)
    def test_required_failure_blocks_effect(self):
        self.case['audit_required_online']=True;self.assertEqual(self.apply(up=False)[0],503)
        self.assertEqual(l03.observe(self.db)['effects'],[])
    def test_capacity_uses_persisted_count(self):
        self.case['buffer_capacity']=1;self.assertEqual(self.apply()[0],200)
        self.case['id']='second';self.assertEqual(self.apply()[0],503)
        self.assertEqual(len(l03.observe(self.db)['effects']),1)
    def test_audit_insert_failure_rolls_back_effect(self):
        with closing(sqlite3.connect(self.db)) as c, c:c.execute("CREATE TRIGGER reject_audit BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.apply()
        self.assertEqual(l03.observe(self.db)['effects'],[])
    def test_duplicate_no_second_effect(self):
        self.apply();self.assertEqual(self.apply()[0],409);self.assertEqual(len(l03.observe(self.db)['effects']),1)
    def test_naive_control_propagates_bad_target(self):
        self.case['proposal']['tenant']='b';self.assertEqual(self.apply(mode='naive')[0],200)
        self.assertEqual(l03.observe(self.db)['effects'][0][1],'b')
    def test_naive_depends_on_optional(self):self.assertEqual(self.apply(mode='naive',up=False)[0],503)

class Evidence(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'capture'
        shutil.copytree(CAP/'l04',self.root);self.data=load(self.root/'observed.json')['data']
    def tearDown(self):self.tmp.cleanup()
    def test_final_reconciled(self):self.assertEqual(l04.reconcile(self.data,self.root)['attempts'],8)
    def test_partial_refused(self):
        with self.assertRaises(ValueError):l04.reconcile(load(self.root/'partial/observed.json')['data'],self.root/'partial')
    def test_missing_raw_refused(self):
        (self.root/'attempts/C01-a1/raw.json').unlink()
        with self.assertRaises(FileNotFoundError):l04.reconcile(self.data,self.root)
    def test_rehashed_wrong_value_refused(self):
        p=self.root/'attempts/C01-a1/raw.json';raw=load(p);raw['value']=999;p.unlink();save(p,raw)
        next(x for x in self.data['results'] if x['attempt_id']=='C01-a1')['sha256']=sha(p)
        with self.assertRaisesRegex(ValueError,'Quadrado'):l04.reconcile(self.data,self.root)
    def test_swapped_input_hash(self):
        p=self.root/'attempts/C01-a1/raw.json';raw=load(p);raw['input_hash']='0'*64;p.unlink();save(p,raw)
        next(x for x in self.data['results'] if x['attempt_id']=='C01-a1')['sha256']=sha(p)
        with self.assertRaisesRegex(ValueError,'Entrada'):l04.reconcile(self.data,self.root)
    def test_result_without_attempt(self):
        self.data['attempts'].pop()
        with self.assertRaises(ValueError):l04.reconcile(self.data,self.root)
    def test_missing_event(self):
        self.data['events'].pop(1)
        with self.assertRaisesRegex(ValueError,'Lacuna'):l04.reconcile(self.data,self.root)
    def test_duplicate_results(self):
        self.data['results'].append(self.data['results'][0])
        with self.assertRaises(ValueError):l04.reconcile(self.data,self.root)
    def test_missing_first_attempt(self):
        self.data['attempts']=[a for a in self.data['attempts'] if a['id']!='C02-a1']
        self.data['results']=[a for a in self.data['results'] if a['attempt_id']!='C02-a1']
        with self.assertRaisesRegex(ValueError,'Sequência'):l04.reconcile(self.data,self.root)
    def test_bad_terminal_state(self):
        self.data['results'][0]['state']='discarded'
        with self.assertRaises(ValueError):l04.reconcile(self.data,self.root)
    def test_manifest_extra_file(self):
        save(self.root/'partial/extra.json',{})
        with self.assertRaises(ValueError):check_manifest(self.root/'partial')
    def test_manifest_tampered_file(self):
        p=self.root/'partial/plan.json';p.write_bytes(b'{}')
        with self.assertRaises(ValueError):check_manifest(self.root/'partial')
    def test_refuse_overwrite(self):
        with self.assertRaises(FileExistsError):save(self.root/'observed.json',{})
    def test_complete_campaign(self):
        result=verify(CAP);self.assertEqual(result['L03']['protected']['domain_violations'],0)
        self.assertEqual(result['L04']['final']['tasks'],{'success':5,'failed':1,'pending':0})
    def test_observer_different_process(self):
        rows=load(CAP/'l03/requests.json')
        for r in rows:self.assertNotEqual(r['service_pid'],load(CAP/'l03'/r['observation'])['observer_pid'])

if __name__=='__main__':unittest.main()
