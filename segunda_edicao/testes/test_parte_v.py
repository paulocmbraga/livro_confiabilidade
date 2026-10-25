import json,sqlite3,tempfile,unittest,shutil
from pathlib import Path
from laboratorios.parte_v.core import (strict_json,order_contract,identity,commit,
    policy_metrics,judge_release,edit_distance,wer,numeric)
from laboratorios.parte_v.memory import Memory
from laboratorios.parte_v.fallback import decision
from laboratorios.parte_v.verify import verify
from laboratorios.parte_i.common import seal

class Contracts(unittest.TestCase):
    def gate(self,text,**kw):return order_contract(text,kw.get('complete',True),'a',kw.get('received','a'))
    def test_negative_rejected(self):self.assertEqual(self.gate('{"quantity":-3}')['reason'],'domain')
    def test_zero_rejected(self):self.assertFalse(self.gate('{"quantity":0}')['accepted'])
    def test_upper_boundary(self):self.assertTrue(self.gate('{"quantity":99}')['accepted'])
    def test_above_boundary(self):self.assertFalse(self.gate('{"quantity":100}')['accepted'])
    def test_bool_is_not_quantity(self):self.assertEqual(self.gate('{"quantity":true}')['reason'],'schema')
    def test_float_is_not_int(self):self.assertFalse(self.gate('{"quantity":7.0}')['accepted'])
    def test_extra_field(self):self.assertFalse(self.gate('{"quantity":7,"approve":true}')['accepted'])
    def test_missing_field(self):self.assertFalse(self.gate('{}')['accepted'])
    def test_array_rejected(self):self.assertFalse(self.gate('[7]')['accepted'])
    def test_partial_stream(self):self.assertEqual(self.gate('{"quantity":7}',complete=False)['reason'],'incomplete')
    def test_mismatched_config(self):self.assertEqual(self.gate('{"quantity":7}',received='b')['reason'],'configuration')
    def test_duplicate_key(self):self.assertEqual(self.gate('{"quantity":7,"quantity":8}')['reason'],'syntax')
    def test_trailing_data(self):self.assertFalse(self.gate('{"quantity":7} extra')['accepted'])
    def test_nonfinite(self):
        for value in ['NaN','Infinity','-Infinity']:
            with self.subTest(value=value),self.assertRaises(ValueError):strict_json('{"x":'+value+'}')
    def test_identity_order(self):self.assertEqual(identity({'x':1,'y':2}),identity({'y':2,'x':1}))
    def test_identity_sensitive(self):self.assertNotEqual(identity({'temperature':0}),identity({'temperature':.7}))
    def test_effect_replay(self):
        store={};self.assertEqual(commit(store,'a',{'quantity':7}),'created');self.assertEqual(commit(store,'a',{'quantity':7}),'replayed');self.assertEqual(len(store),1)
    def test_effect_conflict(self):
        store={};commit(store,'a',{'quantity':7})
        with self.assertRaises(ValueError):commit(store,'a',{'quantity':8})

class Decisions(unittest.TestCase):
    def setUp(self):self.rows=[{'kind':'answerable','correct':True},{'kind':'missing','correct':False}]
    def test_all_denominator(self):self.assertEqual(policy_metrics(self.rows,'all')['conditional_error'],.5)
    def test_coverage(self):self.assertEqual(policy_metrics(self.rows,'evidence')['coverage'],.5)
    def test_model_abstention_not_coverage(self):
        rows=[{'kind':'missing','correct':True,'answer':'UNKNOWN','complete':True}]
        m=policy_metrics(rows,'all');self.assertEqual(m['accepted'],0);self.assertEqual(m['model_abstentions'],1);self.assertIsNone(m['conditional_error'])
    def test_truncation_not_coverage(self):
        rows=[{'kind':'answerable','correct':False,'answer':'12','complete':False}]
        m=policy_metrics(rows,'all');self.assertEqual(m['accepted'],0);self.assertEqual(m['pipeline_failures'],1)
    def test_no_answers_not_zero_risk(self):self.assertIsNone(policy_metrics(self.rows,'reject_all')['conditional_error'])
    def test_false_blocks(self):self.assertEqual(policy_metrics(self.rows,'reject_all')['false_blocks'],1)
    def test_utility_includes_refusals(self):self.assertEqual(policy_metrics(self.rows,'evidence')['utility'],.4)
    def test_empty_admissions(self):self.assertIsNone(policy_metrics([],'all')['utility'])
    def test_unqualified_judge(self):self.assertFalse(judge_release({'independent_reviewers':2}))
    def test_missing_scope_gate(self):self.assertFalse(judge_release({'independent_reviewers':2,'heldout_adjudicated':True,'threshold_validated':True}))
    def test_qualified_documented_gate(self):self.assertTrue(judge_release({'independent_reviewers':2,'heldout_adjudicated':True,'threshold_validated':True,'scope_matches':True}))
    def test_edit_empty(self):self.assertEqual(edit_distance([],['a']),1)
    def test_edit_substitution(self):self.assertEqual(edit_distance(['a','b'],['a','c']),1)
    def test_wer_can_exceed_one(self):self.assertEqual(wer('a','a b c'),2)
    def test_wer_normalization(self):self.assertEqual(wer('Áudio, claro.','audio CLARO'),0)
    def test_numeric_nan(self):self.assertIsNone(numeric('{"value":NaN}'))
    def test_numeric_boolean(self):self.assertIsNone(numeric('{"value":true}'))
    def test_numeric_string(self):self.assertIsNone(numeric('{"value":"12"}'))

class Storage(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'m.sqlite';self.m=Memory(self.path)
    def tearDown(self):self.m.close();self.tmp.cleanup()
    def run_action(self,action,**kw):return self.m.run('a','a','k',action,**kw)
    def test_restart_persistence(self):
        self.run_action('put',value='12');self.m.close();self.m=Memory(self.path);self.assertEqual(self.run_action('read')['value'],'12')
    def test_cross_tenant(self):
        self.run_action('put',value='12')
        with self.assertRaises(PermissionError):self.m.run('b','a','k','read')
    def test_update_invalidates_summary(self):
        self.run_action('put',value='12');self.run_action('summarize',value='limit 12');self.run_action('put',value='18');self.assertIsNone(self.run_action('summary')['value'])
    def test_same_value_new_epoch(self):
        self.run_action('put',value='12');self.assertEqual(self.run_action('put',value='12')['epoch'],2)
    def test_delete_invalidates_derivative(self):
        self.run_action('put',value='12');self.run_action('summarize',value='limit 12');self.run_action('delete');self.assertIsNone(self.run_action('summary')['value'])
    def test_unsafe_counterexample(self):
        self.run_action('put',value='12');self.run_action('summarize',value='limit 12');self.run_action('delete');self.assertEqual(self.run_action('summary',unsafe=True)['value'],'limit 12')
    def test_delete_is_not_physical_erasure(self):
        self.run_action('put',value='12');self.run_action('summarize',value='limit 12');self.run_action('delete');self.assertEqual(self.m.db.execute('SELECT count(*) FROM summaries').fetchone()[0],1)
    def test_absent_read(self):self.assertIsNone(self.run_action('read')['value'])
    def test_absent_summary_refused(self):
        with self.assertRaises(ValueError):self.run_action('summarize',value='invented')
    def test_deleted_read(self):self.run_action('delete');self.assertIsNone(self.run_action('read')['value'])
    def test_recreated_not_old_summary(self):
        self.run_action('put',value='12');self.run_action('summarize',value='limit 12');self.run_action('delete');self.run_action('put',value='20');self.assertIsNone(self.run_action('summary')['value'])
    def test_sql_value_preserved(self):
        text="'; DROP TABLE facts; --";self.run_action('put',value=text);self.assertEqual(self.run_action('read')['value'],text)

class Fallback(unittest.TestCase):
    def d(self,**kw):
        args=dict(kind='ocr',width=1000,text='Subtotal 100.00 Tax 29.90 Total 129.90',value=129.9,complete=True)
        args.update(kw);return decision(**args)
    def test_correct_candidate(self):self.assertEqual(self.d()['amount_cents'],12990)
    def test_llm_wrong_field(self):self.assertEqual(self.d(value=100)['reason'],'disagreement')
    def test_low_resolution_even_if_correct(self):self.assertFalse(self.d(width=160)['accepted'])
    def test_audio_forwarded(self):self.assertEqual(self.d(kind='asr')['reason'],'unqualified_audio')
    def test_incomplete_refused(self):self.assertEqual(self.d(complete=False)['reason'],'incomplete')
    def test_double_total(self):self.assertFalse(self.d(text='Subtotal 100.00 Tax 29.90 Total 129.90 Total 129.90')['accepted'])
    def test_bad_arithmetic(self):self.assertEqual(self.d(text='Subtotal 100.00 Tax 29.90 Total 139.90')['reason'],'arithmetic')
    def test_nonfinite_value(self):self.assertFalse(self.d(value=float('inf'))['accepted'])

class Evidence(unittest.TestCase):
    source=Path(__file__).resolve().parents[1]/'output/parte_v_principal_v02'
    def test_capture_reconciled(self):self.assertEqual(verify(self.source)['inferences'],115)
    def mutate(self,file,change,reseal=True):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'copy';shutil.copytree(self.source,root)
            p=root/file;q=json.loads(p.read_text(encoding='utf-8'));change(q)
            p.write_text(json.dumps(q,ensure_ascii=False),encoding='utf-8')
            if reseal:(root/'manifesto.json').unlink();seal(root,'mutation')
            with self.assertRaises((ValueError,AssertionError)):verify(root)
    def test_corrupt_hash(self):self.mutate('results.json',lambda q:q.update(fake=True),False)
    def test_resealed_wrong_metric(self):self.mutate('results.json',lambda q:q['L18']['policies']['all'].update(coverage=1))
    def test_resealed_wrong_oracle(self):self.mutate('results.json',lambda q:q['L18']['answers'][0].update(allowed=['99']))
    def test_resealed_wrong_stream(self):self.mutate('calls/l17_retry.json',lambda q:q.update(text='{"quantity":99}'))
    def test_resealed_unsafe_release(self):self.mutate('results.json',lambda q:q['L18'].update(judge_operational_release=True))

if __name__=='__main__':unittest.main()
