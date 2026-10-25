"""Contratos e mutações do observador, além da captura real reconciliada."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from laboratorios.l26.core import classify,digest,load,valid_request
from laboratorios.l26.verify import analyze,verify

ROOT=Path(__file__).resolve().parents[1]
CAPTURE=ROOT/'output/l26_principal_v02'


def body():
    return dict(tenant='horizonte',intent='pedido-1',key='chave-1',action='reserve',
                resource='peca-A',quantity=2,expected_version=0,expires_at=2000.0,original=None)


class ContractTests(unittest.TestCase):
    def test_canonical_order(self):
        b=body();self.assertEqual(digest(b),digest(dict(reversed(list(b.items())))))
    def test_token_is_execution_not_business(self):
        self.assertEqual(digest(body()),digest(dict(body(),token=9)))
    def test_key_is_identity_not_content(self):
        self.assertEqual(digest(body()),digest(dict(body(),key='another')))
    def test_tenant_changes_digest(self):
        self.assertNotEqual(digest(body()),digest(dict(body(),tenant='other')))
    def test_quantity_changes_digest(self):
        self.assertNotEqual(digest(body()),digest(dict(body(),quantity=3)))
    def test_deadline_changes_digest(self):
        self.assertNotEqual(digest(body()),digest(dict(body(),expires_at=2001.0)))
    def test_boolean_quantity_denied(self):self.assertFalse(valid_request(dict(body(),quantity=True)))
    def test_negative_quantity_denied(self):self.assertFalse(valid_request(dict(body(),quantity=-1)))
    def test_float_quantity_denied(self):self.assertFalse(valid_request(dict(body(),quantity=2.5)))
    def test_invalid_version_denied(self):self.assertFalse(valid_request(dict(body(),expected_version=True)))
    def test_infinite_deadline_denied(self):self.assertFalse(valid_request(dict(body(),expires_at=float('inf'))))
    def test_nan_deadline_denied(self):self.assertFalse(valid_request(dict(body(),expires_at=float('nan'))))
    def test_unknown_field_denied(self):self.assertFalse(valid_request(dict(body(),instruction='override')))
    def test_negative_fence_denied(self):self.assertFalse(valid_request(dict(body(),token=-2)))
    def test_empty_key_denied(self):self.assertFalse(valid_request(dict(body(),key='')))
    def test_valid_request(self):self.assertTrue(valid_request(body()))
    def test_missing_receipt_not_failure_proof(self):self.assertEqual(classify(body(),{}),'unknown')
    def test_forged_effect_no_hash_not_success(self):self.assertEqual(classify(body(),{'effect':'applied'}),'unknown')
    def test_foreign_receipt_not_success(self):
        b=body();r=dict(hash=digest(b),key=b['key'],tenant='other',effect='applied')
        self.assertEqual(classify(b,r),'unknown')
    def test_matching_receipt_confirms(self):
        b=body();r=dict(hash=digest(b),key=b['key'],tenant=b['tenant'],intent=b['intent'],effect='applied',action='reserve',effect_id=1)
        self.assertEqual(classify(b,r),'confirmed')
    def test_matching_negative_receipt_rejects(self):
        b=body();r=dict(hash=digest(b),key=b['key'],tenant=b['tenant'],intent=b['intent'],effect='not_applied')
        self.assertEqual(classify(b,r),'rejected')
    def test_success_requires_effect_identifier(self):
        b=body();r=dict(hash=digest(b),key=b['key'],tenant=b['tenant'],intent=b['intent'],effect='applied',action='reserve')
        self.assertEqual(classify(b,r),'unknown')
    def test_receipt_wrong_intent(self):
        b=body();r=dict(hash=digest(b),key=b['key'],tenant=b['tenant'],intent='wrong',effect='not_applied')
        self.assertEqual(classify(b,r),'unknown')


class ObserverTests(unittest.TestCase):
    def snapshot(self,case='P01'):return deepcopy(load(CAPTURE/case/'final.json'))
    def test_complete_capture(self):self.assertEqual(verify(CAPTURE)['episodes'],24)
    def test_balance_mutation(self):
        v=self.snapshot();v['destination']['stock'][0]['available']+=1
        with self.assertRaisesRegex(AssertionError,'stock_conservation'):analyze(v)
    def test_version_mutation(self):
        v=self.snapshot();v['destination']['stock'][0]['version']+=1
        with self.assertRaisesRegex(AssertionError,'version_effect_count'):analyze(v)
    def test_receipt_hash_mutation(self):
        v=self.snapshot();v['client']['jobs'][0]['receipt']['hash']='wrong'
        with self.assertRaisesRegex(AssertionError,'receipt_payload'):analyze(v)
    def test_receipt_key_mutation(self):
        v=self.snapshot();v['client']['jobs'][0]['receipt']['key']='wrong'
        with self.assertRaisesRegex(AssertionError,'receipt_key'):analyze(v)
    def test_outbox_disappeared(self):
        v=self.snapshot();v['client']['outbox']=[]
        with self.assertRaisesRegex(AssertionError,'job_without_outbox'):analyze(v)
    def test_unknown_discarded(self):
        v=self.snapshot('P13');v['client']['outbox'][0]['pending']=False
        with self.assertRaisesRegex(AssertionError,'uncertainty_discarded'):analyze(v)
    def test_false_confirmation(self):
        v=self.snapshot('P13');v['client']['jobs'][0]['receipt']={}
        with self.assertRaisesRegex(AssertionError,'unknown_with_confirmation'):analyze(v)
    def test_compensation_amount_mutation(self):
        v=self.snapshot('P14');v['destination']['effects'][1]['quantity']=3
        v['destination']['stock'][0]['available']=11
        with self.assertRaisesRegex(AssertionError,'wrong_compensation_amount'):analyze(v)
    def test_compensation_tenant_mutation(self):
        v=self.snapshot('P14');v['destination']['effects'][1]['tenant']='other'
        with self.assertRaisesRegex(AssertionError,'cross_tenant_compensation'):analyze(v)
    def test_duplicate_control_detected(self):self.assertEqual(analyze(self.snapshot('P03'))['duplicates'],1)
    def test_compensation_not_duplicate(self):self.assertEqual(analyze(self.snapshot('P14'))['duplicates'],0)
    def test_expired_receipt_keeps_unknown(self):self.assertEqual(analyze(self.snapshot('P11'))['unknown'],1)


if __name__=='__main__':unittest.main()
