from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from laboratorios import liberacao21 as release,incidente22 as incident
from laboratorios import assistente23 as assistant,operacoes24 as operations,parte_vi
from laboratorios import evidencia_vi as evidence,recuperacao06 as rag
from laboratorios.dados_ii import write,readlines


class Liberacao(unittest.TestCase):
    def test_complete(self):self.assertTrue(release.gate(release.package())['accepted'])
    def test_missing_case(self):
        p=release.package();p['suites']['reserved']['rows'].pop()
        self.assertIn('suite_incompleta:reserved',release.gate(p)['reasons'])
    def test_duplicate_case(self):
        p=release.package();p['suites']['reserved']['rows'][-1]=p['suites']['reserved']['rows'][0]
        self.assertFalse(release.gate(p)['accepted'])
    def test_report_cannot_change_denominator(self):
        p=release.package();s=p['suites']['reserved'];s['rows'].pop();s['expected'].pop()
        self.assertFalse(release.gate(p)['accepted'])
    def test_minor_segment(self):
        p=release.package();p['suites']['reserved']['rows'][-1]['passed']=False
        g=release.gate(p);self.assertEqual(g['scores']['raro']['rate'],.75)
        self.assertIn('piso_segmento:raro',g['reasons'])
    def test_other_subject(self):
        p=release.package();p['suites']['unit']['subject']='old'
        self.assertIn('sujeito_divergente:unit',release.gate(p)['reasons'])
    def test_runtime_swap(self):
        p=release.package();p['observed_components']['model']='changed'
        self.assertIn('execucao_divergente',release.gate(p)['reasons'])
    def test_rehash_not_authenticity(self):
        p=release.package();p['manifest']['components']['model']='changed'
        self.assertIn('identidade_invalida',release.gate(p)['reasons'])
    def test_missing_component(self):
        p=release.package();p['manifest']['components'].pop('policy')
        self.assertIn('componentes_incompletos',release.gate(p)['reasons'])
    def test_unknown_change_full_suite(self):self.assertEqual(release.required_suites(['unknown']),set(release.SUITES))
    def test_missing_suite(self):
        p=release.package();p['suites'].pop('reserved');self.assertFalse(release.gate(p)['accepted'])
    def test_old_reader_refuses(self):
        old=dict(schema=1,intent='I',key='K',status='unknown',quantity=2)
        new=release.checkpoint_v2(old)
        self.assertEqual(release.read_checkpoint(old,1),release.read_checkpoint(new,2))
        with self.assertRaises(ValueError):release.read_checkpoint(new,1)
    def test_unsafe_migration(self):
        p=release.package();p['migration']['pending_pinned_v1']=False
        self.assertIn('retorno_inseguro',release.gate(p)['reasons'])
    def test_shadow_effects_real_sqlite(self):
        with tempfile.TemporaryDirectory() as t:
            a=release.rollout(Path(t)/'a.sqlite');b=release.rollout(Path(t)/'b.sqlite',True)
        self.assertEqual((a['effects'],b['effects']),(10,20))
        self.assertEqual(a['candidate_tasks'],2)


class Incidente(unittest.TestCase):
    def setUp(self):self.a=incident.run();self.b=incident.run('availability')
    def test_population(self):self.assertEqual(len({r['task'] for r in self.a['tasks']}),12)
    def test_200_can_be_wrong(self):self.assertEqual(sum(r['status']==200 and not r['good'] for r in self.b['tasks']),5)
    def test_containment_not_success(self):
        self.assertEqual(self.a['summary']['held'],3);self.assertEqual(self.a['summary']['good'],6)
    def test_alert_reconciliation(self):
        self.assertEqual(self.a['summary']['detection_delay'],3)
        self.assertIn('quality_alert_dropped',[r['event'] for r in self.a['timeline']])
    def test_partial_bounds(self):
        r=incident.service_view(self.a['tasks'],4)
        self.assertEqual((r['known'],r['total']),(3,5));self.assertEqual((r['lower'],r['upper']),(.6,1))
    def test_mature_bounds_collapse(self):
        r=incident.service_view(self.a['tasks'],13);self.assertEqual(r['lower'],r['upper']);self.assertEqual(r['coverage'],1)
    def test_no_population_undefined(self):self.assertIsNone(incident.service_view([],0)['lower'])
    def test_partial_recovery_refused(self):self.assertFalse(self.a['return_checks'][0]['allowed'])
    def test_complete_recovery(self):self.assertTrue(self.a['return_checks'][1]['allowed'])
    def test_missing_ack(self):
        e=deepcopy(self.a['return_checks'][1]['evidence']);e.pop('owner_ack')
        self.assertFalse(incident.may_reopen(e)['allowed'])
    def test_critical_separate(self):self.assertTrue(incident.critical_stop([dict(kind='content_exposure')]))
    def test_budget_not_permission(self):
        v=incident.service_view([dict(tick=0,label_at=0,good=True)],0)
        self.assertGreater(v['budget']['allowed'],0)
        self.assertTrue(incident.critical_stop([dict(kind='unauthorized_effect')]))
    def test_action_wrong_version(self):
        a=dict(owner='op',due=2,revision='v3',verification='t')
        self.assertFalse(incident.close_action(a,{'t':dict(passed=True,revision='v2')}))
    def test_action_same_version(self):
        a=dict(owner='op',due=2,revision='v3',verification='t')
        self.assertTrue(incident.close_action(a,{'t':dict(passed=True,revision='v3')}))


class Assistente(unittest.TestCase):
    def setUp(self):self.docs=assistant.documents();self.q=assistant.reserved()
    def test_reference_hidden(self):self.assertNotIn('expected',assistant.public(self.q[0]))
    def test_disjoint_families(self):self.assertFalse({q['topic'] for q in rag.queries()} & {q['family'] for q in self.q})
    def test_reserved_correct(self):
        rows=[assistant.judge(q,assistant.answer(q,'compositor',self.docs),self.docs) for q in self.q]
        self.assertEqual(sum(r['correct'] for r in rows),8)
    def test_forbidden_not_context(self):
        row=assistant.answer(self.q[2],'compositor',self.docs);self.assertNotIn('H04',row['context'])
        self.assertEqual(row['response'],{})
    def test_conflict_abstains(self):self.assertEqual(assistant.answer(self.q[3],'compositor',self.docs)['response'],{})
    def test_unknown_abstains(self):self.assertEqual(assistant.answer(self.q[6],'compositor',self.docs)['response'],{})
    def test_missing_population(self):
        with self.assertRaises(ValueError):assistant.aggregate([],['A01'])
    def test_duplicate_population(self):
        row=assistant.judge(self.q[0],assistant.answer(self.q[0],'compositor',self.docs),self.docs)
        with self.assertRaises(ValueError):assistant.aggregate([row,row],['A01'])
    def test_stale_cache_preserved(self):
        c=assistant.Cache(False);a=c.get(self.q[0],'compositor',self.docs)
        b=c.get(self.q[0],'compositor',assistant.updated(self.docs))
        self.assertEqual(a['response'],b['response']);self.assertTrue(b['cache_hit']);self.assertEqual(b['work_units'],1)
    def test_safe_cache_updates(self):
        c=assistant.Cache();c.get(self.q[0],'compositor',self.docs)
        b=c.get(self.q[0],'compositor',assistant.updated(self.docs))
        self.assertEqual(b['response'],{'garantia_prazo':'24 meses'});self.assertFalse(b['cache_hit'])
    def test_safe_cache_permission(self):
        c=assistant.Cache();c.get(self.q[1],'compositor',self.docs)
        self.assertEqual(c.get(self.q[1],'compositor',assistant.updated(self.docs))['response'],{})
    def test_bad_citation(self):
        q=self.q[0];row=assistant.answer(q,'compositor',self.docs);row['citations']=[]
        self.assertFalse(assistant.judge(q,row,self.docs)['correct'])
    def test_reindex_failure_detected(self):
        broken=[d for d in self.docs if d['doc_id']!='H07'];q=self.q[4]
        self.assertFalse(assistant.judge(q,assistant.answer(q,'compositor',broken),self.docs)['correct'])
    def test_select_only_development(self):
        dev=[assistant.judge(q,assistant.answer(q,v,self.docs),self.docs) for v in assistant.VARIANTS for q in rag.queries()]
        self.assertEqual(assistant.select(dev),'compositor')


class Operacoes(unittest.TestCase):
    def test_workflow_selected(self):self.assertEqual(operations.choose(operations.development()),'workflow')
    def test_common_budget(self):self.assertEqual({r['budget'] for r in operations.development()},{8})
    def test_rule_agent_violation(self):
        self.assertEqual(sum(r['violation'] for r in operations.development() if r['architecture']=='agente_regras'),1)
    def test_incomplete_development(self):
        with self.assertRaises(ValueError):operations.choose(operations.development()[:-1])
    def test_incomplete_operational(self):
        with self.assertRaises(ValueError):operations.decide([],{},[],'workflow')
    def test_review_conservation(self):
        rows=operations.review_queue([['A','B','C'],[],[]],1)
        self.assertEqual([len(r['pending']) for r in rows],[2,1,0])
        self.assertEqual([x for r in rows for x in r['processed']],['A','B','C'])
    def test_zero_capacity_visible(self):self.assertEqual(len(operations.review_queue([['A'],[]],0)[-1]['pending']),1)
    def test_negative_capacity(self):
        with self.assertRaises(ValueError):operations.review_queue([], -1)
    def test_unknown_blocks_authority(self):
        reports=[dict(case=i,unknown=int(i=='S12'),duplicates=0) for i in operations.FAULT_IDS]
        d=operations.decide(reports,dict(effects=0),[dict(pending=[])],'workflow')
        self.assertEqual(d['status'],'bloquear_ampliacao');self.assertFalse(d['external_authority'])
    def test_backlog_blocks(self):
        reports=[dict(case=i,unknown=0,duplicates=0) for i in operations.FAULT_IDS]
        d=operations.decide(reports,dict(effects=0),[dict(pending=['A'])],'workflow')
        self.assertEqual(d['status'],'bloquear_ampliacao')


class Integracao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.folder=Path(cls.tmp.name)/'capture'
        cls.result=parte_vi.capture(cls.folder)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_complete_capture(self):self.assertEqual(self.result['labs'],['L21','L22','L23','L24'])
    def test_read_only_reconciliation(self):self.assertEqual(parte_vi.verify(self.folder),self.result)
    def test_actual_lost_reply_recovered(self):
        r=json.loads((self.folder/'L24/S02/evidence.json').read_text(encoding='utf8'))
        self.assertEqual((r['report']['effects'],r['report']['unknown']),(1,0))
    def test_actual_missing_receipt_uncertain(self):
        r=json.loads((self.folder/'L24/S12/evidence.json').read_text(encoding='utf8'))
        self.assertEqual((r['report']['effects'],r['report']['unknown']),(1,1))
    def test_actual_delegation_denied(self):
        r=json.loads((self.folder/'L24/delegation/evidence.json').read_text(encoding='utf8'))
        self.assertEqual((r['status'],r['effects']),(403,0))
    def test_concurrent_single_effect(self):
        r=json.loads((self.folder/'L24/S08/evidence.json').read_text(encoding='utf8'))
        self.assertEqual((r['report']['effects'],r['report']['duplicates']),(1,0))
    def test_index_tampering(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);write(p/'data.json',dict(a=1));idx=evidence.index(p,{'a':['data.json']})
            write(p/'data.json',dict(a=2))
            with self.assertRaises(ValueError):evidence.verify_index(p,idx,['a'])
    def test_path_escape(self):
        with self.assertRaises(ValueError):evidence.locate(self.folder,'../outside')
    def test_missing_claim(self):
        with self.assertRaises(ValueError):evidence.verify_index(self.folder,{'claims':[]},['a'])
    def test_new_capture_required(self):
        with self.assertRaises(FileExistsError):parte_vi.capture(self.folder)


if __name__=='__main__':unittest.main()
