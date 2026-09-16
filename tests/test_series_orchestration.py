"""Counterexamples for bounded coordinator receipts and versioned series context."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import pysubs2
import subtitle_core as core
import run_pipeline as runner
import series_context as series


class SeriesOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'source.ass';subs=pysubs2.SSAFile()
        subs.events=[pysubs2.SSAEvent(start=0,end=1800,text='SERIES_SOURCE_SENTINEL')];subs.save(self.source)
        self.source_sha=core.file_hash(self.source)
        self.context=self.root/'episode-context.json'
        core.write_json(self.context,{'context_prepared':True,'title':'Episode fixture','media_type':'anime',
            'summary':'An authored episode fixture used to test bounded orchestration receipts.',
            'glossary':{},'relationships':[],'voices':{},'uncertainties':[],'songs':[],
            'context_sources':[{'kind':'subtitle','reference':'source.ass','finding':'One authored fixture dialogue event is present.'}],
            'context_checks':{k:'reviewed_none_found' for k in ('glossary','relationships','voices','uncertainties','songs')},
            'source_language':'de','target_language':'tr','original_audio_language':'ja','original_audio_status':'verified',
            'original_audio_evidence':'The authored anime fixture declares Japanese original audio.'})
        self.series_root=self.root/'series'
        series.init_series(self.series_root,'fixture-series','Fixture Series')

    def tearDown(self): self.temp.cleanup()

    def current_series_path(self):
        return self.series_root/series.inspect_series(self.series_root)['current_file']

    def job(self,translated=False):
        job=self.root/'job'
        runner.prepare(self.source,job,context_path=self.context,series_context_path=self.current_series_path(),episode_id='S01E01')
        # Series snapshot regressions model pre-marker jobs; strict coverage is
        # exercised by the dedicated pipeline forward-flow fixture.
        meta=core.read_json(job/'job.json');meta.pop('orchestration_required');core.write_json(job/'job.json',meta)
        (job/'orchestration.json').unlink()
        if translated:
            request=core.read_json(job/'requests/batch-0001.json');response=request['response_shape']
            response['lines'][0]['tr_text']='Dizi çevirisi.'
            core.write_json(job/'translations/batch-0001.json',response)
        return job

    def update_payload(self,base_path,preferred='Klasik Edebiyat Kulübü',changes=None):
        base=core.read_json(base_path);base_sha=core.file_hash(base_path);nxt=copy.deepcopy(base)
        nxt.update(revision=base['revision']+1,parent_sha256=base_sha,through_episode='S01E01')
        nxt['glossary']['classic-lit-club']={'preferred_tr':preferred,'aliases':['Classic Lit Club'],
            'note':'Series-wide club name.','state':'active','scope':'series','evidence':[
                {'episode_id':'S01E01','source_sha256':self.source_sha,'line_indices':[0],'kind':'subtitle_line_ids'}]}
        return {'schema_version':1,'series_id':base['series_id'],'episode_id':'S01E01','base_revision':base['revision'],
                'base_sha256':base_sha,'reviewed_by':'context-curator','review_summary':'Series term checked against authored fixture line identifiers.',
                'changes':changes or [],'next_context':nxt}

    def test_series_revision_is_hash_chained_and_stale_update_is_rejected(self):
        base=self.current_series_path();update=self.root/'update.json';core.write_json(update,self.update_payload(base))
        advanced=series.advance_series(self.series_root,update)
        self.assertEqual(advanced['current_revision'],1);self.assertEqual(advanced['counts']['glossary'],1)
        self.assertNotIn('Classic Lit Club',json.dumps(advanced,ensure_ascii=False))
        with self.assertRaisesRegex(ValueError,'Stale'): series.advance_series(self.series_root,update)

    def test_existing_series_entry_cannot_change_without_exact_reason(self):
        base=self.current_series_path();first=self.root/'first.json';core.write_json(first,self.update_payload(base));series.advance_series(self.series_root,first)
        current=self.current_series_path();payload=self.update_payload(current,preferred='Eski Edebiyat Kulübü')
        with self.assertRaisesRegex(ValueError,'exact prior hashes'): series.validate_update(payload,core.read_json(current),core.file_hash(current))

    def test_normalized_glossary_alias_collision_is_rejected(self):
        context=core.read_json(self.current_series_path())
        evidence=[{'episode_id':'S01E01','source_sha256':self.source_sha,'line_indices':[0],'kind':'subtitle_line_ids'}]
        context['glossary']={
            'first':{'preferred_tr':'İlk','aliases':['Classic Lit Club'],'note':'First meaning.','state':'active','scope':'series','evidence':evidence},
            'second':{'preferred_tr':'İkinci','aliases':[' classic  lit club '],'note':'Second meaning.','state':'active','scope':'series','evidence':evidence},
        }
        with self.assertRaisesRegex(ValueError,'alias collision'):
            series.validate_series_context(context)

    def test_translation_requires_episode_profile_and_series_bindings(self):
        job=self.job();legacy={'source_sha256':self.source_sha,'lines':[{'index':0,'tr_text':'Dizi çevirisi.'}]}
        core.write_json(job/'translations/batch-0001.json',legacy)
        with self.assertRaisesRegex(ValueError,'binding'): runner.collect(job,core.read_json(job/'job.json'))
        request=core.read_json(job/'requests/batch-0001.json');response=request['response_shape'];response['lines'][0]['tr_text']='Dizi çevirisi.'
        core.write_json(job/'translations/batch-0001.json',response)
        self.assertEqual(runner.create_receipt(job,'translation')['status'],'complete')
        episode=core.read_json(job/'context.json');episode['summary']+=' changed';core.write_json(job/'context.json',episode)
        with self.assertRaisesRegex(ValueError,'inputs changed'): runner.load_job(job)

    def test_agent_claim_cannot_make_missing_work_complete_or_leak_payloads(self):
        job=self.job();(job/'worker-final.txt').write_text(('AGENT_FINAL_SENTINEL\n')*5000)
        wrapper=runner.create_receipt(job,'translation');receipt=core.read_json(wrapper['receipt_path'])
        encoded=json.dumps(receipt,ensure_ascii=False)
        self.assertEqual(receipt['status'],'incomplete');self.assertEqual(receipt['error_code'],'MISSING_BATCHES')
        self.assertNotIn('AGENT_FINAL_SENTINEL',encoded);self.assertNotIn('SERIES_SOURCE_SENTINEL',encoded)
        self.assertLess(len(encoded),2000)

    def test_stale_present_batch_receipt_is_invalid_not_complete(self):
        job=self.job();core.write_json(job/'translations/batch-0001.json',{
            'source_sha256':self.source_sha,'lines':[{'index':0,'tr_text':'Dizi çevirisi.'}]})
        wrapper=runner.create_receipt(job,'translation');receipt=core.read_json(wrapper['receipt_path'])
        self.assertEqual(receipt['status'],'invalid');self.assertEqual(receipt['error_code'],'INVALID_BATCH')

    def test_old_episode_keeps_its_snapshot_after_series_advances(self):
        job=self.job();snapshot_sha=core.file_hash(job/'series_context.json')
        update=self.root/'after-prepare.json';core.write_json(update,self.update_payload(self.current_series_path()))
        series.advance_series(self.series_root,update)
        self.assertEqual(core.file_hash(job/'series_context.json'),snapshot_sha)
        loaded_meta,_,_=runner.load_job(job)
        self.assertEqual(loaded_meta['translation_bindings']['series_context_sha256'],snapshot_sha)

    def test_episode_archive_keeps_exact_series_snapshot_and_receipts(self):
        job=self.job(translated=True);runner.create_receipt(job,'translation');runner.build(job)
        review=core.read_json(job/'review-template.json');review.update(reviewer='separate-review-worker',mode='independent_agent',
            summary='Separate fixture reviewer checked the final candidate against its authored source event.')
        for row in review['lines']:
            row['reviewed']=True
            if row['formatting_reviewed'] is not None: row['formatting_reviewed']=True
        core.write_json(job/'review.json',review);runner.create_receipt(job,'review')
        output=self.root/'final.ass';result=runner.finalize(job,output,archive_root=self.root/'archive');bundle=Path(result['archive'])
        self.assertTrue((bundle/'series_context.json').is_file());self.assertTrue((bundle/'receipts/translation.json').is_file())
        self.assertEqual(core.file_hash(bundle/'series_context.json'),core.file_hash(job/'series_context.json'))


if __name__=='__main__': unittest.main()
