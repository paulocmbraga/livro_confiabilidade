"""Testes de fronteiras, transações, mutações e controles da Parte X."""
from pathlib import Path
from contextlib import closing
import copy,math,sqlite3,tempfile,unittest,shutil,json
from laboratorios.parte_x.core import *
from laboratorios.parte_x.service import Store
ROOT=Path(__file__).resolve().parents[1]


class Learning(unittest.TestCase):
    def test_fit_separable(self):
        rows=[{'x':i,'y':int(i>2)} for i in range(6)];m=fit(rows)
        self.assertEqual([predict(m,r['x']) for r in rows],[r['y'] for r in rows])
    def test_empty_train(self):
        with self.assertRaises(ValueError):fit([])
    def test_tie_deterministic(self):self.assertEqual(fit([{'x':0,'y':0}]),fit([{'x':0,'y':0}]))
    def test_nonfinite(self):
        for x in [math.inf,math.nan]:
            with self.assertRaises(ValueError):predict({'threshold':0},x)
    def test_equality_boundary(self):self.assertEqual(predict({'threshold':0},0),0)
    def test_delayed_label(self):
        r=dict(arrives=2,revised_at=10,provisional=0,y=1)
        self.assertIsNone(label_at(r,1));self.assertEqual(label_at(r,2),0);self.assertEqual(label_at(r,10),1)
    def test_immature_excluded(self):self.assertEqual(mature([{'cohort':5}],10)['n'],0)
    def test_mature_missing_denominator(self):
        r=dict(cohort=0,arrives=100,revised_at=100,provisional=1,y=1,prediction=1)
        self.assertEqual(mature([r],11)['n'],1);self.assertEqual(mature([r],11)['coverage'],0)
    def test_cutoff_exclusive(self):self.assertEqual(mature([{'cohort':1}],11)['n'],0)
    def test_critical_gate(self):
        rows=[dict(correct=True,critical=False)]*99+[dict(correct=False,critical=True)]
        self.assertFalse(release_gate(rows)['pass'])
    def test_no_canary_sample(self):self.assertFalse(release_gate([])['pass'])


class Durable(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db.sqlite';self.s=Store(self.path)
    def tearDown(self):self.tmp.cleanup()
    def call(self,p,d=None):return self.s.call(p,d or {})
    def admit(self,id='a'):return self.call('/admit',dict(id=id,amount=100))
    def test_integer_money(self):self.assertEqual(self.call('/admit',dict(id='a',amount=True))[0],400)
    def test_admission_idempotent(self):self.admit();self.assertEqual(self.admit()[0],200)
    def test_identity_conflict(self):self.admit();self.assertEqual(self.call('/admit',dict(id='a',amount=200))[0],409)
    def test_shadow_cannot_write(self):self.admit();self.assertEqual(self.call('/effect',dict(id='a',capability='shadow'))[0],403)
    def test_hold_blocks_active(self):
        self.admit();self.call('/mode',{'mode':'hold'});self.assertEqual(self.call('/effect',dict(id='a',capability='active'))[0],423)
    def test_effect_once(self):
        self.admit();self.call('/effect',dict(id='a',capability='active'));self.call('/effect',dict(id='a',capability='active'))
        self.assertEqual(len(self.call('/state')[1]['effects']),1)
    def test_existing_receipt_not_cancelled(self):
        self.admit();self.call('/effect',dict(id='a',capability='active'));self.assertEqual(self.call('/resolve',dict(id='a',decision='cancel'))[0],409)
    def test_missing_receipt_not_done(self):self.admit();self.assertEqual(self.call('/resolve',dict(id='a'))[0],409)
    def test_capacity(self):
        self.call('/mode',{'mode':'hold'})
        self.assertEqual([self.admit(str(i))[0] for i in range(4)],[201,201,201,429])
    def test_priority(self):
        self.call('/mode',{'mode':'hold'});self.admit('a');self.call('/admit',dict(id='b',amount=10,priority=2))
        self.assertEqual(self.call('/next_review')[1]['id'],'b')
    def test_hold_survives_restart(self):
        self.call('/mode',{'mode':'hold'});self.s=Store(self.path);self.assertEqual(self.call('/state')[1]['config']['mode'],'hold')
    def test_early_return(self):self.admit();self.assertEqual(self.call('/mode',{'mode':'auto'})[0],409)
    def test_return_needs_retest(self):self.call('/mode',{'mode':'hold'});self.assertEqual(self.call('/mode',{'mode':'auto'})[0],409)
    def test_open_migration_blocked(self):self.admit();self.assertEqual(self.call('/migrate')[0],409)
    def test_reader_compatibility(self):
        self.admit();self.call('/resolve',dict(id='a',decision='cancel'));self.call('/migrate')
        self.assertEqual(self.call('/read',dict(id='a',supported=[1]))[0],409)
        self.assertEqual(self.call('/read',dict(id='a',supported=[1,2]))[1]['amount'],100)
    def test_drain_admission(self):self.call('/drain');self.assertEqual(self.admit()[0],503)
    def test_archive_requires_drain(self):self.assertEqual(self.call('/archive',{'dependencies_closed':True})[0],409)
    def test_archive_open_obligation(self):self.admit();self.call('/drain');self.assertEqual(self.call('/archive',{'dependencies_closed':True})[0],409)
    def test_archive_requires_dependencies(self):self.call('/drain');self.assertEqual(self.call('/archive',{'dependencies_closed':False})[0],409)
    def test_archive_read_only(self):
        self.admit();self.call('/effect',dict(id='a',capability='active'));self.call('/resolve',dict(id='a'));self.call('/drain')
        self.call('/archive',{'dependencies_closed':True})
        self.assertEqual(self.call('/effect',dict(id='a',capability='active'))[0],423)
        self.assertEqual(self.call('/read',dict(id='a',supported=[1]))[0],200)


class Evidence(unittest.TestCase):
    def setUp(self):
        self.context={k:'v1' for k in CONTEXT_FIELDS}
        self.body=dict(**self.context,issued=0,expires=20,assumption_expires=20,observed_claim='C',outcome='passed',unresolved=0)
    def check(self,body,now=10):return assess('C',dict(body=body,digest=digest(body)),self.context,now)
    def test_valid(self):self.assertTrue(self.check(self.body)['supported'])
    def test_hash_not_relevance(self):
        for field in CONTEXT_FIELDS:
            with self.subTest(field=field):self.assertFalse(self.check({**self.body,field:'v2'})['supported'])
    def test_expiry_boundary(self):self.assertFalse(self.check(self.body,20)['supported'])
    def test_future_evidence(self):self.assertFalse(self.check({**self.body,'issued':11})['supported'])
    def test_expired_assumption(self):self.assertFalse(self.check({**self.body,'assumption_expires':10})['supported'])
    def test_pending_obligation(self):self.assertFalse(self.check({**self.body,'unresolved':1})['supported'])
    def test_failed_test(self):self.assertFalse(self.check({**self.body,'outcome':'failed'})['supported'])
    def test_corrupted_hash(self):self.assertFalse(assess('C',dict(body=self.body,digest='bad'),self.context,10)['supported'])
    def test_no_humans(self):self.assertEqual(human_results([])['status'],'pending')
    def test_synthetic_not_human(self):
        rows=[dict(role=r,participant_id=str(i),source='fixture',consent=True,evidence_ids=['E1'],decision='hold',started=0,decided=1)
              for i,r in enumerate(['coordenacao','operacao'])]
        with self.assertRaises(ValueError):human_results(rows)
    def test_duplicate_participants(self):
        rows=[dict(role=r,participant_id='same',source='human',consent=True,evidence_ids=['E1'],decision='hold',started=0,decided=1)
              for r in ['coordenacao','operacao']]
        with self.assertRaises(ValueError):human_results(rows)


class CaptureMutation(unittest.TestCase):
    def setUp(self):
        from laboratorios.parte_x.verify import verify
        self.verify=verify;self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'capture'
        shutil.copytree(ROOT/'output/parte_x_engenharia_v01',self.path)
    def tearDown(self):self.tmp.cleanup()
    def mutate(self,rel,change):
        p=self.path/rel;data=load(p);change(data);p.write_text(json.dumps(data),encoding='utf-8')
        # Recalcula apenas o manifesto da cópia para exigir verificação relacional.
        manifest=load(self.path/'manifesto.json');manifest['files'][rel]=sha(p)
        (self.path/'manifesto.json').write_text(json.dumps(manifest),encoding='utf-8')
    def test_wrong_prediction_resealed(self):
        self.mutate('l37/events.json',lambda d:d[0].update(prediction=1-d[0]['prediction']))
        with self.assertRaises(AssertionError):self.verify(self.path)
    def test_unreported_canary_resealed(self):
        self.mutate('l38/exposure.json',lambda d:d[19].update(candidate=True))
        with self.assertRaises(AssertionError):self.verify(self.path)
    def test_human_form_fabrication_resealed(self):
        self.mutate('l39/human/operacao/form.json',lambda d:d.update(decision='return'))
        with self.assertRaises(AssertionError):self.verify(self.path)
    def test_false_supported_claim_resealed(self):
        self.mutate('l40/cases.json',lambda d:d[1]['decision'].update(supported=True))
        with self.assertRaises(AssertionError):self.verify(self.path)


if __name__=='__main__':unittest.main()
