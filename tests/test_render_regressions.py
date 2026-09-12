"""Pixel-level karaoke regressions using the actual FFmpeg/libass renderer."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('AUDIT_SKILL', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / 'scripts'))
import pysubs2
import subtitle_core as core
from verify_render_qa import find_renderer


class KaraokePixelRegression(unittest.TestCase):
    def test_turkish_is_static_for_all_four_karaoke_modes(self):
        try:
            renderer = find_renderer()
        except ValueError as e:
            self.skipTest(str(e))
        fonts = ROOT / 'resources/fonts'
        self.assertTrue((fonts / 'SourceSans3-Regular.otf').is_file(), 'Restore original fonts before testing')
        for tag in ('k', 'K', 'kf', 'ko'):
            with self.subTest(tag=tag), tempfile.TemporaryDirectory() as td:
                td = Path(td)
                event = pysubs2.SSAEvent(start=0, end=5000, style='OP', text=r'{\k200}そら ' + '{\\' + tag + '200}へ')
                item = {'tr_text': 'Gökyüzüne', 'romaji_status': 'verified',
                        'romaji_source': 'Japanese kana in the source event',
                        'romaji_parts': [{'part':0, 'source_text':'', 'romaji_text':''},
                                         {'part':1, 'source_text':'そら ', 'romaji_text':'Sora '},
                                         {'part':2, 'source_text':'へ', 'romaji_text':'e'}]}
                event.text = core.translated_text(event, item)
                subs = pysubs2.SSAFile()
                subs.info.update({'PlayResX':'640', 'PlayResY':'360'})
                subs.styles['OP'] = pysubs2.SSAStyle(fontname='Source Sans 3', fontsize=32, marginv=30,
                     primarycolor=pysubs2.Color(255,255,255), secondarycolor=pysubs2.Color(255,0,0))
                subs.append(event); subs.save(td / 'test.ass')
                frames=[]
                for t in ('0.2', '4.5'):
                    r=subprocess.run([renderer,'-nostdin','-v','error','-f','lavfi','-i',
                         'color=c=black:s=640x360:r=24:d=5','-vf',f'ass=filename=test.ass:fontsdir={fonts}',
                         '-ss',t,'-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],
                         cwd=td,capture_output=True,check=True)
                    self.assertEqual(len(r.stdout),640*360*3)
                    frames.append(r.stdout)
                lower=[f[300*640*3:335*640*3] for f in frames]
                upper=[f[267*640*3:299*640*3] for f in frames]
                self.assertTrue(any(lower[0]), 'Turkish crop must contain actual glyph pixels')
                self.assertEqual(lower[0],lower[1], 'Karaoke effect leaked into the Turkish line')
                self.assertNotEqual(upper[0],upper[1], 'Original upper-line karaoke timing must remain active')


if __name__=='__main__': unittest.main()
