"""Season-wide source analysis and spoiler-safe episode projection."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))

import pysubs2
import season_context as season
import run_pipeline as runner
from subtitle_core import file_hash, read_json, write_json


class SeasonContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.e1 = self.root/'e1.ass'; self.e2 = self.root/'e2.ass'
        for path, texts in ((self.e1, ['Hello, senpai.', 'Who is that?']), (self.e2, ['It was Haru.', 'Hello again.'])):
            subs = pysubs2.SSAFile()
            subs.events = [pysubs2.SSAEvent(start=i*2000, end=i*2000+1500, text=t) for i,t in enumerate(texts)]
            subs.save(path)
        self.manifest = self.root/'manifest.json'
        write_json(self.manifest, {
            'schema_version':1,'series_id':'fixture','season_id':'S01','title':'Fixture','media_type':'anime',
            'source_language':'en','target_language':'tr','original_audio_language':'ja','original_audio_status':'verified',
            'original_audio_evidence':'Fixture metadata declares Japanese as the original audio.',
            'episodes':[{'episode_id':'S01E01','subtitle':str(self.e1)},{'episode_id':'S01E02','subtitle':str(self.e2)}]
        })
        self.pack = self.root/'pack.json'; season.prepare_reading_pack(self.manifest, self.pack)
        self.context = self.root/'season_context.json'
        write_json(self.context, {
            'schema_version':1,'series_id':'fixture','season_id':'S01','title':'Fixture','media_type':'anime',
            'source_language':'en','target_language':'tr','original_audio_language':'ja','original_audio_status':'verified',
            'original_audio_evidence':'Fixture metadata declares Japanese as the original audio.',
            'episode_sources':[
                {'episode_id':'S01E01','source_sha256':file_hash(self.e1),'source_file':'e1.ass'},
                {'episode_id':'S01E02','source_sha256':file_hash(self.e2),'source_file':'e2.ass'},
            ],
            'characters':{
                'haru':{'name':'Haru','aliases':[],'translation_guidance':'Do not reveal identity before the source does.',
                        'visible_from':'S01E02','evidence':[{'episode_id':'S01E02','source_sha256':file_hash(self.e2),'line_indices':[0]}]}
            },
            'relationships':[],
            'voices':{},
            'glossary':{
                'senpai':{'source':'senpai','preferred_tr':'senpai','aliases':[],'note':'Honorific policy.',
                          'state':'locked','valid_from':'S01E01','valid_through':None,
                          'evidence':[{'episode_id':'S01E01','source_sha256':file_hash(self.e1),'line_indices':[0]}]}
            },
            'recurring_elements':[{
                'id':'hello','type':'callback','description':'Greeting repeats later.','translation_guidance':'Keep the greeting wording stable.',
                'occurrences':[{'episode_id':'S01E01','line_indices':[0]},{'episode_id':'S01E02','line_indices':[1]}]
            }],
            'episode_notes':{
                'S01E01':{'translation_summary':'Episode one introduces an intentionally unidentified person.', 'notes':[], 'songs':[]},
                'S01E02':{'translation_summary':'Episode two resolves the earlier identity.', 'notes':[], 'songs':[]}
            },
            'guardrails':[{
                'episode_id':'S01E01','line_indices':[1],'rule':'preserve_identity_uncertainty',
                'instruction':'Do not reveal the later identity in Turkish.',
                'evidence':[{'episode_id':'S01E01','source_sha256':file_hash(self.e1),'line_indices':[1]}]
            }],
            'uncertainties':[],
            'content_filter_candidates':[{
                'id':'kiss_hint','episode_id':'S01E02','line_indices':[1],'category':'kissing',
                'reason':'Fixture text hint for content-filter handoff.',
                'evidence':[{'episode_id':'S01E02','source_sha256':file_hash(self.e2),'line_indices':[1]}]
            }]
        })

    def tearDown(self): self.temp.cleanup()

    def test_reading_pack_is_compact_visible_source(self):
        data = read_json(self.pack)
        self.assertEqual(len(data['episodes']), 2)
        self.assertEqual(data['episodes'][0]['lines'][0]['text'], 'Hello, senpai.')
        self.assertEqual(data['episodes'][0]['source_sha256'], file_hash(self.e1))

    def test_validate_and_derive_episode_context(self):
        season.validate_season_context(read_json(self.context))
        output = self.root/'e1-context.json'
        season.derive_episode_context(self.context, 'S01E01', output)
        episode = read_json(output)
        self.assertEqual(episode['glossary']['senpai']['preferred_tr'], 'senpai')
        self.assertEqual(len(episode['translation_guardrails']), 1)
        self.assertNotIn('haru', episode['characters'])
        # Future occurrence must not leak into E01 view.
        self.assertEqual(episode['recurring_elements'][0]['occurrences'], [{'episode_id':'S01E01','line_indices':[0]}])
        runner.validate_context(episode)


    def test_filter_review_handoff_is_episode_scoped(self):
        output = self.root/'filter-review.json'
        season.derive_filter_review(self.context, 'S01E01', output)
        e1 = read_json(output)
        self.assertTrue(e1['auto_content_filter'])
        self.assertEqual(e1['text_candidates'], [])
        season.derive_filter_review(self.context, 'S01E02', output)
        e2 = read_json(output)
        self.assertEqual([row['id'] for row in e2['text_candidates']], ['kiss_hint'])
        self.assertTrue(e2['content_filter_profile']['require_visual_confirmation'])

    def test_evidence_hash_mismatch_is_rejected(self):
        data = read_json(self.context)
        data['guardrails'][0]['evidence'][0]['source_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'source hash'):
            season.validate_season_context(data)

    def test_future_validity_is_filtered(self):
        data = read_json(self.context)
        data['glossary']['later'] = {'source':'later','preferred_tr':'sonra','aliases':[],'note':'Future-only term','state':'preferred',
            'valid_from':'S01E02','valid_through':None,'evidence':[{'episode_id':'S01E02','source_sha256':file_hash(self.e2),'line_indices':[0]}]}
        write_json(self.context, data, overwrite=True)
        output = self.root/'e1-context.json'; season.derive_episode_context(self.context, 'S01E01', output)
        self.assertNotIn('later', read_json(output)['glossary'])


if __name__ == '__main__': unittest.main()
