"""Keep real Matroska attachments out of the timed concat path, but preserve their bytes."""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(os.environ.get('AUDIT_SKILL',Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(ROOT/'scripts'))
import pysubs2,subtitle_core as core,run_pipeline as runner,content_filter_pipeline as cuts
from test_independent_audit import context,cut_spec

class AttachmentCutRegression(unittest.TestCase):
    def test_cut_preserves_original_non_font_attachment_payload(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);sub=r/'source.ass';s=pysubs2.SSAFile();s.append(pysubs2.SSAEvent(start=100,end=3900,text='Kesimin iki yanında kalan metin.'));s.save(sub)
            note=r/'note.txt';note.write_bytes(b'Attachment data must remain byte-identical.\n')
            video=r/'source.mkv'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=s=160x90:r=24:d=4',
                '-f','lavfi','-i','sine=d=4:r=48000','-c:v','mpeg4','-g','24','-bf','0','-c:a','pcm_s16le',
                '-attach',str(note),'-metadata:s:t:0','mimetype=text/plain','-metadata:s:t:0','filename=note.txt',str(video)],check=True,capture_output=True)
            ctx=r/'context.json';core.write_json(ctx,context('tr'));job=r/'job';runner.prepare(sub,job,context_path=ctx)
            out=r/'cut.mkv';result=cuts.sanitize_movie(video,sub,cut_spec(),out,r/'cut.ass',job_path=job,archive_root=r/'archive')
            attachment=[s for s in cuts.probe(out)['streams'] if s['codec_type']=='attachment']
            self.assertEqual([s['tags']['filename'] for s in attachment],['note.txt'])
            restored=r/'restored.txt'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-dump_attachment:t:0',str(restored),'-i',str(out),
                '-map','0:v:0','-frames:v','1','-f','null','-'],check=True,capture_output=True)
            self.assertEqual(restored.read_bytes(),note.read_bytes())
            self.assertTrue(result['checks']['stream_signature_preserved'])


class AggregateOpenGopRegression(unittest.TestCase):
    def test_aggregate_hevc_span_also_triggers_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);sub=r/'source.ass';s=pysubs2.SSAFile();s.append(pysubs2.SSAEvent(start=100,end=11900,text='A synthetic timing test.'));s.save(sub)
            video=r/'source.mkv'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=s=320x180:r=24:d=12',
                '-f','lavfi','-i','sine=d=12:r=48000','-f','lavfi','-i','sine=d=12:r=48000:f=880',
                '-map','0:v','-map','1:a','-map','2:a','-c:v','libx265','-preset','fast',
                '-x265-params','keyint=48:min-keyint=48:scenecut=0:bframes=4:open-gop=1:pools=2:log-level=error',
                '-c:a','pcm_s16le',str(video)],check=True,capture_output=True)
            ctx=r/'context.json';core.write_json(ctx,context('en'));job=r/'job';runner.prepare(sub,job,context_path=ctx)
            result=cuts.sanitize_movie(video,sub,cut_spec(3.1,4.9),r/'cut.mkv',r/'cut.ass',job_path=job,archive_root=r/'archive')
            checks=result['checks']
            self.assertEqual(checks['video_processing'],'lossless_reencode')
            self.assertLessEqual(abs(checks['duration_actual']-checks['duration_expected']),0.1)
            self.assertTrue(any(x.get('scope')=='concatenated_base' for x in checks['video_reencode']['trigger_details']))
            self.assertEqual(checks['base_av_payload_sha256'],checks['final_av_payload_sha256'])

if __name__=='__main__':unittest.main()
