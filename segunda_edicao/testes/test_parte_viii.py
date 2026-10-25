"""Contratos e mutações da evidência: nunca modifica a captura autoral."""
from pathlib import Path
import json,shutil,tempfile,unittest
from laboratorios.parte_viii.core import remaining,jitter,migrate,validate_backup,sha,seal,load,retry_after,Breaker
from laboratorios.parte_viii.verify import verify

ROOT=Path(__file__).resolve().parents[1]
CAP=ROOT/'output/parte_viii_principal_v02'

class Contracts(unittest.TestCase):
    def test_deadline_expired(self):self.assertEqual(remaining(3,4),0)
    def test_deadline_reserve(self):self.assertAlmostEqual(remaining(4,3,.2),.8)
    def test_jitter_bounded(self):
        for attempt in range(20):self.assertTrue(0<=jitter(attempt,29)<=.1)
    def test_jitter_reproducible(self):self.assertEqual(jitter(3,29),jitter(3,29))
    def test_jitter_negative(self):
        with self.assertRaises(ValueError):jitter(-1,29)
    def test_migrate_v1(self):self.assertEqual(migrate(dict(schema_version=1,step=2)),dict(schema_version=2,step=2,receipt=None))
    def test_migrate_v2(self):
        state=dict(schema_version=2,step=3,receipt='R');self.assertEqual(migrate(state),state)
    def test_migrate_future(self):
        with self.assertRaises(ValueError):migrate(dict(schema_version=3,step=2))
    def test_migrate_boolean(self):
        with self.assertRaises(ValueError):migrate(dict(schema_version=True,step=2))
    def test_backup_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'backup';p.write_bytes(b'valid');h=sha(p);self.assertTrue(validate_backup(p,h))
            p.write_bytes(b'changed')
            with self.assertRaises(ValueError):validate_backup(p,h)
    def test_retry_seconds(self):self.assertEqual(retry_after('2',0),2)
    def test_retry_decimal_invalid(self):self.assertEqual(retry_after('0.04',0),0)
    def test_retry_date(self):self.assertEqual(retry_after('Thu, 01 Jan 1970 00:00:10 GMT',8),2)
    def test_retry_past(self):self.assertEqual(retry_after('Thu, 01 Jan 1970 00:00:10 GMT',18),0)
    def test_retry_missing(self):self.assertEqual(retry_after(None,0),0)
    def test_breaker_reopens(self):
        b=Breaker(cooldown=1);b.finish(False,0);b.finish(False,0)
        self.assertFalse(b.admit(.5));self.assertTrue(b.admit(1));self.assertFalse(b.admit(1))
        b.finish(False,1);self.assertFalse(b.admit(1.5));self.assertTrue(b.admit(2))
    def test_breaker_closes(self):
        b=Breaker(cooldown=1);b.finish(False,0);b.finish(False,0);b.admit(1)
        b.finish(True,1);self.assertTrue(b.admit(1));self.assertIsNone(b.open_until)
    def test_author_capture(self):self.assertEqual(verify(CAP)['labs'],4)

def mutate_test(file,action):
    def test(self):
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/'copy';shutil.copytree(CAP,dest)
            p=dest/file;data=load(p);action(data)
            p.write_text(json.dumps(data),encoding='utf-8')
            (dest/'manifesto.json').unlink();seal(dest,'mutated',True)
            with self.assertRaises(ValueError):verify(dest)
    return test

MUTATIONS=[
 ('http_useful','l29/results.json',lambda d:d[0].update(useful=True)),
 ('http_attempt','l29/results.json',lambda d:d[0]['attempts'].pop()),
 ('http_count','l29/server_observation.json',lambda d:d['budget_always503'].update(calls=28)),
 ('http_effect','l29/server_observation.json',lambda d:d['budget_delay_after']['effects'].append('extra')),
 ('hedge','l29/results.json',lambda d:d[12].update(loser_cancelled=True)),
 ('breaker','l29/results.json',lambda d:d[13].update(rejected_open=0)),
 ('admission','l30/producer/result.json',lambda d:d[-1].update(admitted=True)),
 ('inflight','l30/inflight.json',lambda d:d['pending'].update(pending=0)),
 ('kill','l30/crash.json',lambda d:d.update(returncode=0)),
 ('pending','l30/after.json',lambda d:d['pending'].update(pending=1)),
 ('dlq','l30/after.json',lambda d:d.update(dead=[])),
 ('effect_lost','l30/after.json',lambda d:d['destination']['effects'].pop()),
 ('fair','l30/fairness.json',lambda d:d[1].update(first_b_position=7)),
 ('outbox','l31/uncertain.json',lambda d:d['source']['outbox'][0].update(sent=True)),
 ('inbox_hash','l31/after.json',lambda d:d['destination']['inbox'][0].update(body_hash='false')),
 ('fence','l31/after.json',lambda d:d['fencing'][1]['final'].update(value='old')),
 ('token','l31/after.json',lambda d:d['fencing'][1]['final'].update(token=1)),
 ('optimistic','l31/after.json',lambda d:d['optimistic'].update(second=1)),
 ('read','l31/after.json',lambda d:d['reads'][1].update(after=99)),
 ('restore','l32/restored_before_reconcile.json',lambda d:d['jobs'].pop()),
 ('lost','l32/after.json',lambda d:d.update(lost_before_reconcile=[])),
 ('rpo','l32/after.json',lambda d:d.update(rpo_count_before=0)),
 ('rto','l32/after.json',lambda d:d.update(rto_validated_seconds=0)),
 ('resend','l32/after.json',lambda d:d['actions'][0].update(action='resend')),
 ('rebuild','l32/rebuilt_index.json',lambda d:d.update(E0='ready')),
 ('cleanup','cleanup.json',lambda d:d[0].update(returncode=1)),
]
for name,file,action in MUTATIONS:setattr(Contracts,'test_mutation_'+name,mutate_test(file,action))

if __name__=='__main__':unittest.main()
