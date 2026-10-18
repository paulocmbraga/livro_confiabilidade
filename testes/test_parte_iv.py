import copy
import tempfile
from pathlib import Path
import unittest
from laboratorios import guardrails13 as g, autoridade14 as a, coordenacao16 as c
from laboratorios.parte_iv import unique

class Guardrails(unittest.TestCase):
    def test_catalog_has_benign_and_hostile_in_each_partition(self):
        for part in ('desenvolvimento','teste_familias'):
            rows=[r for r in g.cases() if r['partition']==part]
            self.assertEqual([sum(r['benign'] for r in rows),sum(not r['benign'] for r in rows)],[3,3])
    def test_partitions_have_disjoint_families(self):
        s=[{r['family'] for r in g.cases() if r['partition']==p} for p in ('desenvolvimento','teste_familias')]
        self.assertFalse(s[0]&s[1])
    def test_benign_quote_triggers_filter(self):self.assertTrue(g.detected(g.cases()[1]['text']))
    def test_indirect_export_bypasses_filter(self):self.assertEqual(g.decide(g.cases()[7],'lexico'),'permitido')
    def test_tool_list_does_not_authorize_resource(self):self.assertEqual(g.decide(g.cases()[8],'ferramenta'),'permitido')
    def test_bound_policy_blocks_all_hostile(self):
        self.assertTrue(all(g.decide(x,'vinculado')!='permitido' for x in g.cases() if not x['benign']))
    def test_bound_policy_allows_all_legitimate(self):
        self.assertTrue(all(g.decide(x,'vinculado')=='permitido' for x in g.cases() if x['benign']))
    def test_defense_stack_keeps_false_blocks(self):self.assertEqual(g.decide(g.cases()[1],'lexico_vinculado'),'detector')
    def test_block_has_no_effect(self):
        with tempfile.TemporaryDirectory() as d:
            r=g.run_case(g.cases()[8],'vinculado',Path(d)/'d.sqlite')
            self.assertEqual(r['effects'],[]);self.assertEqual(r['states']['T2'],'open')
    def test_allowed_attack_changes_target(self):
        with tempfile.TemporaryDirectory() as d:
            r=g.run_case(g.cases()[8],'ferramenta',Path(d)/'d.sqlite')
            self.assertTrue(r['violation']);self.assertEqual(r['states']['T2'],'closed')

class Authority(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'d.sqlite';a.initialize(self.db);self.req=a.request_for()
    def test_normal_and_repeat_share_receipt(self):
        x=a.execute(self.db,self.req);y=a.execute(self.db,self.req)
        self.assertEqual(x['receipt'],y['receipt']);self.assertEqual(len(a.snapshot(self.db)['receipts']),1)
    def test_resource_switch_does_not_touch_other_owner(self):
        r=a.execute(self.db,dict(self.req,resource='T2'));self.assertEqual(r['reason'],'recurso')
        self.assertEqual(a.snapshot(self.db)['tickets'][1][2],'open')
    def test_claimed_principal_cannot_replace_context(self):self.assertEqual(a.execute(self.db,self.req,'outro')['reason'],'identidade')
    def test_delegation_cannot_enlarge_scope(self):self.assertEqual(a.execute(self.db,self.req,'leitor')['reason'],'escopo')
    def test_audience_required(self):self.assertEqual(a.execute(self.db,self.req,'audiencia_errada')['reason'],'audiencia')
    def test_expired_request_blocks(self):self.assertEqual(a.execute(self.db,self.req,now=151)['reason'],'prazo')
    def test_deadline_inclusive(self):self.assertTrue(a.execute(self.db,self.req,now=150)['allowed'])
    def test_extra_field_rejected(self):self.assertEqual(a.execute(self.db,dict(self.req,admin=True))['reason'],'schema')
    def test_boolean_not_integer_quantity(self):self.assertEqual(a.execute(self.db,dict(self.req,quantity=True))['reason'],'tipo')
    def test_schema_change_explicit(self):self.assertEqual(a.execute(self.db,self.req,schema='2')['reason'],'schema')
    def test_changed_content_loses_approval(self):self.assertEqual(a.execute(self.db,dict(self.req,intent='I-other'))['reason'],'aprovacao')
    def test_receipt_resource_binding(self):
        receipt=a.execute(self.db,self.req)['receipt'];receipt['resource']='T2'
        self.assertFalse(a.valid_receipt(self.req,receipt));self.assertEqual(len(a.snapshot(self.db)['receipts']),1)
    def test_revocation_after_proposal_before_effect(self):
        import sqlite3
        db=sqlite3.connect(self.db);db.execute('UPDATE approvals SET revoked=1');db.commit();db.close()
        self.assertEqual(a.execute(self.db,self.req)['reason'],'aprovacao')
        self.assertEqual(a.snapshot(self.db)['receipts'],[])
    def test_version_changes_after_approval(self):
        import sqlite3
        db=sqlite3.connect(self.db);db.execute('UPDATE tickets SET version=1');db.commit();db.close()
        self.assertEqual(a.execute(self.db,self.req)['reason'],'versao')
    def test_three_http_adapters(self):
        for t in a.TRANSPORTS:
            with self.subTest(transport=t):
                r=a.run_case(a.cases()[0],t,Path(self.temp.name)/t)
                self.assertEqual((r['effects'],r['client']),(1,'confirmed'))
                self.assertNotEqual(r['pid'],r['client_pid'])
                if t=='mcp':
                    from laboratorios.dados_ii import readlines
                    wire=readlines(Path(self.temp.name)/t/'wire.jsonl')
                    self.assertEqual(wire[1]['request']['method'],'notifications/initialized')
                    self.assertNotIn('id',wire[1]['request'])
                    self.assertEqual(wire[1]['response']['http_status'],202)

class Coordination(unittest.TestCase):
    def test_budget_zero_no_effect(self):
        r=c.run(c.cases()[0],'equipe',0);self.assertEqual((r['cost'],r['effects'],r['reason']),(0,[],'orcamento'))
    def test_global_budget_not_per_role(self):
        for limit in range(9):self.assertLessEqual(c.run(c.cases()[0],'equipe',limit)['cost'],limit)
    def test_team_costs_more_than_workflow(self):
        self.assertEqual([c.run(c.cases()[0],v)['cost'] for v in ('simples','equipe')],[4,6])
    def test_review_ablation_exposes_shared_error(self):
        self.assertFalse(c.run(c.cases()[2],'equipe')['violation']);self.assertTrue(c.run(c.cases()[2],'sem_revisor')['violation'])
    def test_consensus_does_not_correct_stale_source(self):self.assertTrue(c.run(c.cases()[2],'consenso')['violation'])
    def test_repeated_artifact_no_extra_effect(self):
        r=c.run(c.cases()[3],'equipe');self.assertEqual(len(r['effects']),1)
        self.assertEqual(sum(e.get('result')=='duplicado' for e in r['trace']),2)
    def test_late_result_does_not_complete_join(self):
        r=c.run(c.cases()[4],'equipe');self.assertEqual((r['outcome'],r['wasted'],r['logical_time']),('pendente',1,6))
        self.assertTrue(any(e.get('result')=='tardio' for e in r['trace']))
    def test_cycle_is_bounded(self):self.assertEqual(c.run(c.cases()[5],'equipe')['reason'],'ciclo')
    def test_wrong_authority_blocks_effect(self):self.assertEqual(c.run(c.cases()[6],'equipe')['effects'],[])
    def test_retry_is_charged(self):self.assertEqual(c.run(c.cases()[7],'equipe')['cost'],7)
    def test_conflicting_duplicate_is_not_overwrite(self):
        store={};x=dict(task='t',role='r',id='i',value=1);c.accept_artifact(store,x,'t')
        self.assertEqual(c.accept_artifact(store,dict(x,value=2),'t'),'conflito')
        self.assertEqual(store[('r','i')]['value'],1)
    def test_wrong_task_rejected(self):self.assertEqual(c.accept_artifact({},dict(task='x',role='r',id='i'),'t'),'tarefa')
    def test_manifest_identity_coverage(self):
        with self.assertRaises(ValueError):unique([dict(id=1),dict(id=1)],('id',),[(1,),(2,)])

if __name__=='__main__':unittest.main()
