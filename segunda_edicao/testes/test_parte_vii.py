"""Contratos que impedem conclusões falsas e efeitos indevidos."""
from pathlib import Path
import copy,json,tempfile,threading,unittest
from laboratorios.parte_vii.core import *
from laboratorios.parte_vii.campaign import fixtures,policy_cases
from laboratorios.parte_vii.destination import init,act,inspect
from laboratorios.parte_vii.verify import verify,protocols
from laboratorios.parte_i.common import save,seal,check_manifest
ROOT=Path(__file__).resolve().parents[1]

class DestinationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'db.sqlite';self.task=fixtures()[0];init(self.db,self.task)
    def tearDown(self):self.tmp.cleanup()
    def request(self,**changes):return dict(dict(action='reserve',item='A',quantity=2,version=0),**changes)
    def read(self):return act(self.db,self.task,self.request(action='inspect'))
    def test_read_required(self):self.assertEqual(act(self.db,self.task,self.request())['error'],'read_required')
    def test_reservation(self):self.read();act(self.db,self.task,self.request());self.assertEqual(inspect(self.db)['stock']['A'],3)
    def test_duplicate(self):
        self.read();act(self.db,self.task,self.request());act(self.db,self.task,self.request());self.assertEqual(len(inspect(self.db)['effects']),1)
    def test_concurrent(self):
        self.read();results=[]
        threads=[threading.Thread(target=lambda:results.append(act(self.db,self.task,self.request()))) for _ in range(4)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(len(results),4);self.assertEqual(len(inspect(self.db)['effects']),1)
    def test_invalid_item(self):self.read();self.assertEqual(act(self.db,self.task,self.request(item='B'))['error'],'not_allowed')
    def test_invalid_quantity(self):self.read();self.assertEqual(act(self.db,self.task,self.request(quantity=3))['error'],'quantity')
    def test_boolean_quantity(self):self.read();self.assertEqual(act(self.db,self.task,self.request(quantity=True))['error'],'type')
    def test_old_version(self):self.read();self.assertEqual(act(self.db,self.task,self.request(version=7))['error'],'version_conflict')
    def test_no_effect_on_finish(self):self.read();act(self.db,self.task,self.request(action='finish'));self.assertEqual(inspect(self.db)['effects'],[])
    def test_false_finish(self):self.assertTrue(outcome(self.task,inspect(self.db),'finish')['false_finish'])
    def test_refusal_feasible(self):self.assertFalse(outcome(self.task,inspect(self.db),'abstain')['task_success'])
    def test_success_observer(self):self.read();act(self.db,self.task,self.request());self.assertTrue(outcome(self.task,inspect(self.db),'confirmed')['task_success'])
    def test_control_forbidden(self):
        snapshot=inspect(self.db);snapshot['effects']=[dict(intent=self.task['id'],item='B',quantity=2,amount=16)]
        self.assertEqual(outcome(self.task,snapshot,'finish')['forbidden_effects'],1)
    def test_control_duplicate(self):
        self.read();act(self.db,self.task,self.request());snapshot=inspect(self.db);snapshot['effects']*=2
        self.assertEqual(outcome(self.task,snapshot,'confirmed')['duplicate_effects'],1)
    def test_read_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'db';task=fixtures()[4];init(db,task);seen=act(db,task,self.request(action='inspect'))
            self.assertEqual(seen['version'],0);self.assertEqual(inspect(db)['version'],1)
            self.assertEqual(act(db,task,self.request())['error'],'version_conflict')
    def test_workflow_all_fixtures(self):
        for task in fixtures():
            with self.subTest(task=task['id']),tempfile.TemporaryDirectory() as d:
                db=Path(d)/'db';init(db,task);state=None;terminal='budget'
                for _ in range(4):
                    p=self.request(action='inspect') if state is None else choose(task,state);r=act(db,task,p)
                    if r.get('receipt'):terminal='confirmed';break
                    if p['action']=='abstain':terminal='abstain';break
                    state=None if r.get('error') else r
                self.assertTrue(outcome(task,inspect(db),terminal)['task_success'])

class DecisionTests(unittest.TestCase):
    def test_consensus_yes(self):self.assertIs(consensus([{'approve':True}]*2+[None]),True)
    def test_consensus_no(self):self.assertIs(consensus([{'approve':False}]*2+[None]),False)
    def test_consensus_abstains(self):self.assertIsNone(consensus([{'approve':True},None,None]))
    def test_tie(self):self.assertIsNone(consensus([{'approve':True},{'approve':False},None]))
    def test_joint_error(self):self.assertEqual(pair_error([{'approve':True}]*3,False)['both_wrong'],3)
    def test_missing_denominator(self):self.assertEqual(pair_error([{'approve':True},None,{'approve':False}],False)['pairs'],1)
    def test_reference_separate(self):self.assertNotEqual(policy_cases()[2]['current'],policy_cases()[2]['stale'])
    def test_schema_completion(self):
        r={'choices':[dict(finish_reason='stop',message={'content':'{"approve":true,"limit":100,"source":"v2"}'})]}
        self.assertTrue(parsed(r,VOTE_SCHEMA)['approve'])
    def test_truncation_rejected(self):
        with self.assertRaises(ValueError):parsed({'choices':[{'finish_reason':'length'}]},VOTE_SCHEMA)
    def test_extra_field_rejected(self):
        from jsonschema import ValidationError
        r={'choices':[dict(finish_reason='stop',message={'content':'{"approve":true,"limit":100,"source":"v2","x":1}'})]}
        with self.assertRaises(ValidationError):parsed(r,VOTE_SCHEMA)

class BudgetTests(unittest.TestCase):
    def test_invalid_limit(self):
        with self.assertRaises(ValueError):Budget(True)
    def test_cap(self):b=Budget(100);self.assertTrue(b.reserve('a',60));self.assertFalse(b.reserve('b',60))
    def test_complete(self):b=Budget(100);b.reserve('a',60);b.complete('a',20);self.assertEqual(b.spent,20);self.assertEqual(b.held,{})
    def test_overuse(self):
        b=Budget(100);b.reserve('a',60)
        with self.assertRaises(ValueError):b.complete('a',61)
    def test_no_early_reclaim(self):
        b=Budget(100);b.reserve('a',60)
        with self.assertRaises(ValueError):b.cancelled_before_call('a',False)
        self.assertEqual(b.held['a'],60)
    def test_reclaim(self):b=Budget(100);b.reserve('a',60);b.cancelled_before_call('a',True);self.assertEqual(b.held,{})
    def test_duplicate_reservation(self):
        b=Budget(100);b.reserve('a',20)
        with self.assertRaises(ValueError):b.reserve('a',20)
    def test_concurrent_admission(self):
        b=Budget(100);result=[];threads=[threading.Thread(target=lambda n=i:result.append(b.reserve(str(n),60))) for i in range(8)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sum(result),1)

class CallbackTests(unittest.TestCase):
    def setUp(self):
        self.expected=dict(task_id='t',context_id='c',intent='i',contract='v1',audience='a')
        self.state=dict(seen=[],sequence=0,status='working')
        self.event=dict(event_id='e',sequence=1,status='completed',metadata=self.expected.copy())
    def test_binding(self):self.assertTrue(artifact_binding(self.expected,self.event))
    def test_each_dimension(self):
        for key in self.expected:
            e=copy.deepcopy(self.event);e['metadata'][key]='other';self.assertFalse(artifact_binding(self.expected,e))
    def test_accept(self):self.assertEqual(apply_callback(self.state,self.event,self.expected)[1],'accepted')
    def test_no_mutation(self):apply_callback(self.state,self.event,self.expected);self.assertEqual(self.state['seen'],[])
    def test_duplicate(self):
        s,_=apply_callback(self.state,self.event,self.expected);self.assertEqual(apply_callback(s,self.event,self.expected)[1],'duplicate')
    def test_old(self):self.assertEqual(apply_callback(self.state,dict(self.event,sequence=0),self.expected)[1],'old_event')
    def test_terminal(self):
        s,_=apply_callback(self.state,self.event,self.expected)
        self.assertEqual(apply_callback(s,dict(self.event,event_id='e2',sequence=2,status='working'),self.expected)[1],'terminal_regression')
    def test_foreign(self):self.assertEqual(apply_callback(self.state,dict(self.event,metadata={}),self.expected)[1],'binding_rejected')

class CaptureTests(unittest.TestCase):
    def test_real_inference_capture(self):self.assertEqual(verify(ROOT/'output/parte_vii_principal_v02')['episodes25'],48)
    def test_protocol_capture(self):self.assertGreater(protocols(ROOT/'output/parte_vii_protocolos_v02')['files'],20)
    def test_hash_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);save(p/'x.json',{'x':1});seal(p,'test');(p/'x.json').write_text('{}')
            with self.assertRaises(ValueError):check_manifest(p)
    def test_missing_member(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);save(p/'x.json',{'x':1});seal(p,'test');(p/'x.json').unlink()
            with self.assertRaises(ValueError):check_manifest(p)
    def test_extra_member(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);seal(p,'test');save(p/'x.json',{'x':1})
            with self.assertRaises(ValueError):check_manifest(p)

if __name__=='__main__':unittest.main()
