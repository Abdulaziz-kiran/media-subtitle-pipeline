"""Behavioral tests for the opt-in viewing-breaks beta."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pysubs2
import subtitle_core as core
import viewing_breaks_beta as viewing
from content_filter_pipeline import probe


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/FFprobe unavailable')
class ViewingBreaksBetaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.root = Path(cls.temp.name)
        cls.video = cls.root / 'long-fixture.mkv'
        subprocess.run([
            'ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
            'testsrc2=size=160x90:rate=2:duration=125', '-f', 'lavfi', '-i',
            'sine=duration=125:sample_rate=16000:frequency=440', '-c:v', 'mpeg4',
            '-g', '10', '-bf', '0', '-c:a', 'aac', '-b:a', '64k', str(cls.video),
        ], check=True, capture_output=True, text=True)
        cls.subtitle = cls.root / 'source.ass'
        subs = pysubs2.SSAFile()
        subs.events = [pysubs2.SSAEvent(start=0, end=50_000, text='The first authored scene.'),
                       pysubs2.SSAEvent(start=70_000, end=120_000, text='A separate authored scene begins.')]
        subs.save(cls.subtitle)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_analysis_ranks_reviewable_keyframe_in_subtitle_gap(self):
        report = viewing.analyze_breaks(self.video, self.subtitle, parts=2)
        self.assertEqual(report['status'], 'beta_candidates_needing_story_review')
        self.assertFalse(report['astra_reviewed'])
        candidates = report['break_groups'][0]['candidates']
        self.assertTrue(candidates)
        self.assertTrue(any(row['signals']['subtitle_gap'] for row in candidates))
        self.assertTrue(all(row['story_review_required'] for row in candidates))

    def test_reviewed_break_creates_stream_copy_chapters_and_sidecar(self):
        analysis = viewing.analyze_breaks(self.video, self.subtitle, parts=2)
        selected = next(row for row in analysis['break_groups'][0]['candidates'] if row['signals']['subtitle_gap'])
        plan = {
            'beta_feature': 'viewing_breaks', 'beta_version': viewing.BETA_VERSION,
            'source_sha256': core.file_hash(self.video), 'review_status': 'reviewed',
            'reviewed_by': 'beta-test-reviewer',
            'review_summary': 'Picture, audio and neighboring authored dialogue were reviewed for the fixture.',
            'breaks': [{'requested_time': analysis['break_groups'][0]['ideal_time'],
                        'applied_time': selected['applied_time'], 'story_safe': True,
                        'evidence': 'The first fixture scene has ended and a long subtitle gap follows.',
                        'next_title': 'İzleme Bölümü 2'}],
        }
        plan_path = self.root / 'reviewed-plan.json'; plan_path.write_text(json.dumps(plan))
        output = self.root / 'chaptered.mkv'; before = core.file_hash(self.video)
        report = viewing.apply_chapters(self.video, plan_path, output)
        self.assertEqual(core.file_hash(self.video), before)
        self.assertEqual(report['status'], 'beta_chapters_need_playback_review')
        self.assertTrue(report['audio_video_payloads_preserved'])
        self.assertTrue(report['streams_and_attachments_preserved'])
        self.assertEqual(len(probe(output)['chapters']), 2)
        self.assertTrue(output.with_suffix('.mkv.viewing-breaks.json').is_file())

    def test_unreviewed_candidate_report_cannot_be_applied(self):
        analysis = viewing.analyze_breaks(self.video, self.subtitle, parts=2)
        path = self.root / 'unreviewed.json'; path.write_text(json.dumps(analysis['review_template']))
        with self.assertRaisesRegex(ValueError, 'story review'):
            viewing.apply_chapters(self.video, path, self.root / 'must-not-exist.mkv')
        self.assertFalse((self.root / 'must-not-exist.mkv').exists())


if __name__ == '__main__':
    unittest.main()
