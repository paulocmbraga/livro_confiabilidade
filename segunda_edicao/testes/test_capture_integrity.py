"""Muta cópias da captura real de engenharia; nunca a evidência original."""
import json,shutil,tempfile,unittest
from pathlib import Path
from laboratorios.l23.campaign import ROOT,load,seal,verify

class CaptureIntegrity(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.out=Path(self.tmp.name)/'capture'
        shutil.copytree(ROOT/'output/l23_smoke_v01',self.out)
    def tearDown(self):self.tmp.cleanup()
    def edit(self,rel,fn):
        p=self.out/rel;data=load(p);fn(data)
        p.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    def first(self):return next((self.out/'raw').glob('*.json')).relative_to(self.out)
    def test_original_reconciles(self):self.assertEqual(verify(self.out)['calls'],6)
    def test_hash_change_rejected(self):
        self.edit('state.json',lambda d:d.update(observed_calls=5))
        with self.assertRaisesRegex(ValueError,'Hash'):verify(self.out)
    def test_resealed_raw_change_rejected(self):
        def mutate(d):d['response']['choices'][0]['message']['content']='{"resposta":"alterada","citacoes":[],"abster":true}'
        self.edit(self.first(),mutate);seal(self.out)
        with self.assertRaisesRegex(ValueError,'Observação'):verify(self.out)
    def test_resealed_summary_change_rejected(self):
        self.edit('results.json',lambda d:d['variants']['bm25/top1'].update(calls=99));seal(self.out)
        with self.assertRaisesRegex(ValueError,'Resumo'):verify(self.out)
    def test_extra_file_rejected(self):
        (self.out/'extra.txt').write_text('extra')
        with self.assertRaisesRegex(ValueError,'extra'):verify(self.out)
    def test_missing_attempt_even_resealed(self):
        (self.out/self.first()).unlink();seal(self.out)
        with self.assertRaises(FileNotFoundError):verify(self.out)
    def test_resealed_ranking_change_rejected(self):
        def mutate(d):d[0]['bm25'][0]['score']+=1
        self.edit('retrieval.json',mutate);seal(self.out)
        with self.assertRaisesRegex(ValueError,'BM25'):verify(self.out)
    def test_roundoff_preserves_identity_and_order(self):
        def mutate(d):d[0]['bm25'][0]['score']+=1e-15
        self.edit('retrieval.json',mutate);seal(self.out)
        self.assertEqual(verify(self.out)['calls'],6)
    def test_pending_even_resealed(self):
        shutil.copyfile(self.out/self.first(),self.out/'raw/unresolved.pending.json');seal(self.out)
        with self.assertRaisesRegex(ValueError,'Denominador'):verify(self.out)
    def test_incomplete_even_resealed(self):
        self.edit('state.json',lambda d:d.update(status='incomplete'));seal(self.out)
        with self.assertRaisesRegex(ValueError,'incompleta'):verify(self.out)
    def test_stopped_server_required(self):
        self.edit('generation_resources.json',lambda d:d.update(process_ended=False));seal(self.out)
        with self.assertRaisesRegex(ValueError,'encerramento'):verify(self.out)

if __name__=='__main__':unittest.main()
