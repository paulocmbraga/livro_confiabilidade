import copy,json,math,unittest
from pathlib import Path
from laboratorios.l23.core import *
from laboratorios.l23.campaign import plan_jobs,ROOT

class Mechanisms(unittest.TestCase):
    def setUp(self):
        self.q={'tenant':'alpha','as_of':'2026-10-23'}
        self.d=dict(id='A',tenant='alpha',valid_from='2026-01-01',valid_until=None,version='v1',text='limite 10',source_text='limite 10')
    def test_tenant_not_from_document(self):
        self.assertFalse(eligible(dict(self.d,tenant='beta'),self.q))
    def test_future_excluded(self):
        self.assertFalse(eligible(dict(self.d,valid_from='2027-01-01'),self.q))
    def test_end_exclusive(self):
        self.assertFalse(eligible(dict(self.d,valid_until='2026-10-23'),self.q))
    def test_bm25_numerical(self):
        docs=[dict(id='a',text='azul'),dict(id='b',text='verde')]
        r=bm25('azul',docs)
        self.assertAlmostEqual(r[0]['score'],math.log(2));self.assertEqual(r[1]['score'],0)
    def test_bm25_tf_saturation(self):
        a=bm25('azul',[dict(id='a',text='azul'),dict(id='b',text='verde')])[0]['score']
        b=bm25('azul',[dict(id='a',text='azul azul azul'),dict(id='b',text='verde')])[0]['score']
        self.assertLess(b,3*a)
    def test_query_repetition_not_weighted(self):
        self.assertEqual(bm25('x x',[dict(id='a',text='x')]),bm25('x',[dict(id='a',text='x')]))
    def test_rrf_manual(self):
        r=rrf([[{'id':'A'},{'id':'B'}],[{'id':'B'},{'id':'A'}]])
        self.assertEqual([x['id'] for x in r],['A','B']);self.assertAlmostEqual(r[0]['score'],1/61+1/62)
    def test_recall_not_empty_success(self):
        self.assertIsNone(ranking_metrics(['A'],[])['recall'])
    def test_ndcg_manual(self):
        self.assertAlmostEqual(ranking_metrics(['X','A'],['A'])['ndcg'],1/math.log2(3))
    def test_duplicates_not_gain(self):
        self.assertEqual(ranking_metrics(['A','A'],['A','B'])['recall'],.5)
    def test_whole_block_not_cut(self):
        c=assemble(['A'],{'A':self.d},1,3,len)
        self.assertEqual(c['ids'],[]);self.assertEqual(c['skipped'],['A'])
    def test_source_only_explicit_intervention(self):
        d=dict(self.d,text='nota ausente',source_text='nota: 10')
        a=assemble(['A'],{'A':d},1,1000,len);b=assemble(['A'],{'A':d},1,1000,len,True)
        self.assertNotIn('nota: 10',a['text']);self.assertIn('nota: 10',b['text'])
    def test_prompt_no_reference(self):
        m=messages('Qual prazo?','[A] prazo 10')
        self.assertNotIn('required_ids',json.dumps(m));self.assertNotIn('answer_needles',json.dumps(m))
    def test_truncated_json_refused(self):
        with self.assertRaises(ValueError):parse_response({'choices':[{'finish_reason':'length','message':{'content':'{}'}}]})
    def test_wrong_bool_refused(self):
        obj={'resposta':'a','citacoes':[],'abster':1}
        with self.assertRaises(ValueError):parse_response({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(obj)}}]})
    def test_negative_phrase_false_positive_is_documented(self):
        # Contraprova intencional: a proxy lexical não detecta negação.
        row={'parsed':{'resposta':'O limite não é 10.','citacoes':['A'],'abster':False},'context':{'ids':['A'],'source_restored':False}}
        ref={'required_ids':['A'],'answer_needles':['10'],'expected_abstain':False}
        self.assertTrue(observe(row,ref,{'A':self.d})['automatic_contract_signal'])
    def test_unknown_citation_fails_signal(self):
        row={'parsed':{'resposta':'10','citacoes':['B'],'abster':False},'context':{'ids':['A'],'source_restored':False}}
        ref={'required_ids':['A'],'answer_needles':['10'],'expected_abstain':False}
        self.assertFalse(observe(row,ref,{'A':self.d})['automatic_contract_signal'])
    def test_substring_not_number_hit(self):
        row={'parsed':{'resposta':'110','citacoes':['A'],'abster':False},'context':{'ids':['A'],'source_restored':False}}
        ref={'required_ids':['A'],'answer_needles':['10'],'expected_abstain':False}
        self.assertFalse(observe(row,ref,{'A':self.d})['answer_lexical_signal'])
    def test_source_loss_separate_from_id_delivery(self):
        row={'parsed':None,'context':{'ids':['A'],'source_restored':False}}
        ref={'required_ids':['A'],'answer_needles':['10'],'expected_abstain':False}
        m=observe(row,ref,{'A':dict(self.d,text='nota ausente')})
        self.assertTrue(m['all_required_delivered']);self.assertFalse(m['reference_evidence_available'])
    def test_cluster_identical_contrast(self):
        rows=[dict(phase='primary',family=f,retriever=r,policy='top3',observed={'x':True}) for f in ['a','b'] for r in ['a','b'] for _ in range(3)]
        v=clustered_difference(rows,'a/top3','b/top3','x',n_boot=100)
        self.assertEqual(v['families'],2);self.assertEqual(v['percentile_95'],[0,0])
    def test_plan_reconciles(self):
        q=json.loads((ROOT/'materiais/l23/consultas.json').read_text(encoding='utf-8'))
        p=json.loads((ROOT/'materiais/l23/plano.json').read_text(encoding='utf-8'))
        j=plan_jobs(q,p)
        self.assertEqual(len(j),672);self.assertEqual(len({x['id'] for x in j}),672)
        self.assertEqual(sum(x['phase']=='primary' for x in j),576)
    def test_material_no_unresolvable_gold(self):
        docs={d['id']:d for d in json.loads((ROOT/'materiais/l23/corpus.json').read_text(encoding='utf-8'))['documents']}
        refs=json.loads((ROOT/'materiais/l23/referencias.json').read_text(encoding='utf-8'))
        queries=json.loads((ROOT/'materiais/l23/consultas.json').read_text(encoding='utf-8'))
        for q in queries:
            self.assertTrue(all(eligible(docs[id],q) for id in refs[q['id']]['required_ids']))

if __name__=='__main__':unittest.main()
