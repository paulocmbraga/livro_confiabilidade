import json
from pathlib import Path
import tempfile
import unittest
from laboratorios.efeitos15 import (Destination, approve, connect, digest, initialize,
    init_ledger, record, request_for, valid_receipt)
from laboratorios.piloto15 import CASES, oracle, run_case


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='l15_contract_')
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'target.sqlite'
        initialize(self.path);self.req=request_for();approve(self.path,self.req)
        self.target=Destination(self.path)

    def test_replay_preserves_effect_and_receipt(self):
        first=self.target.execute(self.req)
        second=self.target.execute(self.req)
        self.assertEqual(first,second)
        self.assertEqual(len(oracle(self.path)['effects']),1)

    def test_payload_conflict_preserves_original(self):
        self.target.execute(self.req)
        status,body,_=self.target.execute(dict(self.req,quantity=3))
        self.assertEqual((status,body['effect']),(409,'unknown'))
        self.assertEqual(oracle(self.path)['stock'][0]['available'],8)

    def test_approval_binds_payload(self):
        status,body,_=self.target.execute(dict(self.req,quantity=3))
        self.assertEqual((status,body['error']),(403,'approval_denied'))
        self.assertEqual(len(oracle(self.path)['effects']),0)

    def test_fresh_key_needs_fresh_version(self):
        self.target.execute(self.req)
        other=request_for('pedido-2','chave-2');approve(self.path,other)
        self.assertEqual(self.target.execute(other)[1]['error'],'version_conflict')

    def test_expired_tombstone_prevents_reuse(self):
        self.target.execute(self.req)
        self.target.now=150
        self.assertEqual(self.target.execute(self.req)[0],410)
        self.assertEqual(len(oracle(self.path)['effects']),1)

    def test_absent_receipt_is_observation_not_rejection(self):
        status,body=self.target.lookup(self.req['principal'],self.req['key'])
        self.assertEqual(status,404);self.assertNotIn('effect',body)

    def test_revocation_does_not_erase_historical_receipt(self):
        first=self.target.execute(self.req)[1]
        approve(self.path,self.req,revoked=True)
        self.assertEqual(self.target.execute(self.req)[1],first)
        self.assertEqual(len(oracle(self.path)['effects']),1)

    def test_unknown_receipt_is_not_accepted(self):
        reply=self.target.execute(self.req)[1]
        self.assertFalse(valid_receipt(self.req,dict(reply,key='outra')))
        self.assertFalse(valid_receipt(self.req,dict(reply,hash='errado')))
        self.assertFalse(valid_receipt(self.req,dict(reply,reservation='')))

    def test_principal_scopes_key(self):
        self.target.execute(self.req)
        other=dict(self.req,principal='outro-operador',intent='pedido-2',expected_version=1)
        approve(self.path,other)
        self.assertEqual(self.target.execute(other)[0],200)
        self.assertEqual(len(oracle(self.path)['effects']),2)

    def test_hash_is_not_intent(self):
        self.assertEqual(digest(self.req),digest(dict(reversed(list(self.req.items())))))
        self.assertNotEqual(digest(self.req),digest(dict(self.req,intent='pedido-2')))

    def test_request_expired_without_receipt_remains_unknown(self):
        self.target.now=150
        status,body,_=self.target.execute(self.req)
        self.assertEqual((status,body['effect']),(410,'unknown'))
        self.assertEqual(len(oracle(self.path)['effects']),0)

    def test_nonpositive_quantity_has_no_effect(self):
        for qty in (0,-1,True,2.5):
            with self.subTest(quantity=qty):
                self.assertEqual(self.target.execute(dict(self.req,quantity=qty))[0],400)
        self.assertEqual(len(oracle(self.path)['effects']),0)

    def test_ledger_cannot_change_identity(self):
        client=Path(self.tmp.name)/'client.sqlite'
        init_ledger(client,self.req)
        with self.assertRaises(ValueError):
            init_ledger(client,dict(self.req,key='new-key'))

    def test_late_worker_cannot_downgrade_confirmation(self):
        client=Path(self.tmp.name)/'client.sqlite';init_ledger(client,self.req)
        receipt=self.target.execute(self.req)[1]
        record(client,self.req['intent'],'confirmed','ok',receipt)
        record(client,self.req['intent'],'unknown','late_timeout')
        with connect(client) as db:
            row=db.execute('SELECT * FROM operations').fetchone()
            self.assertEqual(row['state'],'confirmed')
            self.assertEqual(json.loads(row['receipt']),receipt)

    def test_compensation_is_idempotent_new_effect(self):
        original=self.target.execute(self.req)[1]
        release=request_for('reparacao','chave-comp')
        release.update(action='release',reservation=original['reservation'])
        approve(self.path,release)
        self.assertEqual(self.target.execute(release)[0],200)
        self.assertEqual(self.target.execute(release)[0],200)
        snapshot=oracle(self.path)
        self.assertEqual(len(snapshot['effects']),2)
        self.assertEqual(snapshot['stock'][0]['available'],10)
        self.assertEqual(self.target.lookup(self.req['principal'],self.req['key'])[1],original)


class ProcessTests(unittest.TestCase):
    """Cada teste usa processos HTTP/worker e bancos novos, sem serviços externos."""


def scenario_test(case):
    def test(self):
        with tempfile.TemporaryDirectory(prefix='l15_process_') as tmp:
            row,events=run_case(Path(tmp)/case[0],case)
            self.assertTrue(row['passed']);self.assertTrue(events)
            if case[1]=='baseline':self.assertEqual(row['duplicates'],1)
            else:self.assertEqual(row['duplicates'],0)
    return test


for case in CASES:
    setattr(ProcessTests,'test_'+case[0]+'_'+case[1],scenario_test(case))


if __name__=='__main__':unittest.main()
