"""Contraprovas dos instrumentos; integração real fica nas capturas reconciliadas."""
from pathlib import Path
from tempfile import TemporaryDirectory
import copy,json,unittest,shutil
from laboratorios.parte_iii import l09,l10,l12
from laboratorios.parte_i.common import ROOT,load,sha
from laboratorios.parte_iii.verify import verify

class CaptureMutationTests(unittest.TestCase):
    """Hashes refeitos: a rejeição precisa vir de uma relação quebrada."""
    def changed(self,relative,mutate):
        with TemporaryDirectory() as tmp:
            out=Path(tmp)/'capture'
            shutil.copytree(ROOT/'output/parte_iii_principal_v02',out)
            path=out/relative
            value=mutate(load(path))
            if value is None:path.unlink()
            else:path.write_text(json.dumps(value),encoding='utf-8')
            manifest=load(out/'manifesto.json')
            manifest['files']={p.relative_to(out).as_posix():sha(p)
                for p in out.rglob('*') if p.is_file() and p.name!='manifesto.json'}
            (out/'manifesto.json').write_text(json.dumps(manifest),encoding='utf-8')
            with self.assertRaises((AssertionError,ValueError,FileNotFoundError)):
                verify(out)
    def test_missing_raw_even_with_new_manifest(self):
        self.changed('l12/T01/raw.json',lambda _:None)
    def test_changed_request(self):
        def alter(v):v['request']['max_tokens']=999;return v
        self.changed('l12/T01/raw.json',alter)
    def test_evaluator_result_cannot_be_faked(self):
        def alter(v):v['response']['correct']=False;return v
        self.changed('l12/T01/evaluation.json',alter)
    def test_callback_must_match_raw_digest(self):
        self.changed('l12/T01/callback.json',lambda v:v|{'output_sha256':'0'*64})
    def test_service_audit_must_match_worker(self):
        def alter(v):v['response']['correct']=False;return v
        self.changed('l12/evaluator/event_000.json',alter)
    def test_budget_must_reject_actual_ninth_reservation(self):
        def alter(v):v['events'][-1]['result']='reserved';return v
        self.changed('l12/budget.json',alter)
    def test_aborted_attempt_not_deleted(self):
        def alter(v):del v['attempt_states']['T07-1'];return v
        self.changed('l12/report.json',alter)
    def test_crash_exit_not_normalized(self):
        def alter(v):
            next(x for x in v if x['exit_code']==86)['exit_code']=0
            return v
        self.changed('l12/processes.json',alter)
    def test_late_result_not_promoted(self):
        self.changed('l12/late_delivery.json',lambda v:v|{'status':'accepted'})
    def test_human_fixture_not_relabelled(self):
        self.changed('l10_fixture.json',lambda v:v|{'actual_people':2})
    def test_oracle_summary_must_match_rows(self):
        def alter(v):v['rounding']['independent']['decision']='pass';return v
        self.changed('l09/summary.json',alter)

class OracleTests(unittest.TestCase):
    def test_half_up_anchor(self):self.assertEqual(l09.reference_cents('1.005'),101)
    def test_implementation_anchor(self):self.assertEqual(l09.cents('1.005'),101)
    def test_shared_converter_has_defect(self):self.assertEqual(l09.cents('1.005','rounding'),100)
    def test_reject_negative(self):
        with self.assertRaises(ValueError):l09.reference_cents('-1')
    def test_reject_boolean(self):
        with self.assertRaises(ValueError):l09.cents(True)
    def test_reject_nan(self):
        with self.assertRaises(ValueError):l09.cents('NaN')
    def test_reject_non_ascii(self):
        with self.assertRaises(ValueError):l09.cents('١')
    def test_zero_denied(self):
        with self.assertRaises(ValueError):l09.reference_cents('0.000')
    def test_generated_positive_cents(self):
        for n in range(1,10000,17):
            text=f'{n//1000}.{n%1000:03}'
            self.assertEqual(l09.cents(text),l09.reference_cents(text))
    def test_repeated_request_preserves_balance(self):
        r=l09.Reference();q=dict(id='A',op='credit',amount='1.005');first=r.apply(q);self.assertEqual(r.apply(q),first)
    def test_conflict_does_not_change_balance(self):
        r=l09.Reference();r.apply(dict(id='A',op='credit',amount='1'));self.assertEqual(r.apply(dict(id='A',op='credit',amount='2')),{'status':'conflict','balance':100})
    def test_overdraft_denied(self):self.assertEqual(l09.Reference().apply(dict(id='B',op='debit',amount='1'))['status'],'insufficient')
    def test_unknown_not_pass(self):
        row={'request':dict(id='A',op='credit',amount='1'),'observed':None};self.assertEqual(l09.analyze([row])['decision'],'inconclusive')
    def test_real_sqlite_rollback_of_decline(self):
        with TemporaryDirectory() as d:
            ledger=l09.Ledger(Path(d)/'x.sqlite','correct')
            self.assertEqual(ledger.apply(dict(id='B',op='debit',amount='10'))['balance'],0);ledger.db.close()
    def test_mutant_overdraft_is_reached(self):
        with TemporaryDirectory() as d:
            ledger=l09.Ledger(Path(d)/'x.sqlite','overdraft')
            self.assertEqual(ledger.apply(dict(id='B',op='debit',amount='10'))['balance'],-1000);ledger.db.close()
    def test_sequence_size(self):self.assertEqual(len(l09.operations()),40)

class HumanTests(unittest.TestCase):
    def test_perfect_nonconstant(self):self.assertEqual(l10.agreement([0,1,2],[0,1,2])['kappa'],1)
    def test_single_class_not_infinite(self):self.assertIsNone(l10.agreement([2,2],[2,2])['kappa'])
    def test_unknown_preserves_denominator(self):self.assertEqual(l10.agreement([0,'U'],[0,1])['unknown'],1)
    def test_all_unknown(self):self.assertIsNone(l10.agreement(['U'],[1])['agreement'])
    def test_boolean_not_label(self):
        with self.assertRaises(ValueError):l10.agreement([True],[1])
    def test_unpaired(self):
        with self.assertRaises(ValueError):l10.agreement([1],[1,2])
    def test_fixture_is_explicit(self):self.assertEqual(l10.fixture()['actual_people'],0)
    def test_weighted_penalizes_distance(self):self.assertGreater(l10.agreement([0,1,2],[0,2,2],True)['agreement'],l10.agreement([0,1,2],[0,2,2])['agreement'])
    def test_blank_form_blocked(self):
        with self.assertRaises(ValueError):l10.validate({'kind':'human','rubric':'L10-r1'},[])
    def test_fixture_not_human(self):
        with self.assertRaises(ValueError):l10.validate({'kind':'fixture_not_human','rubric':'L10-r1'},[])
    def test_unresolved_disagreement(self):
        a=[dict(item='A',support=2,sufficiency=1)];b=[dict(item='A',support=0,sufficiency=1)]
        result=l10.adjudicate(a,b,{})
        self.assertEqual(result[0]['reference'],'U');self.assertEqual(result[0]['original'],[2,0]);self.assertEqual(result[1]['reference'],1)
    def test_adjudication_requires_reason(self):
        a=[dict(item='A',support=2,sufficiency=1)];b=[dict(item='A',support=0,sufficiency=1)]
        with self.assertRaises(ValueError):l10.adjudicate(a,b,{'A:support':{'value':2}})

class CampaignContracts(unittest.TestCase):
    def test_quota_denies_ninth(self):
        b=l12.Budget(8)
        for i in range(8):self.assertEqual(b.reserve(str(i)),'reserved')
        self.assertEqual(b.reserve('ninth'),'quota_rejected')
    def test_retry_reuses_reservation(self):
        b=l12.Budget(1);b.reserve('A');self.assertEqual(b.reserve('A'),'already_reserved');self.assertEqual(b.reserve('B'),'quota_rejected')
    def test_budget_bool_invalid(self):
        with self.assertRaises(ValueError):l12.Budget(True)
    def test_budget_zero_invalid(self):
        with self.assertRaises(ValueError):l12.Budget(0)
    def setUp(self):
        self.exp={'attempt':'A','case':'T01','candidate':'C','judge':'exact-v1'}
        self.payload=self.exp|{'output_sha256':'a'*64,'valid':True,'correct':True}
        self.c=l12.Collector([self.exp])
    def test_accept_known_identity(self):self.assertEqual(self.c.callback(self.payload)['status'],'accepted')
    def test_case_mismatch(self):self.assertEqual(self.c.callback(self.payload|{'case':'T02'})['status'],'identity_mismatch')
    def test_judge_mismatch(self):self.assertEqual(self.c.callback(self.payload|{'judge':'exact-v2'})['status'],'identity_mismatch')
    def test_candidate_mismatch(self):self.assertEqual(self.c.callback(self.payload|{'candidate':'D'})['status'],'identity_mismatch')
    def test_unknown_attempt(self):self.assertEqual(self.c.callback(self.payload|{'attempt':'B'})['status'],'unknown_attempt')
    def test_duplicate_idempotent(self):
        self.c.callback(self.payload);self.assertEqual(self.c.callback(self.payload)['status'],'duplicate');self.assertEqual(len(self.c.received),1)
    def test_conflicting_duplicate_rejected(self):
        self.c.callback(self.payload);self.assertEqual(self.c.callback(self.payload|{'correct':False})['status'],'conflicting_duplicate')
    def test_late_does_not_reopen(self):
        self.c.closed=True;self.assertEqual(self.c.callback(self.payload)['status'],'late');self.assertFalse(self.c.received)
    def test_invalid_not_discarded(self):self.assertEqual(self.c.callback(self.payload|{'valid':False,'correct':False})['status'],'accepted')
    def test_string_boolean_rejected(self):self.assertEqual(self.c.callback(self.payload|{'valid':'true'})['status'],'malformed')
    def test_correct_requires_valid(self):self.assertEqual(self.c.callback(self.payload|{'valid':False})['status'],'malformed')
    def test_hex_digest_required(self):self.assertEqual(self.c.callback(self.payload|{'output_sha256':'z'*64})['status'],'malformed')
    def test_duplicate_admission_rejected(self):
        with self.assertRaises(ValueError):l12.Collector([self.exp,self.exp])
    def test_raw_value_oracle(self):self.assertTrue(l12.evaluate('{"prazo":10}',l12.cases()[0],'exact-v1')['correct'])
    def test_v2_is_different_ruler(self):self.assertFalse(l12.evaluate('{"prazo":10}',l12.cases()[0],'exact-v2')['correct'])
    def test_duplicate_json_keys_invalid(self):self.assertFalse(l12.evaluate('{"prazo":1,"prazo":10}',l12.cases()[0],'exact-v1')['valid'])
    def test_boolean_answer_invalid(self):self.assertFalse(l12.evaluate('{"prazo":true}',l12.cases()[0],'exact-v1')['valid'])
    def test_missing_answer_invalid(self):self.assertFalse(l12.evaluate(None,l12.cases()[0],'exact-v1')['valid'])
    def test_truncated_finish_not_full_answer(self):
        raw={'error':None,'response':{'choices':[{'finish_reason':'length','message':{'content':'{"prazo":10}'}}]}}
        self.assertIsNone(l12.consumed_text(raw))
    def test_reference_not_in_request_fields(self):
        self.assertNotIn('expected',json.dumps(l12.request_for(l12.cases()[0])))
    def test_unknown_blocks_release(self):
        r={'identity':'X','created':100,'expires':200,'tasks':{'T':'unknown'},'human_semantic_qualification':True}
        self.assertEqual(l12.release(r,150,'X'),'blocked_incomplete')
    def test_expiry_is_checked(self):
        r={'identity':'X','created':100,'expires':200,'tasks':{'T':'evaluated'},'human_semantic_qualification':True}
        self.assertEqual(l12.release(r,201,'X'),'blocked_expired')
    def test_identity_blocks_even_good_report(self):
        r={'identity':'X','created':100,'expires':200,'tasks':{'T':'evaluated'},'human_semantic_qualification':True}
        self.assertEqual(l12.release(r,150,'Y'),'blocked_identity')
    def test_gate_never_implies_publish(self):
        r={'identity':'X','created':100,'expires':200,'tasks':{'T':'evaluated'},'human_semantic_qualification':True,'accepted_correct':1}
        self.assertEqual(l12.release(r,150,'X'),'eligible_for_review')
    def test_complete_does_not_imply_correct(self):
        r={'identity':'X','created':100,'expires':200,'tasks':{'T':'evaluated'},'human_semantic_qualification':True,'accepted_correct':0}
        self.assertEqual(l12.release(r,150,'X'),'blocked_quality')

if __name__=='__main__':unittest.main()
