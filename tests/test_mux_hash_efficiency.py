import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from content_filter_pipeline import probe
from mux_mkv import av_payload_hashes


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg/FFprobe unavailable')
class MuxHashEfficiencyTests(unittest.TestCase):
    def test_one_process_matches_per_stream_reference(self):
        with tempfile.TemporaryDirectory() as d:
            video=Path(d)/'fixture.mkv'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=64x48:rate=5:duration=1',
                            '-f','lavfi','-i','sine=frequency=440:duration=1','-f','lavfi','-i','sine=frequency=880:duration=1',
                            '-map','0:v','-map','1:a','-map','2:a','-c:v','mpeg4','-c:a','aac',str(video)],check=True)
            info=probe(video)
            streams=[s for s in info['streams'] if s.get('codec_type') in ('audio','video')]
            reference=[]
            for stream in streams:
                r=subprocess.run(['ffmpeg','-nostdin','-v','error','-fflags','+noparse+nofillin','-i',str(video),
                                  '-map',f"0:{stream['index']}",'-c','copy','-f','streamhash','-hash','sha256','-'],
                                 capture_output=True,text=True,check=True)
                reference.append((stream['codec_type'],stream.get('codec_name'),r.stdout.strip().split('=',1)[-1]))
            with patch('mux_mkv.subprocess.run',wraps=subprocess.run) as run:
                metrics={}; actual=av_payload_hashes(video,info,metrics)
            self.assertEqual(actual,reference)
            self.assertEqual(run.call_count,1)
            self.assertEqual(metrics['subprocess_count'],1)
            self.assertGreaterEqual(metrics['wall_seconds'],0)
            self.assertGreaterEqual(metrics['child_cpu_user_seconds'],0)
            self.assertGreaterEqual(metrics['child_cpu_system_seconds'],0)
            self.assertEqual(run.call_args.args[0].count('-c'),1)
            self.assertIn('-c',run.call_args.args[0]);self.assertIn('copy',run.call_args.args[0])
            for stream in streams:self.assertIn(f"0:{stream['index']}",run.call_args.args[0])

    def test_rejects_output_order_or_count_mismatch(self):
        info={'streams':[{'index':4,'codec_type':'video','codec_name':'x'},
                         {'index':9,'codec_type':'audio','codec_name':'y'}]}
        fake=subprocess.CompletedProcess([],0,stdout='0,a,sha256='+'a'*64+'\n1,v,sha256='+'b'*64+'\n',stderr='')
        with patch('mux_mkv.subprocess.run',return_value=fake):
            with self.assertRaisesRegex(ValueError,'order mismatch'):
                av_payload_hashes('fixture.mkv',info)

    def test_accepts_shuffled_output_and_rejects_duplicate_or_malformed_digest(self):
        info={'streams':[{'index':4,'codec_type':'video','codec_name':'x'},
                         {'index':9,'codec_type':'audio','codec_name':'y'}]}
        shuffled=subprocess.CompletedProcess([],0,stdout='1,a,sha256='+'b'*64+'\n0,v,SHA256='+'a'*64+'\n',stderr='')
        with patch('mux_mkv.subprocess.run',return_value=shuffled):
            self.assertEqual(av_payload_hashes('fixture.mkv',info),[('video','x','a'*64),('audio','y','b'*64)])
        duplicate=subprocess.CompletedProcess([],0,stdout='0,v,sha256='+'a'*64+'\n0,v,sha256='+'b'*64+'\n',stderr='')
        with patch('mux_mkv.subprocess.run',return_value=duplicate):
            with self.assertRaisesRegex(ValueError,'order mismatch'): av_payload_hashes('fixture.mkv',info)
        malformed=subprocess.CompletedProcess([],0,stdout='0,v,sha256=xyz\n1,a,sha256='+'b'*64+'\n',stderr='')
        with patch('mux_mkv.subprocess.run',return_value=malformed):
            with self.assertRaisesRegex(ValueError,'malformed'): av_payload_hashes('fixture.mkv',info)

    def test_failed_hash_process_records_attempt_and_time(self):
        metrics={}
        with patch('mux_mkv.subprocess.run',side_effect=subprocess.CalledProcessError(7,['ffmpeg'])):
            with self.assertRaises(subprocess.CalledProcessError): av_payload_hashes('fixture.mkv',{'streams':[{'index':4,'codec_type':'video'}]},metrics)
        self.assertEqual(metrics['subprocess_count'],1)
        self.assertGreaterEqual(metrics['wall_seconds'],0)


if __name__=='__main__': unittest.main()
