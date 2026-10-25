from pathlib import Path
import copy, json, math, tempfile, unittest
import numpy as np
from laboratorios.parte_i.common import load
from laboratorios.parte_vi import ingest, retrieval, store
ROOT=Path(__file__).resolve().parents[1]


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.source=(ROOT/'materiais/parte_vi/fontes/jantar_v2.html').read_text(encoding='utf-8')
        self.doc=ingest.parse(self.source)
        self.ref=load(ROOT/'materiais/parte_vi/referencia_ingestao.json')['documents']['jantar_v2']
    def test_note_loss_detected(self):
        self.assertEqual(ingest.assess(ingest.chunks(self.doc,'body_only'),self.ref)['missing'],['N'])
    def test_all_characters_not_all_relations(self):
        a=ingest.assess(ingest.chunks(self.doc,'independent'),self.ref)
        self.assertEqual((a['recoverable'],a['closed_in_one_chunk']),(3,1))
    def test_linked_conserves_rule_exception(self):
        self.assertEqual(ingest.assess(ingest.chunks(self.doc,'linked'),self.ref)['closed_in_one_chunk'],3)
    def test_dependency_cycle_terminates(self):
        self.assertEqual(len(ingest.chunks(self.doc,'linked')),3)
    def test_missing_dependency_rejected(self):
        with self.assertRaises(ValueError):ingest.parse(self.source.replace('data-requires="N"','data-requires="Z"'))
    def test_duplicate_unit_rejected(self):
        with self.assertRaises(ValueError):ingest.parse(self.source.replace('data-unit="N"','data-unit="T"'))
    def test_missing_license_rejected(self):
        with self.assertRaises(ValueError):ingest.parse(self.source.replace('data-license="autoral-didatico"',''))
    def test_future_ineligible(self):self.assertFalse(ingest.eligible(self.doc['metadata'],'alpha','2026-10-23'))
    def test_start_inclusive(self):self.assertTrue(ingest.eligible(self.doc['metadata'],'alpha','2026-10-24'))
    def test_end_exclusive(self):
        m=dict(self.doc['metadata'],until='2026-10-25');self.assertFalse(ingest.eligible(m,'alpha','2026-10-25'))
    def test_foreign_ineligible(self):self.assertFalse(ingest.eligible(self.doc['metadata'],'beta','2026-10-24'))
    def test_duplicate_preserves_provenance(self):
        c=ingest.catalog([('a',self.doc),('b',self.doc)])
        self.assertEqual(c['duplicates'],[{'source':'b','same_as':'a'}])
    def test_foreign_same_content_not_deduplicated(self):
        other=copy.deepcopy(self.doc);other['metadata']['tenant']='beta'
        self.assertEqual(len(ingest.catalog([('a',self.doc),('b',other)])['retained']),2)
    def test_conflict_quarantines_release(self):
        other=copy.deepcopy(self.doc);other['units'][2]['text']='Plantão: R$ 75'
        self.assertFalse(ingest.catalog([('a',self.doc),('b',other)])['publishable'])
    def test_version_changes_chunk_identity(self):
        old=copy.deepcopy(self.doc);old['metadata']['version']='other'
        self.assertNotEqual(ingest.chunks(self.doc,'linked')[0]['id'],ingest.chunks(old,'linked')[0]['id'])


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.v=np.asarray([[1,0],[.8,.6],[-1,0],[0,1]],dtype=np.float32)
        self.q=np.array([1,0],dtype=np.float32);self.ids=['A','B','C','D']
        self.centers=np.asarray([[1,0],[0,1]],dtype=np.float32);self.labels=np.array([0,1,1,1])
    def test_all_probes_equals_exact(self):
        a=retrieval.approximate(self.v,self.q,range(4),self.ids,self.centers,self.labels,2)
        self.assertEqual(a['ranking'],retrieval.order(self.v,self.q,range(4),self.ids)[:3])
    def test_one_probe_can_lose_neighbor(self):
        a=retrieval.approximate(self.v,self.q,range(4),self.ids,self.centers,self.labels,1)
        self.assertEqual([r['id'] for r in a['ranking']],['A'])
    def test_permission_before_scan(self):
        a=retrieval.approximate(self.v,self.q,[1,2,3],self.ids,self.centers,self.labels,2)
        self.assertNotIn('A',[r['id'] for r in a['ranking']])
    def test_invalid_probe(self):
        with self.assertRaises(ValueError):retrieval.approximate(self.v,self.q,range(4),self.ids,self.centers,self.labels,0)
    def test_ann_denominator(self):self.assertEqual(retrieval.ann_recall(['A'],['A','B','C']),1/3)
    def test_empty_exact_undefined(self):self.assertIsNone(retrieval.ann_recall([],[]))
    def test_unjudged_not_assumed_judged(self):self.assertEqual(retrieval.judged_metrics(['A','B'],{'A':2})['unjudged'],1)
    def test_ndcg_incomplete_judgments_changes(self):
        a=retrieval.judged_metrics(['B','A'],{'A':2})
        b=retrieval.judged_metrics(['B','A'],{'A':2,'B':2})
        self.assertLess(a['ndcg_unjudged_as_zero'],b['ndcg_unjudged_as_zero'])
    def test_duplicate_rank_rejected(self):
        with self.assertRaises(ValueError):retrieval.judged_metrics(['A','A'],{'A':2})
    def test_no_relevance_undefined(self):self.assertIsNone(retrieval.judged_metrics(['A'],{'A':0})['ndcg_unjudged_as_zero'])
    def test_cache_identity_includes_scope(self):
        self.assertNotEqual(retrieval.exact_cache_key('a',1,1,'h','p','m','q'),retrieval.exact_cache_key('b',1,1,'h','p','m','q'))
    def test_same_vector_foreign_cache_rejected(self):
        self.assertFalse(retrieval.semantic_compatible(self.q,self.q,'a','b',1,1))
    def test_same_vector_old_activation_rejected(self):
        self.assertFalse(retrieval.semantic_compatible(self.q,self.q,'a','a',1,2))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'db.sqlite';store.init(self.db)
        self.v1={'id':'v1','version':'1','embedding':'fixed','documents':[{'id':'D','tenant':'a','version':'1','text':'Valor 90'}],'vectors':[[1.,0.]]}
        self.v2={'id':'v2','version':'2','embedding':'fixed','documents':[{'id':'D','tenant':'a','version':'2','text':'Valor 140'}],'vectors':[[1.,0.]]}
        store.stage(self.db,self.v1);store.stage(self.db,self.v2);store.publish(self.db,'v1')
    def tearDown(self):self.tmp.cleanup()
    def request(self):return store.query(self.db,'a','valor?',[1.,0.])
    def test_cache_reused_same_activation(self):
        self.assertFalse(self.request()['response']['cache_hit']);self.assertTrue(self.request()['response']['cache_hit'])
    def test_update_does_not_reuse_old_cache(self):
        self.request();store.publish(self.db,'v2');r=self.request()['response']
        self.assertEqual(r['answer'],'Valor 140');self.assertFalse(r['cache_hit'])
    def test_rollback_increments_epoch(self):
        store.publish(self.db,'v2');store.publish(self.db,'v1');self.assertEqual(store.snapshot(self.db)['epoch'],3)
    def test_inflight_rejected_after_update(self):
        r=store.candidate(store.snapshot(self.db),'a','valor?',[1.,0.]);store.publish(self.db,'v2')
        self.assertFalse(store.deliver(self.db,r)['served'])
    def test_inflight_rejected_after_revoke(self):
        r=store.candidate(store.snapshot(self.db),'a','valor?',[1.,0.]);store.revoke(self.db,'D')
        self.assertFalse(store.deliver(self.db,r)['served'])
    def test_revoked_document_not_retrieved(self):
        store.revoke(self.db,'D');self.assertEqual(self.request()['response']['citations'],[])
    def test_rollback_cannot_resurrect_revocation(self):
        store.revoke(self.db,'D');store.publish(self.db,'v2');store.publish(self.db,'v1')
        self.assertEqual(self.request()['response']['answer'],'SEM EVIDÊNCIA')
    def test_foreign_tenant_cannot_read(self):
        self.assertEqual(store.query(self.db,'b','valor?',[1.,0.])['response']['citations'],[])
    def test_partial_bundle_rejected(self):
        broken=dict(self.v2,id='broken',vectors=[])
        with self.assertRaises(ValueError):store.stage(self.db,broken)
    def test_mixed_versions_rejected(self):
        broken=copy.deepcopy(self.v2);broken['id']='broken';broken['documents'][0]['version']='1'
        with self.assertRaises(ValueError):store.stage(self.db,broken)
    def test_nonfinite_vectors_rejected(self):
        broken=dict(self.v2,id='broken',vectors=[[float('nan'),0]])
        with self.assertRaises(ValueError):store.stage(self.db,broken)
    def test_immutable_bundle(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):store.stage(self.db,self.v1)
    def test_bad_publish_keeps_active(self):
        with self.assertRaises(ValueError):store.publish(self.db,'missing')
        self.assertEqual(store.snapshot(self.db)['bundle']['id'],'v1')
    def test_corrupted_bundle_detected(self):
        with store.connection(self.db) as c:c.execute('UPDATE bundles SET hash=? WHERE id=?',('bad','v1'))
        with self.assertRaises(ValueError):store.snapshot(self.db)
    def test_unsafe_counterexample_serves_stale(self):
        r=store.candidate(store.snapshot(self.db),'a','valor?',[1.,0.]);store.publish(self.db,'v2')
        self.assertEqual(store.deliver(self.db,r,safe=False)['response']['answer'],'Valor 90')


class EvidenceTests(unittest.TestCase):
    def mutate(self, relative, change):
        import shutil
        from laboratorios.parte_i.common import sha
        from laboratorios.parte_vi.verify import verify
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)/'capture';shutil.copytree(ROOT/'output/parte_vi_principal_v01',dest)
            path=dest/relative;obj=load(path);change(obj)
            path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            manifest=load(dest/'manifesto.json');manifest['files'][relative]=sha(path)
            (dest/'manifesto.json').write_text(json.dumps(manifest),encoding='utf-8')
            with self.assertRaises((AssertionError,ValueError)):verify(dest)
    def test_capture_reconciles(self):
        from laboratorios.parte_vi.verify import verify
        self.assertEqual(verify(ROOT/'output/parte_vi_principal_v01')['calls'],192)
    def test_summary_mutation_after_reseal(self):
        self.mutate('generation_summary.json',lambda x:x['qwen/bm25'].__setitem__('signal',24))
    def test_citation_mutation_after_reseal(self):
        relative='raw/F01Q1_bm25_qwen_23.response.json'
        def alter(x):x['choices'][0]['message']['content']='{"resposta":"alterada","citacoes":["FALSA"],"abster":false}'
        self.mutate(relative,alter)
    def test_ann_metric_mutation_after_reseal(self):
        self.mutate('ann.json',lambda x:x['rows'][0]['ann']['8'].__setitem__('recall_exact',.5))
    def test_model_identity_mutation_after_reseal(self):
        self.mutate('smol_resources.json',lambda x:x.__setitem__('model_sha256','0'*64))
    def test_human_judgment_cannot_be_invented(self):
        self.mutate('human_A.json',lambda x:x[0].__setitem__('support',True))
    def test_served_state_mutation_after_reseal(self):
        def alter(x):
            e=next(e for e in x['events'] if e['step']=='safe_inflight')
            e['result']['delivery']['served']=True
        self.mutate('updates.json',alter)
    def test_footnote_metric_mutation_after_reseal(self):
        self.mutate('ingestion.json',lambda x:x['rows'][0]['audit'].__setitem__('recoverable',3))


if __name__=='__main__':unittest.main()
