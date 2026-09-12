import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import pysubs2
import subtitle_core as core
import run_pipeline as runner
import content_filter_pipeline as cuts
import extract_subtitles as extract
import ab_compare
from archive_delivery import archive_delivery


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.src=self.root/'source.ass';self.profile=core.load_profile()
        subs=pysubs2.SSAFile()
        subs.events=[pysubs2.SSAEvent(start=0,end=1500,text='Do not move.'),pysubs2.SSAEvent(start=2500,end=4000,text='Are you ready?')]
        subs.save(self.src);self.subs=subs
        self.context_path=self.root/'context.json'
        core.write_json(self.context_path,{'context_prepared':True,'title':'Authored fixture','media_type':'film','summary':'Two authored test lines.',
            'glossary':{},'relationships':[],'voices':{},'uncertainties':[],'context_sources':[{'kind':'subtitle','reference':'source.ass','finding':'Two authored English dialogue lines.'}],
            'context_checks':{'glossary':'reviewed_none_found','relationships':'reviewed_none_found','voices':'reviewed_none_found','uncertainties':'reviewed_none_found','songs':'reviewed_none_found'},
            'source_language':'en','target_language':'tr','original_audio_language':'','original_audio_status':'unknown','original_audio_evidence':'','songs':[]})
        self.data={'source_sha256':core.file_hash(self.src),'lines':[{'index':0,'tr_text':'Kıpırdama.'},{'index':1,'tr_text':'Hazır mısın?'}]}
    def tearDown(self):self.temp.cleanup()
    def build(self,data=None):return core.build_candidate(self.src,data or self.data,self.profile)
    def job(self):
        job=self.root/'job';runner.prepare(self.src,job,context_path=self.context_path)
        core.write_json(job/'translations/batch-0001.json',self.data)
        return job
    def review(self,job):
        r=core.read_json(job/'review-template.json');r.update(reviewer='test-reviewer',summary='Fixture translations reviewed against authored source.')
        for line in r['lines']:
            line['reviewed']=True
            if line.get('formatting_reviewed') is not None: line['formatting_reviewed']=True
        prefs=core.read_json(core.ROOT/'resources/preferences.json')
        core.write_json(job/'learning_report.json',{
            'learner_profile':prefs['english_learner_profile'],
            'estimated_cefr':{'with_english_subtitles':'B1-B2','listening_without_subtitles':'B1','confidence':'medium','evidence':[{'line_index':0,'source_excerpt':'Do not move.','reason':'Short imperative tests negation.'}]},
            'fit_for_learner':'productive_stretch','learning_points':[{'line_index':1,'source_excerpt':'Are you ready?','meaning_tr':'Hazır mısın?','why_useful':'Common readiness question.'}],
            'personal_assessment':False,
            'limitations':'Fixture-based approximation, not a personal CEFR certificate.'})
        r.update(learning_report_reviewed=True,learning_report_sha256=core.file_hash(job/'learning_report.json'),
                 learning_report_review_summary='CEFR, meanings and reasons checked against the authored source lines.')
        core.write_json(job/'review.json',r)
        return r
    def test_no_mock_llm(self):self.assertFalse(hasattr(runner,'LLMClient'))
    def test_translation_applied(self):self.assertEqual(self.build()[0][0].text,'Kıpırdama.')
    def test_empty_translation_rejected(self):
        d=copy.deepcopy(self.data);d['lines']=[]
        with self.assertRaises(ValueError):self.build(d)
    def test_negative_index_rejected(self):
        d=copy.deepcopy(self.data);d['lines'][0]['index']=-1
        with self.assertRaises(ValueError):self.build(d)
    def test_bool_index_rejected(self):
        d=copy.deepcopy(self.data);d['lines'][0]['index']=False
        with self.assertRaises(ValueError):self.build(d)
    def test_duplicate_rejected(self):
        d=copy.deepcopy(self.data);d['lines'].append(d['lines'][0])
        with self.assertRaises(ValueError):self.build(d)
    def test_stale_source_rejected(self):
        d=copy.deepcopy(self.data);d['source_sha256']='old'
        with self.assertRaises(ValueError):self.build(d)
    def test_unchanged_requires_reason(self):
        d=copy.deepcopy(self.data);d['lines'][0]['tr_text']='Do not move.'
        with self.assertRaises(ValueError):self.build(d)
    def test_inline_tags_stay_at_phrase(self):
        text=r'{\i1}Bu eğik ifade{\i0} normal devam ediyor ve bu cümle kırk karakteri aşıyor.'
        got=core.wrap_text(text)
        self.assertIn(r'{\i1}Bu eğik ifade{\i0}',got)
        self.assertEqual(core.TAG.findall(text),core.TAG.findall(got))
    def test_structured_tag_roundtrip(self):
        source=r'{\i1}Stop{\i0} here.'
        parts=[{'part':0,'source_text':'','tr_text':''},{'part':1,'source_text':'Stop','tr_text':'Dur'},{'part':2,'source_text':' here.','tr_text':' burada.'}]
        self.assertEqual(core.restore_structured_parts(source,parts),r'{\i1}Dur{\i0} burada.')
        with self.assertRaises(ValueError):
            core.translated_text(pysubs2.SSAEvent(text=source),{'index':0,'tr_text':r'⟪ASS:0⟫Dur burada.⟪ASS:1⟫'})
    def test_missing_reordered_parts_rejected(self):
        source=r'{\i1}Stop{\i0}'
        for parts in ([],[{'part':1,'source_text':'','tr_text':''},{'part':0,'source_text':'Stop','tr_text':'Dur'},{'part':2,'source_text':'','tr_text':''}]):
            with self.assertRaises(ValueError):core.restore_structured_parts(source,parts)
    def test_style_slot_cannot_silently_absorb_other_text(self):
        source=r'{\i1}Stop{\i0} here.'
        parts=[{'part':0,'source_text':'','tr_text':''},{'part':1,'source_text':'Stop','tr_text':'Burada dur.'},{'part':2,'source_text':' here.','tr_text':''}]
        with self.assertRaisesRegex(ValueError,'scope_change_reason'):core.restore_structured_parts(source,parts)
    def test_three_line_overflow_reported(self):
        issues,_=core.text_issues(r'bir\Niki\Nüç',1500,self.profile)
        self.assertIn('TOO_MANY_LINES',issues)
    def test_unbreakable_overflow_reported(self):
        issues,_=core.text_issues('a'*90,7000,self.profile)
        self.assertIn('CPL_HIGH',issues)
    def test_timing_preserved_without_evidence(self):
        subs=self.build()[0];self.assertEqual(subs[0].end,1500)
    def test_timing_extends_only_with_window(self):
        s=copy.deepcopy(self.subs);s[0].end=800
        changes=core.optimize_timing(s,{0},self.profile,{'0':{'min_end_ms':800,'max_end_ms':2000,'evidence':'Authored silent gap'}})
        self.assertEqual(s[0].end,1300);self.assertEqual(len(changes),1)
    def test_timing_never_creates_overlap(self):
        s=copy.deepcopy(self.subs);s[0].end=800;s[1].start=1000
        core.optimize_timing(s,{0},self.profile,{'0':{'min_end_ms':800,'max_end_ms':2000,'evidence':'Authored gap'}})
        self.assertLessEqual(s[0].end,920)
    def test_finalize_needs_review(self):
        job=self.job();runner.build(job);self.review(job);(job/'review.json').unlink()
        with self.assertRaises(OSError):runner.finalize(job,self.root/'final.ass')
    def test_review_requires_each_line(self):
        job=self.job();runner.build(job);r=self.review(job);r['lines'].pop();core.write_json(job/'review.json',r)
        with self.assertRaises(ValueError):runner.finalize(job,self.root/'final.ass')
    def test_complete_delivery(self):
        job=self.job();runner.build(job);self.review(job);(job/'content_filter').mkdir();(job/'viewing_breaks').mkdir()
        core.write_json(job/'content_filter/cut-demo.json',{'requested_seconds':[1,2],'applied_seconds':[0,3],'evidence':'Authored fixture cut evidence','context_note':'Authored context note'})
        core.write_json(job/'viewing_breaks/chapters-demo.json',{'status':'beta_chapters_need_playback_review','breaks':[2]})
        out=self.root/'final.ass'
        result=runner.finalize(job,out,archive_root=self.root/'archive')
        self.assertEqual(result['status'],'delivered');self.assertEqual(pysubs2.load(out)[0].text,'Kıpırdama.')
        self.assertTrue(out.with_suffix('.ass.qa.json').exists())
        self.assertTrue(Path(result['archive']).is_dir())
        self.assertTrue((Path(result['archive'])/'archive-manifest.json').is_file())
        self.assertTrue((Path(result['archive'])/'source.ass').is_file())
        self.assertTrue((Path(result['archive'])/'final.ass').is_file())
        self.assertTrue((Path(result['archive'])/'content_filter/cut-demo.json').is_file())
        self.assertTrue((Path(result['archive'])/'viewing_breaks/chapters-demo.json').is_file())
        self.assertEqual(core.read_json(out.with_suffix('.ass.qa.json'))['content_filter_evidence'][0]['file'],'cut-demo.json')
        self.assertEqual(core.read_json(out.with_suffix('.ass.qa.json'))['viewing_break_evidence'][0]['file'],'chapters-demo.json')
        self.assertEqual(runner.status(Path(result['archive']))['missing_batches'],[])
        self.assertTrue((Path(result['archive'])/'translations/batch-0001.json').is_file())
        with self.assertRaisesRegex(ValueError,'read-only'):runner.build(Path(result['archive']))
        self.assertFalse((Path(result['archive'])/'.lock').exists())
        resumed=self.root/'resumed';runner.resume_from_archive(Path(result['archive']),resumed)
        self.assertFalse((resumed/'candidate.ass').exists());self.assertTrue((resumed/'translations/batch-0001.json').exists())
        self.assertTrue((resumed/'viewing_breaks/chapters-demo.json').is_file())
        runner.build(resumed)
        repeated=archive_delivery(job,out,out.with_suffix('.ass.qa.json'),self.root/'archive')
        self.assertEqual(repeated['bundle'],result['archive'])
        archived_final=Path(result['archive'])/'final.ass';archived_final.write_text(archived_final.read_text()+'tamper')
        with self.assertRaisesRegex(ValueError,'integrity violation'):
            archive_delivery(job,out,out.with_suffix('.ass.qa.json'),self.root/'archive')
    def test_english_job_requires_learning_report(self):
        job=self.job();runner.build(job);self.review(job);(job/'learning_report.json').unlink()
        with self.assertRaisesRegex(ValueError,'learning_report'):
            runner.finalize(job,self.root/'final.ass',archive_root=self.root/'archive')
    def test_nonsense_learning_report_rejected(self):
        job=self.job();runner.build(job);self.review(job)
        report=core.read_json(job/'learning_report.json');report['estimated_cefr']['with_english_subtitles']='patates';report['personal_assessment']=True
        core.write_json(job/'learning_report.json',report)
        with self.assertRaises(ValueError):runner.finalize(job,self.root/'final.ass',archive_root=self.root/'archive')
    def test_learning_report_needs_hash_bound_semantic_review(self):
        job=self.job();runner.build(job);review=self.review(job);review['learning_report_reviewed']=False
        core.write_json(job/'review.json',review)
        with self.assertRaisesRegex(ValueError,'semantic review'):
            runner.finalize(job,self.root/'final.ass',archive_root=self.root/'archive')
    def test_context_change_invalidates_review(self):
        job=self.job();runner.build(job);self.review(job);context=core.read_json(job/'context.json');context['summary']='changed';core.write_json(job/'context.json',context)
        with self.assertRaises(ValueError):runner.finalize(job,self.root/'final.ass')
    def test_candidate_tamper_rejected(self):
        job=self.job();runner.build(job);self.review(job)
        p=job/'candidate.ass';p.write_text(p.read_text()+'\n')
        with self.assertRaises(ValueError):runner.finalize(job,self.root/'final.ass')
    def test_technical_fault_not_passed(self):
        self.subs[0].end=100;self.subs.save(self.src);self.data['source_sha256']=core.file_hash(self.src)
        job=self.job();runner.build(job);self.review(job)
        with self.assertRaises(ValueError):runner.finalize(job,self.root/'final.ass')
    def test_overwrite_source_rejected(self):
        job=self.job();runner.build(job);self.review(job)
        with self.assertRaises(ValueError):runner.finalize(job,self.src)
    def test_prepare_resume_does_not_erase(self):
        job=self.job()
        with self.assertRaises(ValueError):runner.prepare(self.src,job)
        self.assertTrue((job/'translations/batch-0001.json').exists())
    def test_handoff_is_bounded_and_excludes_old_chat_like_artifacts(self):
        job=self.root/'handoff-job';runner.prepare(self.src,job,context_path=self.context_path)
        sentinel='OLD_CHAT_AND_FFMPEG_DUMP_MUST_NOT_LEAK'
        (job/'ffmpeg.log').write_text((sentinel+'\n')*5000)
        brief=runner.handoff(job);encoded=json.dumps(brief,ensure_ascii=False)
        self.assertNotIn(sentinel,encoded)
        self.assertNotIn('missing_batches',brief)
        self.assertLess(len(encoded),2000)
        self.assertEqual(brief['next_action'],'translate_next_batch')
        self.assertEqual(brief['next_batch'],'batch-0001.json')
        self.assertEqual(brief['startup_files'],['context.json','profile.json','requests/batch-0001.json'])
        core.write_json(job/'translations/batch-0001.json',self.data)
        self.assertEqual(runner.handoff(job)['next_action'],'build_candidate')
    def test_blank_context_rejected(self):
        blank=self.root/'blank.json';core.write_json(blank,core.read_json(core.ROOT/'resources/context_template.json'))
        with self.assertRaisesRegex(ValueError,'prepared'):runner.prepare(self.src,self.root/'blank-job',context_path=blank)
    def test_token_context_attestation_rejected(self):
        weak=core.read_json(self.context_path);weak['summary']='x';weak['context_sources']=[{'kind':'subtitle','reference':'x','finding':'x'}]
        core.write_json(self.root/'weak.json',weak)
        with self.assertRaises(ValueError):runner.prepare(self.src,self.root/'weak-job',context_path=self.root/'weak.json')
    def test_drawing_passthrough_and_sign_translation(self):
        self.assertEqual(core.classify_line(pysubs2.SSAEvent(text=r'{\p1}m 0 0 l 5 5')),'PASSTHROUGH')
        self.assertEqual(core.role(pysubs2.SSAEvent(text=r'{\an8}EXIT')),'sign')
        self.assertEqual(core.classify_line(pysubs2.SSAEvent(text=r'{\an8}EXIT')),'TRANSLATABLE')
    def test_karaoke_romaji_and_turkish_are_translatable(self):
        event=pysubs2.SSAEvent(start=0,end=3000,text=r'{\k20}空へ',style='OP')
        self.assertEqual(core.classify_line(event),'TRANSLATABLE')
        source=self.root/'song.ass';subs=pysubs2.SSAFile();subs.events=[event];subs.save(source)
        data={'source_sha256':core.file_hash(source),'lines':[{'index':0,'tr_text':'Gökyüzüne','romaji_status':'verified','romaji_source':'Japanese source subtitle',
            'romaji_parts':[{'part':0,'source_text':'','romaji_text':''},{'part':1,'source_text':'空へ','romaji_text':'Sora e'}]}]}
        built,report=core.build_candidate(source,data,self.profile)
        self.assertEqual(built[0].text,r'{\k20}Sora e{\kt0\k0}{\r}\NGökyüzüne')
        self.assertEqual(report['lines'][0]['issues'],[])
        self.assertEqual(core.role(pysubs2.SSAEvent(text='空へ',style='Opening')),'karaoke')
    def test_karaoke_tags_cannot_move_to_turkish(self):
        event=pysubs2.SSAEvent(text=r'{\k20}So{\k30}ra',style='OP')
        with self.assertRaises(ValueError):
            core.translated_text(event,{'tr_text':'Gökyüzü','romaji_status':'verified','romaji_source':'source','romaji_parts':[{'part':0,'source_text':'','romaji_text':'Sora'}]})
    def test_karaoke_romaji_cannot_inject_line_break(self):
        event=pysubs2.SSAEvent(text=r'{\k20}So{\k30}ra',style='OP')
        data={'tr_text':'Gökyüzü','romaji_status':'verified','romaji_source':'source','romaji_parts':[
            {'part':0,'source_text':'','romaji_text':''},{'part':1,'source_text':'So','romaji_text':r'So\N'},
            {'part':2,'source_text':'ra','romaji_text':'ra'}]}
        with self.assertRaisesRegex(ValueError,'line breaks'):core.translated_text(event,data)
    def test_cut_spanning_both_sides(self):
        s=pysubs2.SSAFile();s.events=[pysubs2.SSAEvent(start=1000,end=9000,text='Long event')]
        got=cuts.splice_subtitles(s,[(3000,5000)])
        self.assertEqual([(e.start,e.end) for e in got],[(1000,3000),(3000,7000)])
    def test_overlapping_cuts_count_once(self):
        s=pysubs2.SSAFile();s.events=[pysubs2.SSAEvent(start=10000,end=11000,text='After')]
        got=cuts.splice_subtitles(s,[(2000,5000),(4000,6000)])
        self.assertEqual(got[0].start,6000)
    def test_nested_adjacent_cuts_merge(self):
        self.assertEqual(cuts.normalize_cuts([(2,6),(3,4),(6,7)]),[(2,7,None)])
    def test_unsorted_notes_follow_cuts(self):
        s=pysubs2.SSAFile();s.events=[pysubs2.SSAEvent(start=12000,end=13000,text='End')]
        got=cuts.splice_subtitles(s,[(10000,11000),(2000,3000)],['LATE','EARLY'])
        notes=[e for e in got if e.style=='CutContext']
        self.assertIn('EARLY',notes[0].text);self.assertIn('LATE',notes[1].text)
    def test_invalid_cut_ranges_rejected(self):
        for c in [(-1,2),(2,2),(3,2),(1,float('nan')),(1,50)]:
            with self.assertRaises(ValueError):cuts.normalize_cuts([c],10)
    def test_production_cut_requires_review_evidence(self):
        with self.assertRaisesRegex(ValueError,'evidence'):cuts.reviewed_cut_requests([{'start':1,'end':2,'reviewed_by':'agent'}],10)
    def test_production_cut_requires_authorized_policy_and_reason(self):
        row={'start':1,'end':2,'evidence':'This authored interval was visually inspected','reviewed_by':'agent'}
        with self.assertRaisesRegex(ValueError,'policy'):
            cuts.reviewed_cut_requests([row],10,require_policy=True)
        spec={'policy':{'authorized':True,'requested_by':'user','instruction':'Remove the explicitly selected scene after review.',
                        'source_reference':'Authored test instruction'},'cuts':[row]}
        with self.assertRaisesRegex(ValueError,'category'):
            cuts.reviewed_cut_requests(spec,10,require_policy=True)
    def test_decode_warning_with_success_code_is_reportable_not_failure(self):
        completed=subprocess.CompletedProcess([],0,'','non monotonically increasing dts')
        with patch.object(cuts.subprocess,'run',return_value=completed):
            self.assertIn('non monotonically',cuts.decode_window('fixture.mkv',1.0))
    def test_empty_cut_preserves_metadata(self):
        self.subs.info['Title']='Example';self.subs.fonts_opaque={'demo':['AAAA']}
        got=cuts.splice_subtitles(self.subs,[])
        self.assertEqual(got.info,self.subs.info);self.assertEqual(got.fonts_opaque,self.subs.fonts_opaque)
    def test_ambiguous_stream_fails(self):
        streams=[{'index':i,'codec_name':'ass','tags':{'language':'eng'}} for i in (2,3)]
        with self.assertRaises(ValueError):extract.select_stream(streams)
        self.assertEqual(extract.select_stream(streams,index=3)['index'],3)
    def test_unknown_language_not_guessed(self):
        with self.assertRaises(ValueError):extract.select_stream([{'index':1,'codec_name':'ass','tags':{}}])
    def test_forced_signs_excluded(self):
        streams=[{'index':1,'codec_name':'ass','tags':{'language':'eng','title':'Signs'}},{'index':2,'codec_name':'ass','tags':{'language':'eng','title':'Full'}}]
        self.assertEqual(extract.select_stream(streams)['index'],2)
    def test_blind_empty_and_matching(self):
        other=self.root/'tr.ass';sub=self.build()[0];sub.save(other)
        public,key=ab_compare.compare_subtitles(self.src,other,2,42)
        self.assertEqual(len(public['pairs']),2);self.assertEqual(len(key),2)
        self.assertNotIn(str(self.src),json.dumps(public))
        empty=self.root/'empty.ass';pysubs2.SSAFile().save(empty)
        self.assertEqual(ab_compare.compare_subtitles(self.src,empty)[0]['matched_pairs'],0)

if __name__=='__main__':unittest.main()
