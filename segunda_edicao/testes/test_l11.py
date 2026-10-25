"""Contratos, seletividade, isolamento e mutações da captura: sem novas inferências."""
import copy,csv,json,math,shutil,tempfile,unittest
from pathlib import Path
from laboratorios.l11.core import *
from laboratorios.l11.verify import verify
from laboratorios.l11.human import policy_curve,references,read_form

def response(text='{"choice":"A","confidence":90,"reason":"Fonte FER-E."}',finish='stop'):
    return {'choices':[{'finish_reason':finish,'message':{'content':text}}]}

def good(winner='X',confidence=.9):return dict(valid=True,winner=winner,confidence=confidence)

class Contract(unittest.TestCase):
    def test_position_normalization(self):
        self.assertEqual(parse(response(),'AB')['winner'],'X');self.assertEqual(parse(response(),'BA')['winner'],'Y')
    def test_tie_is_not_invalid(self):self.assertEqual(parse(response('{"choice":"tie","confidence":50,"reason":"iguais"}'),'AB')['winner'],'tie')
    def test_review_is_not_tie(self):self.assertEqual(parse(response('{"choice":"review","confidence":0,"reason":"falta"}'),'AB')['winner'],'review')
    def test_truncated(self):self.assertFalse(parse(response(finish='length'),'AB')['valid'])
    def test_duplicate_key(self):self.assertFalse(parse(response('{"choice":"A","choice":"B","confidence":90,"reason":"x"}'),'AB')['valid'])
    def test_boolean_score(self):self.assertFalse(parse(response('{"choice":"A","confidence":true,"reason":"x"}'),'AB')['valid'])
    def test_nan(self):self.assertFalse(parse(response('{"choice":"A","confidence":NaN,"reason":"x"}'),'AB')['valid'])
    def test_range(self):self.assertFalse(parse(response('{"choice":"A","confidence":101,"reason":"x"}'),'AB')['valid'])
    def test_empty_reason(self):self.assertFalse(parse(response('{"choice":"A","confidence":90,"reason":" "}'),'AB')['valid'])
    def test_extra_field(self):self.assertFalse(parse(response('{"choice":"A","confidence":90,"reason":"x","extra":1}'),'AB')['valid'])
    def test_transport(self):self.assertEqual(parse(None,'AB',{'type':'Timeout'})['problem'],'transport')
    def test_multiple_choices(self):
        r=response();r['choices']*=2;self.assertFalse(parse(r,'AB')['valid'])
    def test_no_json_repair(self):self.assertFalse(parse(response('```json\n{}\n```'),'AB')['valid'])

class Policy(unittest.TestCase):
    def test_full_gate(self):self.assertEqual(gate([good()]*4,'standard')['winner'],'X')
    def test_invalid(self):self.assertIsNone(gate([good()]*3+[dict(valid=False)],'standard')['winner'])
    def test_unstable(self):self.assertEqual(gate([good()]*3+[good('Y')],'standard')['reason'],'unstable')
    def test_high_risk(self):self.assertEqual(gate([good()]*4,'high')['reason'],'risk')
    def test_tie(self):self.assertEqual(gate([good('tie')]*4,'standard')['reason'],'tie_or_review')
    def test_score(self):self.assertEqual(gate([good(confidence=.79)]*4,'standard')['reason'],'score')
    def test_incomplete(self):
        with self.assertRaises(ValueError):gate([good()]*3,'standard')
    def test_threshold(self):
        with self.assertRaises(ValueError):gate([good()]*4,'standard',float('nan'))
    def test_brier(self):self.assertAlmostEqual(brier([.9,.9],[1,0]),.41)
    def test_no_labels(self):
        with self.assertRaises(ValueError):brier([],[])
    def test_zero_denominator(self):self.assertIsNone(wilson(0,0))
    def test_zero_errors_not_certainty(self):self.assertGreater(wilson(0,20)[1],.15)
    def test_test_partition_rejected(self):
        with self.assertRaises(ValueError):policy_curve([],[{'id':'P','split':'test'}],{'P':'X'})
    def test_missing_reference_rejected(self):
        with self.assertRaises(ValueError):policy_curve([],[{'id':'P','split':'calibration'}],{'P':None})
    def test_calibration_only(self):
        ps=[dict(id=str(i),split='calibration',risk='standard') for i in range(4)]
        rs=[dict(trial=dict(pair=p['id'],mode='base'),parsed=good()) for p in ps for _ in range(4)]
        fit=policy_curve(rs,ps,{p['id']:'X' for p in ps});self.assertEqual(fit['threshold'],.5)
    def test_no_eligible_threshold(self):
        ps=[dict(id='P',split='calibration',risk='standard')]
        rs=[dict(trial=dict(pair='P',mode='base'),parsed=good()) for _ in range(4)]
        self.assertIsNone(policy_curve(rs,ps,{'P':'Y'})['threshold'])

class Design(unittest.TestCase):
    def setUp(self):self.pairs=load(MATERIALS/'pares.json')
    def test_cardinality(self):
        rows=schedule(self.pairs);self.assertEqual(len(rows),400);self.assertEqual(len({r['id'] for r in rows}),400)
    def test_cells(self):
        rows=schedule(self.pairs);self.assertEqual(sum(r['mode']=='base' for r in rows),320)
    def test_format_preserves_text(self):
        p=self.pairs[0];self.assertEqual(presented(p,'AB','format')[1]['text'].strip(),p['candidates'][1]['text'].strip())
    def test_attack_targets_canonical_y(self):
        p=self.pairs[0];self.assertIn('NOTA AO AVALIADOR',presented(p,'BA','injection')[0]['text'])
    def test_no_labels_in_prompt(self):
        p=self.pairs[0];req=request(p,schedule([p])[0],(MATERIALS/'rubrica.txt').read_text(encoding='utf-8'))
        self.assertNotIn('bm25',json.dumps(req));self.assertNotIn('calibration',json.dumps(req))
    def test_family_isolation(self):
        a={p['family'] for p in self.pairs if p['split']=='calibration'}
        b={p['family'] for p in self.pairs if p['split']=='test'};self.assertFalse(a&b)
    def test_human_pending(self):
        with self.assertRaises(ValueError):references(ROOT/'output/avaliacao_humana_l11_v01')

class Integrity(unittest.TestCase):
    def mutate(self,fn,pattern):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'capture';shutil.copytree(ROOT/'output/l11_engenharia_v01',dest)
            fn(dest)
            manifest=load(dest/'manifesto.json');manifest['files']={p.relative_to(dest).as_posix():sha(p) for p in dest.rglob('*') if p.is_file() and p.name!='manifesto.json'}
            save(dest/'manifesto.json',manifest)
            with self.assertRaisesRegex(AssertionError,pattern):verify(dest)
    def test_original(self):self.assertEqual(verify(ROOT/'output/l11_engenharia_v01')['calls'],4)
    def test_rehashed_wrong_request(self):
        def change(d):
            p=next((d/'raw').glob('*.json'));r=load(p);r['request']['seed']=999;save(p,r)
        self.mutate(change,'requisição')
    def test_rehashed_fake_winner(self):
        def change(d):
            p=next((d/'raw').glob('*.json'));r=load(p);r['parsed']['winner']='fabricado';save(p,r)
        self.mutate(change,'parser')
    def test_rehashed_missing_trial(self):
        self.mutate(lambda d:next((d/'raw').glob('*.json')).unlink(),'')
    def test_rehashed_tokens(self):
        def change(d):
            p=next((d/'raw').glob('*.json'));r=load(p);r['response']['usage']['total_tokens']+=1;save(p,r)
        self.mutate(change,'tokens')

class HumanIngestion(unittest.TestCase):
    """Rótulos artificiais temporários testam software; nunca entram no pacote real."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.d=Path(self.temp.name)/'packet'
        shutil.copytree(ROOT/'output/avaliacao_humana_l11_v01',self.d)
        people={'collected':True,'reviewers':[dict(pseudonym='fixture-'+str(i),experience='fixture',
            relationship_to_development='teste sintético',independent_collection_confirmed=True) for i in (1,2)]}
        save(self.d/'participantes_pendente.json',people)
        for name in ('revisor_1','revisor_2'):
            f=self.d/name/'formulario.csv'
            with f.open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
            for r in rows:r.update(choice='X',support_X='yes',support_Y='no',reason='Fixture de teste.',evidence_ids='F',minutes='1')
            self.write(f,rows)
    def tearDown(self):self.temp.cleanup()
    def write(self,f,rows):
        with f.open('w',encoding='utf-8',newline='') as stream:
            w=csv.DictWriter(stream,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    def test_complete_import(self):
        refs,diff=references(self.d);self.assertEqual(len(refs),40);self.assertFalse(diff)
    def test_disagreement_stays_unknown(self):
        f=self.d/'revisor_2/formulario.csv'
        with f.open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
        rows[0]['choice']='Y';self.write(f,rows)
        refs,diff=references(self.d);self.assertEqual(len(diff),1);self.assertIsNone(refs[diff[0]])
    def test_adjudication_preserves_inputs(self):
        f=self.d/'revisor_2/formulario.csv'
        with f.open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
        rows[0]['choice']='Y';self.write(f,rows);h=sha(f)
        refs,diff=references(self.d);a=self.d/'adjudication.json'
        save(a,{diff[0]:dict(choice='tie',reason='Fixture.',adjudicator='fixture-3')})
        refs,still_diff=references(self.d,a);self.assertEqual(refs[diff[0]],'tie');self.assertEqual(sha(f),h)
        self.assertEqual(diff,still_diff)
    def test_duplicate_participant(self):
        f=self.d/'participantes_pendente.json';v=load(f);v['reviewers'][1]['pseudonym']=v['reviewers'][0]['pseudonym'];save(f,v)
        with self.assertRaises(ValueError):references(self.d)
    def test_missing_row(self):
        f=self.d/'revisor_2/formulario.csv'
        with f.open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
        self.write(f,rows[:-1])
        with self.assertRaises(ValueError):references(self.d)
    def test_nan_time(self):
        f=self.d/'revisor_2/formulario.csv'
        with f.open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
        rows[0]['minutes']='nan';self.write(f,rows)
        with self.assertRaises(ValueError):references(self.d)

if __name__=='__main__':unittest.main()
