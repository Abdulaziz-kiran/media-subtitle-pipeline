import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import pysubs2
from content_filter_pipeline import sanitize_movie,probe,persist_cut_evidence
from extract_subtitles import extract_subtitle,select_stream,subtitle_streams,inspect_stream_content
from mux_mkv import mux_single,choose_original_audio,inspect_fonts
from verify_render_qa import render_samples,find_renderer


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg/FFprobe unavailable')
class MediaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.ass=cls.root/'source.ass';s=pysubs2.SSAFile();s.info.update(PlayResX='320',PlayResY='180')
        s.events=[pysubs2.SSAEvent(start=100,end=2800,text='A simple source sentence.')];s.save(cls.ass)
        cls.video=cls.root/'source.mkv'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=25:duration=3',
                        '-f','lavfi','-i','sine=duration=3:sample_rate=48000:frequency=440',
                        '-f','lavfi','-i','sine=duration=3:sample_rate=48000:frequency=880','-i',str(cls.ass),
                        '-map','0:v','-map','1:a','-map','2:a','-map','3:s',
                        '-c:v','mpeg4','-g','25','-bf','0','-c:a','pcm_s16le','-c:s','ass','-metadata:s:a:0','language=eng',
                        '-metadata:s:a:1','language=jpn',
                        '-metadata:s:s:0','language=eng','-metadata:s:s:0','title=Full',str(cls.video)],check=True,capture_output=True,text=True)
        from test_independent_audit import context
        import run_pipeline
        cls.cut_job=cls.root/'cut-job'
        ctx=cls.root/'prepared-context.json';ctx.write_text(json.dumps(context('en')))
        run_pipeline.prepare(cls.ass,cls.cut_job,context_path=ctx)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def cut_spec(self,start,end,evidence,context_note=None,category='fixture-scene'):
        row={'start':start,'end':end,'category':category,
             'cut_reason':'The authored fixture policy requires this interval to be removed.',
             'evidence':evidence,'reviewed_by':'test'}
        if context_note is not None: row['context_note']=context_note
        return {'policy':{'authorized':True,'requested_by':'user',
                          'instruction':'Remove the explicitly selected fixture intervals after review.',
                          'source_reference':'Authored integration-test instruction'},'cuts':[row]}
    def test_real_extract(self):
        s=select_stream(subtitle_streams(self.video));out=self.root/'extracted.ass'
        extract_subtitle(self.video,s['index'],out)
        self.assertEqual(pysubs2.load(out)[0].text,'A simple source sentence.')
    def test_content_inspection_is_grounded(self):
        report=inspect_stream_content(self.video,subtitle_streams(self.video))
        self.assertEqual(report[0]['event_count'],1)
        self.assertEqual(report[0]['samples'],['A simple source sentence.'])
    def test_real_mux_preserves_streams(self):
        out=self.root/'muxed.mkv';context=self.root/'anime-context.json'
        context.write_text(json.dumps({'media_type':'anime'}))
        result=mux_single(self.video,self.ass,out,context_path=context)
        streams=probe(out)['streams'];subs=[s for s in streams if s['codec_type']=='subtitle'];audio=[s for s in streams if s['codec_type']=='audio']
        self.assertEqual(len(streams),7);self.assertEqual([s.get('disposition',{}).get('default') for s in subs],[0,1])
        self.assertEqual([s.get('disposition',{}).get('default') for s in audio],[0,1])
        self.assertEqual(result['default_audio_language'],'jpn')
        self.assertEqual(result['max_interleave_delta_us'],0)
    def test_mux_preserves_previously_applied_viewing_chapters(self):
        metadata=self.root/'chapters.ffmeta';metadata.write_text(';FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1500\ntitle=İzleme Bölümü 1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=1500\nEND=3000\ntitle=İzleme Bölümü 2\n')
        chaptered=self.root/'chaptered-source.mkv'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(self.video),'-f','ffmetadata','-i',str(metadata),
                        '-map','0','-map_metadata','0','-map_chapters','1','-c','copy',str(chaptered)],check=True,capture_output=True,text=True)
        context=self.root/'chaptered-context.json';context.write_text(json.dumps({'media_type':'anime'}))
        output=self.root/'chaptered-muxed.mkv';mux_single(chaptered,self.ass,output,context_path=context)
        before=probe(chaptered)['chapters'];after=probe(output)['chapters']
        self.assertEqual([(row['start_time'],row['end_time'],row.get('tags',{}).get('title')) for row in after],
                         [(row['start_time'],row['end_time'],row.get('tags',{}).get('title')) for row in before])
    def test_original_audio_selection(self):
        audio=[{'tags':{'language':'eng'},'disposition':{}},{'tags':{'language':'jpn'},'disposition':{}}]
        self.assertEqual(choose_original_audio(audio,context={'media_type':'anime'})[:2],(1,'jpn'))
        audio[0]['disposition']['original']=1
        self.assertEqual(choose_original_audio(audio,context={'media_type':'anime'})[:2],(1,'jpn'))
        self.assertEqual(choose_original_audio(audio,context={'media_type':'anime','original_audio_language':'eng','original_audio_status':'unknown'})[:2],(1,'jpn'))
        self.assertEqual(choose_original_audio(audio,context={'media_type':'film','original_audio_language':'eng','original_audio_status':'verified','original_audio_evidence':'Studio metadata'})[:2],(0,'eng'))
        self.assertEqual(choose_original_audio(audio,context={'original_audio_language':'ja','original_audio_status':'verified','original_audio_evidence':'Studio metadata'})[:2],(1,'jpn'))
        audio[0]['disposition'].clear()
        with self.assertRaises(ValueError):choose_original_audio(audio)
    def test_font_family_comes_from_internal_metadata(self):
        source=Path(__file__).resolve().parents[1]/'resources/fonts/SourceSans3-Regular.otf'
        self.assertEqual(inspect_fonts([source],'Source Sans 3')[0]['family'],'Source Sans 3')
        fake=self.root/'SourceSans3-Regular-fake.otf';data=source.read_bytes()
        data=data.replace('Source Sans 3'.encode('utf-16-be'),'DejaVu Sans X'.encode('utf-16-be')).replace(b'Source Sans 3',b'DejaVu Sans X')
        fake.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'family'):inspect_fonts([fake],'Source Sans 3')
    def test_real_cut_duration_and_events(self):
        out=self.root/'cut.mkv';ass=self.root/'cut.ass'
        r=sanitize_movie(self.video,self.ass,self.cut_spec(1,2,'Authored fixture interval inspected','A short authored transition was removed.'),out,ass,
                         job_path=self.cut_job,archive_root=self.root/'archive')
        self.assertLess(abs(r['checks']['duration_actual']-2),0.1)
        self.assertTrue(r['checks']['postprocess_av_payloads_preserved'])
        self.assertEqual(len(pysubs2.load(ass)),3)
        archived=Path(r['evidence_archive']['archive_bundle'])/'cut-report.json'
        self.assertTrue(archived.is_file());stored=json.loads(archived.read_text())
        self.assertTrue(stored['plan']['policy']['authorized'])
        self.assertEqual(stored['plan']['cut_reviews'][0]['category'],'fixture-scene')
        self.assertEqual(stored['plan']['cut_reviews'][0]['reviewed_by'],'test')
        self.assertEqual(stored['plan']['cut_reviews'][0]['context_note'],'A short authored transition was removed.')
        archived.write_text(archived.read_text()+'tamper')
        with self.assertRaisesRegex(ValueError,'integrity violation'):
            persist_cut_evidence(self.cut_job,stored,self.root/'archive')
    def test_h264_bframe_cut_uses_keyframe_segmenter(self):
        video=self.root/'bframes.mkv'
        made=subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=24:duration=6',
            '-f','lavfi','-i','sine=duration=6:sample_rate=48000','-c:v','libx264','-g','48','-bf','3','-c:a','aac',str(video)],capture_output=True,text=True)
        if made.returncode: self.skipTest('libx264 unavailable')
        out=self.root/'bframes-cut.mkv';ass=self.root/'bframes-cut.ass'
        r=sanitize_movie(video,self.ass,self.cut_spec(2,4,'Synthetic B-frame interval inspected'),out,ass,
                         job_path=self.cut_job,archive_root=self.root/'archive')
        self.assertLess(abs(r['checks']['duration_actual']-r['checks']['duration_expected']),0.1)
    def test_cut_is_not_left_published_when_evidence_archive_fails(self):
        out=self.root/'archive-failure.mkv';ass=self.root/'archive-failure.ass'
        with patch('content_filter_pipeline.persist_cut_evidence',side_effect=ValueError('archive unavailable')):
            with self.assertRaisesRegex(ValueError,'archive unavailable'):
                sanitize_movie(self.video,self.ass,self.cut_spec(1,2,'Archive failure interval was visually inspected'),out,ass,
                               job_path=self.cut_job,archive_root=self.root/'archive')
        self.assertFalse(out.exists());self.assertFalse(ass.exists());self.assertFalse(out.with_suffix('.cut-report.json').exists())
    def test_h265_open_gop_cut_has_lossless_video_fallback(self):
        video=self.root/'open-gop-h265.mkv'
        made=subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=24:duration=8',
            '-f','lavfi','-i','sine=duration=8:sample_rate=48000','-c:v','libx265','-x265-params','keyint=48:min-keyint=48:scenecut=0:bframes=4:log-level=error',
            '-c:a','aac',str(video)],capture_output=True,text=True)
        if made.returncode: self.skipTest('libx265 unavailable')
        out=self.root/'open-gop-h265-cut.mkv';ass=self.root/'open-gop-h265-cut.ass'
        r=sanitize_movie(video,self.ass,self.cut_spec(3.1,4.9,'Synthetic open-GOP H265 interval inspected'),out,ass,
                         job_path=self.cut_job,archive_root=self.root/'archive')
        self.assertEqual(r['checks']['video_processing'],'lossless_reencode')
        self.assertTrue(r['checks']['postprocess_av_payloads_preserved'])
        self.assertLess(abs(r['checks']['duration_actual']-r['checks']['duration_expected']),0.1)
    def test_mux_allows_subtitle_later_than_media(self):
        late=self.root/'late.ass';s=pysubs2.SSAFile();s.events=[pysubs2.SSAEvent(start=100,end=26000,text='Late metadata line')];s.save(late)
        out=self.root/'late.mkv';context=self.root/'late-context.json';context.write_text(json.dumps({'media_type':'anime'}))
        result=mux_single(self.video,late,out,context_path=context)
        self.assertTrue(result['audio_video_payloads_preserved'])
    def test_real_render_pixels_created(self):
        try:find_renderer()
        except ValueError:self.skipTest('libass renderer unavailable')
        r=render_samples(self.video,self.ass,self.root/'render',[0.5])
        p=self.root/'render'/r['samples'][0]['image']
        self.assertEqual(p.read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
        self.assertEqual(r['status'],'images_ready_for_visual_review')
        self.assertEqual(r['seek_mode'],'input_fast_seek_with_copyts')

if __name__=='__main__':unittest.main()
