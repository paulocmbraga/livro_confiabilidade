"""Oráculos pequenos, fronteiras de autoridade e corrupção relacional."""
from pathlib import Path
import copy,json,tempfile,unittest,shutil
from laboratorios.parte_xi.core import *
from laboratorios.parte_xi.protocol import Ledger
from laboratorios.parte_xi.verify import verify
from laboratorios.parte_iv import core as ml
from laboratorios.parte_iv.calibration import fit_calibrator,calibrate
ROOT=Path(__file__).resolve().parents[1]

class Contracts(unittest.TestCase):
    def test_bm25_families(self):
        for v in ('v1','v2'):
            for d in corpus(v):self.assertEqual(retrieve(corpus(v),d['family'])[0]['document'],d)
    def test_tie_deterministic(self):
        found=retrieve(corpus('v1'),'inexistente');self.assertEqual([r['document']['id'] for r in found],sorted(r['document']['id'] for r in found))
    def test_revocation(self):self.assertTrue(all(a['limit']>b['limit'] for a,b in zip(corpus('v1'),corpus('v2'))))
    def test_bad_corpus(self):
        with self.assertRaises(ValueError):corpus('latest')
    def test_old_cache(self):self.assertFalse(bound(dict(corpus='v2',index='v2',cache='v1',prompt='v2'),'v2'))
    def test_old_index(self):self.assertFalse(bound(dict(corpus='v2',index='v1',cache='v2',prompt='v2'),'v2'))
    def test_revoked_snapshot(self):self.assertFalse(bound(dict.fromkeys(['corpus','index','cache','prompt'],'v1'),'v2'))
    def test_current_snapshot(self):self.assertTrue(bound(dict.fromkeys(['corpus','index','cache','prompt'],'v2'),'v2'))
    def test_signal_not_bool(self):self.assertFalse(answer_signal('{"limite":true,"fonte":"x"}',dict(limit=1,id='x')))
    def test_signal_wrong_source(self):self.assertFalse(answer_signal('{"limite":120,"fonte":"old"}',dict(limit=120,id='new')))
    def test_truncated(self):self.assertIsNone(parse('{"limite":'))
    def test_out_of_authority(self):self.assertFalse(proposal('{"action":"reserve","quantity":2}',dict(quantity=2,authorized=True))['accepted'])
    def test_no_auth(self):self.assertFalse(proposal('{"action":"reserve","quantity":1}',dict(quantity=1,authorized=False))['accepted'])
    def test_exact_proposal(self):self.assertTrue(proposal('{"action":"reserve","quantity":1}',dict(quantity=1,authorized=True))['accepted'])
    def test_hold(self):self.assertFalse(proposal('{"action":"hold","quantity":1}',dict(quantity=1,authorized=True))['accepted'])
    def test_cost(self):self.assertEqual(cost([dict(id='a',y=1),dict(id='b',y=0)],[dict(id='a',p=0),dict(id='b',p=1)])['cost'],9)
    def test_cost_binding(self):
        with self.assertRaises(ValueError):cost([dict(id='a',y=1)],[dict(id='b',p=0)])
    def test_leak_gate(self):self.assertFalse(release_gate(dict(brier=0),True,False)['allowed'])
    def test_unit_gate(self):self.assertFalse(release_gate(dict(brier=0),False,True)['allowed'])
    def test_quality_gate(self):self.assertFalse(release_gate(dict(brier=.4),True,True)['allowed'])
    def test_changed_evaluator(self):
        a=dict(data='1',model='1',judge='1',dependency='1',contract='1');self.assertEqual(evidence_reuse(a,dict(a,judge='2'))['changed'],['judge'])
    def test_available_not_event(self):
        r=ml.generate(1,1,'x')[0];self.assertEqual(ml.asof(r)['id'],'initial');self.assertEqual(ml.asof(r,True)['id'],'outcome')
    def test_unit_at_consumer(self):
        rows=ml.generate(4,1,'x');m=ml.fit(rows,ml.preprocessor(rows),epochs=1)
        with self.assertRaises(ValueError):ml.predict(m,dict(rows[0],unit='minute'))
    def test_calibration_binding(self):
        with self.assertRaises(ValueError):fit_calibrator([dict(id='a',p=.5)],[dict(id='b',y=1)])

class Destination(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db';self.db=Ledger(self.path);self.task=dict(intent='I',quantity=1,contract='v1')
    def tearDown(self):self.tmp.cleanup()
    def test_requires_prepare(self):self.assertFalse(self.db.call('reserve',self.task)['ok'])
    def test_duplicate_receipt(self):
        self.db.call('prepare',self.task);a=self.db.call('reserve',self.task);b=self.db.call('reserve',self.task);self.assertEqual(a,b);self.assertEqual(len(self.db.call('state',{})['receipts']),1)
    def test_migration_open(self):self.db.call('prepare',self.task);self.assertFalse(self.db.call('migrate',{'to':'v2'})['ok'])
    def test_ack_needs_receipt(self):self.db.call('prepare',self.task);self.assertFalse(self.db.call('ack',self.task)['ok'])
    def test_binding_quantity(self):self.db.call('prepare',self.task);self.assertFalse(self.db.call('reserve',dict(self.task,quantity=2))['ok'])
    def test_prepare_quantity(self):self.assertFalse(self.db.call('prepare',dict(self.task,quantity=2))['ok'])
    def test_prepare_conflict(self):self.db.call('prepare',self.task);self.assertFalse(self.db.call('prepare',dict(self.task,contract='v2'))['ok'])
    def test_restart_receipt(self):
        self.db.call('prepare',self.task);self.db.call('reserve',self.task);fresh=Ledger(self.path);self.assertIsNotNone(fresh.call('reconcile',self.task)['receipt'])
    def test_old_contract_after_migration(self):
        self.db.call('prepare',self.task);self.db.call('reserve',self.task);self.db.call('ack',self.task);self.db.call('migrate',{'to':'v2'});self.assertFalse(self.db.call('reserve',self.task)['ok']);self.assertIsNotNone(self.db.call('reconcile',self.task)['receipt'])
    def test_migrate_after_ack(self):
        self.db.call('prepare',self.task);self.db.call('reserve',self.task);self.db.call('ack',self.task);self.assertTrue(self.db.call('migrate',{'to':'v2'})['ok'])

class Capture(unittest.TestCase):
    def mutate(self,path,mutator):
        source=ROOT/'output/parte_xi_engenharia_v01'
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'capture';shutil.copytree(source,target)
            p=target/path;r=load(p);mutator(r);p.write_text(json.dumps(r),encoding='utf-8')
            m=load(target/'manifesto.json');m['files'][path]=sha(p);(target/'manifesto.json').write_text(json.dumps(m),encoding='utf-8')
            with self.assertRaises((AssertionError,ValueError)):verify(target)
    def test_base(self):self.assertTrue(verify(ROOT/'output/parte_xi_engenharia_v01')['complete'])
    def test_mutated_cost(self):self.mutate('l41/variants.json',lambda r:r['clean']['cost'].update(cost=99999))
    def test_mutated_exposure(self):self.mutate('l42/rows.json',lambda r:next(x for x in r if x['mode']=='race_protected').update(delivered=True))
    def test_mutated_receipt(self):self.mutate('l43/recovery.json',lambda r:r['final']['receipts'].append(r['final']['receipts'][0]))
    def test_mutated_future(self):self.mutate('l44/epoch_4/result.json',lambda r:r['rag'][0].update(delivered=True))

if __name__=='__main__':unittest.main()
