"""Independent 2.3.0 counterexamples; no shim, fixtures authored for this audit.

AUDIT_SKILL can point to an untouched baseline or a repaired tree. Synthetic
learning-report payloads below test schema validation, not anybody's listening.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SKILL = Path(os.environ.get('AUDIT_SKILL', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(SKILL / 'scripts'))
import pysubs2
import subtitle_core as core
import run_pipeline as runner
import content_filter_pipeline as cuts
import archive_delivery as archive
import mux_mkv as mux
import verify_integrity as integrity
import reassemble_ass as reassemble


def context(language='de'):
    return {'context_prepared': True, 'title': 'Independent authored audit fixture',
            'media_type': 'film', 'summary': 'Two speakers arrange to wait and then return to the station.',
            'glossary': {}, 'relationships': [], 'voices': {}, 'uncertainties': [], 'songs': [],
            'context_sources': [{'kind': 'subtitle', 'reference': 'source.ass',
                                 'finding': 'The two authored lines explicitly say to wait and return.'}],
            'context_checks': {k: 'reviewed_none_found' for k in
                               ('glossary', 'relationships', 'voices', 'uncertainties', 'songs')},
            'source_language': language, 'target_language': 'tr',
            'original_audio_language': '', 'original_audio_status': 'unknown', 'original_audio_evidence': ''}


def parts(source, texts, romaji=False):
    return [{'part': n, 'source_text': s, 'romaji_text' if romaji else 'tr_text': texts[n]}
            for n, s in enumerate(core.format_parts(source))]


def cut_spec(start=1.1, end=1.7):
    return {'policy': {'authorized': True, 'requested_by': 'user-audit-request',
                       'instruction': 'Exercise the content-cut machinery on authored synthetic test patterns only.',
                       'source_reference': 'ASTRA-PRO-TEK-SEFER-PROMPT.md section G'},
            'cuts': [{'start': start, 'end': end, 'category': 'synthetic-test-interval',
                      'cut_reason': 'An intentionally chosen synthetic interval exercises keyframe expansion.',
                      'evidence': 'A generated test pattern and sine tones, not an actual sensitive scene.',
                      'reviewed_by': 'independent-audit',
                      'context_note': 'Sentetik deneme aralığı çıkarıldı; gerçek sahne değerlendirilmedi.'}]}


class IndependentTextAndArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.ass'
        subs = pysubs2.SSAFile()
        subs.events = [pysubs2.SSAEvent(start=100, end=1700, text='Warte hier.'),
                       pysubs2.SSAEvent(start=2000, end=3700, text='Wir kommen zurück.')]
        subs.save(self.source)
        self.ctx = self.root / 'context.json'
        core.write_json(self.ctx, context())
        self.data = {'source_sha256': core.file_hash(self.source),
                     'lines': [{'index': 0, 'tr_text': 'Burada bekle.'},
                               {'index': 1, 'tr_text': 'Geri döneceğiz.'}]}

    def tearDown(self):
        self.temp.cleanup()

    def make_job(self):
        job = self.root / 'job'
        runner.prepare(self.source, job, context_path=self.ctx)
        # Historical archive fixtures predate the strict orchestration marker.
        meta=core.read_json(job/'job.json');meta.pop('orchestration_required');core.write_json(job/'job.json',meta)
        (job/'orchestration.json').unlink()
        core.write_json(job / 'translations/batch-0001.json', self.data)
        runner.build(job)
        review = core.read_json(job / 'review-template.json')
        review.update(reviewer='independent-audit-fixture', mode='same_agent_second_pass',
                      summary='Authored German imperative and future promise checked against their Turkish translations.')
        for row in review['lines']:
            row['reviewed'] = True
            if row['formatting_reviewed'] is not None:
                row['formatting_reviewed'] = True
        core.write_json(job / 'review.json', review)
        return job

    def delivered(self, cut_record=False):
        job = self.make_job()
        if cut_record:
            core.write_json(job / 'content_filter/cut-audit.json', {'status': 'synthetic_record_for_inventory_test'})
        output = self.root / 'final.ass'
        result = runner.finalize(job, output, archive_root=self.root / 'archive')
        return job, output, Path(result['archive'])

    def test_plain_ass_alpha_injection_rejected(self):
        d = copy.deepcopy(self.data); d['lines'][0]['tr_text'] = r'{\alpha&HFF&}Burada bekle.'
        with self.assertRaises(ValueError): core.build_candidate(self.source, d, core.load_profile())

    def test_plain_ass_drawing_injection_rejected(self):
        with self.assertRaises(ValueError):
            core.translated_text(pysubs2.SSAEvent(text='Wait.'), {'tr_text': r'{\p1}m 0 0 l 8 8'})

    def test_plain_literal_newline_rejected(self):
        with self.assertRaises(ValueError):
            core.translated_text(pysubs2.SSAEvent(text='Wait.'), {'tr_text': 'Burada\nbekle.'})

    def test_plain_marker_rejected(self):
        with self.assertRaises(ValueError):
            core.translated_text(pysubs2.SSAEvent(text='Wait.'), {'tr_text': '⟪ASS:0⟫Bekle.'})

    def test_plain_ass_linebreak_is_allowed(self):
        got = core.translated_text(pysubs2.SSAEvent(text='Wait here.'), {'tr_text': r'Burada\Nbekle.'})
        self.assertEqual(got, r'Burada\Nbekle.')

    def test_boolean_ass_slot_id_rejected(self):
        source = r'{\i1}Stop{\i0} here.'
        rows = parts(source, ['', 'Dur', ' burada.']); rows[0]['part'] = False
        with self.assertRaises(ValueError): core.restore_structured_parts(source, rows)

    def test_slot_source_binding_rejects_modification(self):
        source = r'{\i1}Stop{\i0} here.'
        rows = parts(source, ['', 'Dur', ' burada.']); rows[1]['source_text'] = 'Go'
        with self.assertRaises(ValueError): core.restore_structured_parts(source, rows)

    def test_slot_emptying_short_reason_rejected(self):
        source = r'{\i1}Stop{\i0} here.'
        for rowtexts in (['', '', 'Burada dur.'], ['', 'Burada dur.', '']):
            with self.subTest(rowtexts=rowtexts), self.assertRaises(ValueError):
                core.restore_structured_parts(source, parts(source, rowtexts), 'x')

    def test_slot_missing_reversed_extra_rejected(self):
        source = r'{\i1}Stop{\i0} here.'; rows = parts(source, ['', 'Dur', ' burada.'])
        for invalid in (rows[:-1], rows[::-1], rows + [rows[0]]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError): core.restore_structured_parts(source, invalid)

    def test_long_scope_reason_is_attestation_not_semantic_proof(self):
        source = r'{\i1}Stop{\i0} here.'
        got = core.restore_structured_parts(source, parts(source, ['', 'Burada dur.', '']),
                                            'Turkish syntax requires a scoped phrase; reviewer must judge this claim.')
        self.assertIn('Burada dur.', got)  # Deliberately no assertion of semantic correctness.

    def test_english_only_romaji_invention_rejected(self):
        with self.assertRaises(ValueError):
            core.translated_text(pysubs2.SSAEvent(text='We fly toward tomorrow', style='OP'),
                                 {'tr_text': 'Yarına uçuyoruz', 'romaji_status': 'verified',
                                  'romaji_source': 'English meaning subtitle only', 'romaji_text': 'Ashita e tobu'})

    def test_untagged_romaji_literal_newline_rejected(self):
        with self.assertRaises(ValueError):
            core.translated_text(pysubs2.SSAEvent(text='そらへ', style='OP'),
                                 {'tr_text': 'Gökyüzüne', 'romaji_status': 'verified',
                                  'romaji_source': 'Kana in the source event', 'romaji_text': 'Sora\ne'})

    def test_untagged_romaji_marker_rejected(self):
        with self.assertRaises(ValueError):
            core.translated_text(pysubs2.SSAEvent(text='そらへ', style='OP'),
                                 {'tr_text': 'Gökyüzüne', 'romaji_status': 'verified',
                                  'romaji_source': 'Kana in the source event', 'romaji_text': 'Sora ⟪ASS:0⟫e'})

    def test_romaji_all_control_sequences_rejected(self):
        source = r'{\k20}そら'
        for value in (r'so\Nra', r'so\nra', r'so\hra', r'{\i1}sora', 'sora⟪ASS:1⟫', 'so\nra'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                core.translated_text(pysubs2.SSAEvent(text=source, style='OP'),
                                     {'tr_text': 'Gökyüzü', 'romaji_status': 'verified',
                                      'romaji_source': 'Kana in timed source', 'romaji_parts': parts(source, ['', value], True)})

    def test_turkish_song_literal_newline_rejected(self):
        with self.assertRaises(ValueError):
            core.translated_text(pysubs2.SSAEvent(text='そら', style='OP'),
                                 {'tr_text': 'Gök\nyüzü', 'romaji_status': 'verified',
                                  'romaji_source': 'Kana in the source event', 'romaji_text': 'Sora'})

    def test_all_four_karaoke_tags_reset_before_turkish(self):
        for tag in ('k', 'K', 'kf', 'ko'):
            source = '{\\' + tag + '20}そら'
            got = core.translated_text(pysubs2.SSAEvent(text=source, style='OP'),
                                       {'tr_text': 'Gökyüzü', 'romaji_status': 'verified',
                                        'romaji_source': 'Kana in timed source', 'romaji_parts': parts(source, ['', 'Sora'], True)})
            self.assertEqual(got, '{\\' + tag + '20}Sora' + r'{\kt0\k0}{\r}\NGökyüzü')
            with self.assertRaises(ValueError):
                core.translated_text(pysubs2.SSAEvent(text=source, style='OP'),
                                     {'tr_text': '{\\' + tag + '20}Gökyüzü', 'romaji_status': 'unavailable', 'romaji_source': ''})

    def test_context_source_reference_wrong_type_rejected(self):
        c = context(); c['context_sources'][0]['reference'] = 123456
        with self.assertRaises(ValueError): runner.validate_context(c)

    def test_context_source_finding_wrong_type_rejected(self):
        c = context(); c['context_sources'][0]['finding'] = {'untrusted': 'not text'}
        with self.assertRaises(ValueError): runner.validate_context(c)

    def test_context_media_type_wrong_type_rejected(self):
        c = context(); c['media_type'] = ['anime']
        with self.assertRaises(ValueError): runner.validate_context(c)

    def test_context_audio_evidence_wrong_type_rejected(self):
        c = context(); c.update(original_audio_status='verified', original_audio_language='eng', original_audio_evidence=12345678901234)
        with self.assertRaises(ValueError): runner.validate_context(c)

    def test_context_contradictory_checks_rejected(self):
        c = context(); c['glossary'] = {'station': 'istasyon'}
        with self.assertRaises(ValueError): runner.validate_context(c)

    def test_context_prepared_boolean_and_token_fields_rejected(self):
        for key, value in (('context_prepared', 1), ('summary', 'x')):
            c = context(); c[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): runner.validate_context(c)
        for key in ('reference', 'finding'):
            c = context(); c['context_sources'][0][key] = 'x'
            with self.subTest(key=key), self.assertRaises(ValueError): runner.validate_context(c)

    def test_all_translation_bad_id_shapes_rejected(self):
        for ids in ([0], [0, 1, 2], [0, 0], [-1, 1], [False, 1]):
            d = {'source_sha256': self.data['source_sha256'], 'lines': [{'index': i, 'tr_text': 'Bekle.'} for i in ids]}
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                core.build_candidate(self.source, d, core.load_profile())

    def test_stale_review_after_valid_context_change(self):
        job = self.make_job(); c = core.read_json(job / 'context.json')
        c['summary'] += ' The changed context is a material new input.'; core.write_json(job / 'context.json', c)
        with self.assertRaises(ValueError): runner.finalize(job, self.root / 'final.ass', archive_root=self.root / 'archive')

    def test_stale_review_after_valid_profile_change(self):
        job = self.make_job(); p = core.read_json(job / 'profile.json'); p['max_cps'] = 17; core.write_json(job / 'profile.json', p)
        with self.assertRaises(ValueError): runner.finalize(job, self.root / 'final.ass', archive_root=self.root / 'archive')

    def test_stale_review_after_source_change(self):
        job = self.make_job(); p = job / 'source.ass'; p.write_text(p.read_text() + '\n')
        with self.assertRaises(ValueError): runner.finalize(job, self.root / 'final.ass', archive_root=self.root / 'archive')

    def test_stale_review_after_candidate_change(self):
        job = self.make_job(); p = job / 'candidate.ass'; p.write_text(p.read_text() + '\n')
        with self.assertRaises(ValueError): runner.finalize(job, self.root / 'final.ass', archive_root=self.root / 'archive')

    def test_finalize_archive_failure_rolls_back_public_files(self):
        job = self.make_job(); output = self.root / 'final.ass'
        badroot = self.root / 'not-a-directory'; badroot.write_text('pre-existing sentinel')
        with self.assertRaises((ValueError, OSError)): runner.finalize(job, output, archive_root=badroot)
        self.assertFalse(output.exists(), 'Unarchived final must not remain published')
        self.assertFalse(output.with_suffix('.ass.qa.json').exists())
        self.assertEqual(badroot.read_text(), 'pre-existing sentinel')

    def test_external_review_is_the_one_actually_archived(self):
        job = self.make_job(); used = core.read_json(job / 'review.json')
        used['reviewer'] = 'actual-external-reviewer'; external = self.root / 'chosen-review.json'; core.write_json(external, used)
        output = self.root / 'final.ass'
        result = runner.finalize(job, output, review_path=external, archive_root=self.root / 'archive')
        self.assertEqual(core.read_json(Path(result['archive']) / 'review.json'), used)

    def test_resume_rejects_unlisted_extra_file(self):
        job, output, bundle = self.delivered(); (bundle / 'unlisted.txt').write_text('unlisted payload')
        with self.assertRaises(ValueError): runner.resume_from_archive(bundle, self.root / 'resume')
        self.assertFalse((self.root / 'resume').exists())

    def test_resume_rejects_deleted_manifest_inventory_entry(self):
        job, output, bundle = self.delivered(); m = core.read_json(bundle / 'archive-manifest.json')
        m['files'] = [x for x in m['files'] if x['name'] != 'review.json']; core.write_json(bundle / 'archive-manifest.json', m)
        with self.assertRaises(ValueError): runner.resume_from_archive(bundle, self.root / 'resume')

    def test_resume_rejects_duplicate_manifest_row(self):
        job, output, bundle = self.delivered(); m = core.read_json(bundle / 'archive-manifest.json')
        m['files'].append(m['files'][0]); core.write_json(bundle / 'archive-manifest.json', m)
        with self.assertRaises(ValueError): runner.resume_from_archive(bundle, self.root / 'resume')

    def test_resume_rejects_payload_tampering(self):
        job, output, bundle = self.delivered(); p = bundle / 'final.ass'; p.write_text(p.read_text() + 'tamper')
        with self.assertRaises(ValueError): runner.resume_from_archive(bundle, self.root / 'resume')

    def test_resume_retains_content_cut_provenance(self):
        job, output, bundle = self.delivered(cut_record=True); new = self.root / 'resume'
        runner.resume_from_archive(bundle, new)
        self.assertTrue((new / 'content_filter/cut-audit.json').is_file())

    def test_archive_repeated_delivery_detects_inventory_tamper(self):
        job, output, bundle = self.delivered(); m = core.read_json(bundle / 'archive-manifest.json'); m['files'].pop()
        core.write_json(bundle / 'archive-manifest.json', m)
        with self.assertRaises(ValueError): archive.archive_delivery(job, output, output.with_suffix('.ass.qa.json'), self.root / 'archive')

    def test_archive_symlink_payload_rejected_even_with_matching_hash(self):
        job, output, bundle = self.delivered(); p = bundle / 'final.ass'; other = self.root / 'outside.ass'
        shutil.copy2(p, other); p.unlink(); p.symlink_to(other)
        with self.assertRaises(ValueError): runner.resume_from_archive(bundle, self.root / 'resume')

    def test_archive_hardlink_payload_rejected_even_with_matching_hash(self):
        job, output, bundle = self.delivered(); p = bundle / 'final.ass'; other = self.root / 'outside.ass'
        shutil.copy2(p, other); p.unlink(); os.link(other, p)
        with self.assertRaises(ValueError): runner.resume_from_archive(bundle, self.root / 'resume')

    def test_archive_nested_reserved_manifest_name_is_not_ignored(self):
        job, output, bundle = self.delivered(); core.write_json(bundle / 'nested/archive-manifest.json', {'unlisted': True})
        with self.assertRaises(ValueError): archive.archive_delivery(job, output, output.with_suffix('.ass.qa.json'), self.root / 'archive')

    def test_archive_status_readonly_build_and_finalize_refused(self):
        job, output, bundle = self.delivered()
        before = {p.relative_to(bundle).as_posix(): core.file_hash(p) for p in bundle.rglob('*') if p.is_file()}
        runner.status(bundle)
        for operation in (lambda: runner.build(bundle), lambda: runner.finalize(bundle, self.root / 'no.ass')):
            with self.assertRaises(ValueError): operation()
        after = {p.relative_to(bundle).as_posix(): core.file_hash(p) for p in bundle.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_job_translation_path_traversal_rejected(self):
        job = self.make_job(); shutil.copy2(job / 'translations/batch-0001.json', job / 'outside.json')
        m = core.read_json(job / 'job.json'); m['batches'][0]['file'] = '../outside.json'; core.write_json(job / 'job.json', m)
        with self.assertRaises(ValueError): runner.build(job)

    def test_job_symlink_parent_is_refused_before_write(self):
        job = self.make_job(); real = job / 'translations'; moved = self.root / 'elsewhere'; real.rename(moved); real.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError): runner.build(job)

    def test_finalize_hardlink_to_source_no_clobber(self):
        job = self.make_job(); dest = self.root / 'alias.ass'; before = core.file_hash(self.source); os.link(self.source, dest)
        with self.assertRaises((ValueError, OSError)): runner.finalize(job, dest, archive_root=self.root / 'archive')
        self.assertEqual(core.file_hash(self.source), before)

    def test_reassemble_sidecar_collision_does_not_leave_partial_candidate(self):
        data = self.root / 'translations.json'; core.write_json(data, self.data)
        output = self.root / 'candidate.ass'; qa = self.root / 'candidate.ass.qa.json'; qa.write_text('sentinel')
        with self.assertRaises((ValueError, OSError)): reassemble.reassemble_ass(self.source, data, output)
        self.assertFalse(output.exists()); self.assertEqual(qa.read_text(), 'sentinel')

    def test_integrity_warning_returncode_zero_not_failure(self):
        with patch.object(integrity, 'get_duration', return_value=5.0), patch.object(integrity.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', 'non monotonically increasing dts')):
            result = integrity.multi_point_decode('synthetic.mkv', [0.5])
        self.assertTrue(result['passed']); self.assertIn('warning', json.dumps(result).lower())

    def test_analyze_cli_cannot_overwrite_existing_file(self):
        report = self.root / 'technical_report.json'; core.write_json(report, {'lines': [], 'status': 'fixture'})
        victim = self.root / 'keep.ass'; victim.write_bytes(b'unchanged sentinel'); before = core.file_hash(victim)
        result = subprocess.run([sys.executable, str(SKILL / 'scripts/analyze_audit.py'), '--jobs-dir', str(self.root), '--output', str(victim)], capture_output=True, text=True)
        self.assertEqual(core.file_hash(victim), before); self.assertNotEqual(result.returncode, 0)

    def test_anime_japanese_beats_conflicting_verified_context(self):
        audio = [{'tags': {'language': 'eng'}, 'disposition': {'original': 1}}, {'tags': {'language': 'jpn'}, 'disposition': {}}]
        c = {'media_type': 'anime', 'original_audio_status': 'verified', 'original_audio_language': 'eng', 'original_audio_evidence': 'A conflicting long metadata claim, not an explicit user override.'}
        self.assertEqual(mux.choose_original_audio(audio, context=c)[:2], (1, 'jpn'))
        self.assertEqual(mux.choose_original_audio(audio, 'eng', c)[:2], (0, 'eng'))

    def test_mux_rejects_one_letter_verified_audio_evidence(self):
        audio = [{'tags': {'language': 'eng'}, 'disposition': {}}, {'tags': {'language': 'jpn'}, 'disposition': {}}]
        with self.assertRaises(ValueError):
            mux.choose_original_audio(audio, context={'media_type': 'film', 'original_audio_status': 'verified', 'original_audio_language': 'eng', 'original_audio_evidence': 'x'})

    def make_learning(self):
        job = self.root / 'learning'; job.mkdir()
        s = pysubs2.SSAFile(); s.events = [pysubs2.SSAEvent(start=0, end=2000, text='Wait at the gate.')]; s.save(job / 'source.ass')
        prefs = core.read_json(SKILL / 'resources/preferences.json')
        payload = {'learner_profile': prefs['english_learner_profile'],
                   'estimated_cefr': {'with_english_subtitles': 'A2-B1', 'listening_without_subtitles': 'B1', 'confidence': 'low',
                                      'evidence': [{'line_index': 0, 'source_excerpt': 'Wait at the gate.', 'reason': 'Schema-test fixture: a short imperative.'}]},
                   'learning_points': [{'line_index': 0, 'source_excerpt': 'at the gate', 'meaning_tr': 'kapıda', 'why_useful': 'A location phrase in this authored line.'}],
                   'fit_for_learner': 'comfortable', 'personal_assessment': False,
                   'limitations': 'SCHEMA TEST ONLY. No real speech, listening difficulty or learner level was assessed.'}
        core.write_json(job / 'learning_report.json', payload)
        return job, payload

    def test_learning_nonstrings_rejected(self):
        job, payload = self.make_learning(); payload['learning_points'][0]['meaning_tr'] = None; core.write_json(job / 'learning_report.json', payload)
        with self.assertRaises(ValueError): runner.validate_learning_report(job, context('en'), job / 'source.ass')

    def test_learning_honest_no_audio_status_supported(self):
        job, payload = self.make_learning()
        payload['estimated_cefr'].update(listening_without_subtitles='not_assessed', listening_assessment_status='not_assessed',
                                         listening_limitations='No original speech is present; sine tones cannot support a listening CEFR estimate.')
        core.write_json(job / 'learning_report.json', payload)
        self.assertEqual(runner.validate_learning_report(job, context('en'), job / 'source.ass'), job / 'learning_report.json')

    def test_learning_invalid_cefr_confidence_fit_quote_personal_rejected(self):
        job, original = self.make_learning()
        mutations = [('cefr', 'D7'), ('confidence', 'certain'), ('fit', 'great'), ('quote', 'not actually here'), ('personal', True), ('empty', None)]
        for field, value in mutations:
            payload = copy.deepcopy(original)
            if field == 'cefr': payload['estimated_cefr']['with_english_subtitles'] = value
            elif field == 'confidence': payload['estimated_cefr']['confidence'] = value
            elif field == 'fit': payload['fit_for_learner'] = value
            elif field == 'quote': payload['learning_points'][0]['source_excerpt'] = value
            elif field == 'personal': payload['personal_assessment'] = value
            else: payload['estimated_cefr']['evidence'] = []
            core.write_json(job / 'learning_report.json', payload)
            with self.subTest(field=field), self.assertRaises(ValueError): runner.validate_learning_report(job, context('en'), job / 'source.ass')

    def test_learning_stale_review_hash_rejected(self):
        job, payload = self.make_learning(); report = {'source_sha256': 's', 'input_sha256': 'i', 'candidate_sha256': 'c', 'lines': []}
        review = dict(report, reviewer='auditor', summary='Schema review only', mode='same_agent_second_pass', technical_exceptions=[],
                      learning_report_reviewed=True, learning_report_sha256=core.file_hash(job / 'learning_report.json'),
                      learning_report_review_summary='The schema and quoted source lines were checked, not a listening estimate.')
        payload['limitations'] += ' A changed input invalidates review.'; core.write_json(job / 'learning_report.json', payload)
        with self.assertRaises(ValueError): runner.validate_review(review, report, job / 'learning_report.json')


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Real FFmpeg/FFprobe required')
class IndependentRealMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.root = Path(cls.temp.name)
        cls.source = cls.root / 'source.ass'; s = pysubs2.SSAFile()
        s.events = [pysubs2.SSAEvent(start=200, end=4700, text='İki yanda kalan aynı replik.')]; s.save(cls.source)
        cls.video = cls.root / 'source.mkv'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=192x108:rate=25:duration=5',
                        '-f', 'lavfi', '-i', 'sine=frequency=523:sample_rate=48000:duration=5',
                        '-c:v', 'mpeg4', '-g', '25', '-bf', '0', '-c:a', 'pcm_s16le', str(cls.video)], check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_public_render_cannot_bypass_policy_and_archive(self):
        out = self.root / 'bypass.mkv'
        plan = cuts.plan_cuts(self.video, cut_spec()['cuts'])
        with self.assertRaises(ValueError): cuts.render_cut_plan(self.video, plan, out)
        self.assertFalse(out.exists())

    def test_archive_failure_does_not_leave_orphan_job_cut_record(self):
        job = self.root / 'failure-job'; ctx=self.root/'failure-context.json'; core.write_json(ctx,context('tr')); runner.prepare(self.source,job,context_path=ctx)
        bad = self.root / 'archive-is-a-file'; bad.write_text('sentinel')
        out = self.root / 'failure.mkv'; sub = self.root / 'failure.ass'
        with self.assertRaises((ValueError, OSError)):
            cuts.sanitize_movie(self.video, self.source, cut_spec(), out, sub, job_path=job, archive_root=bad)
        self.assertFalse(out.exists()); self.assertFalse(sub.exists()); self.assertFalse(out.with_suffix('.cut-report.json').exists())
        self.assertEqual(list((job / 'content_filter').glob('cut-*.json')), [])

    def test_cut_archive_hash_identical_to_job_record(self):
        job = self.root / 'hash-job'; ctx=self.root/'hash-context.json'; core.write_json(ctx,context('tr')); runner.prepare(self.source,job,context_path=ctx)
        out = self.root / 'hash.mkv'; sub = self.root / 'hash.ass'
        result = cuts.sanitize_movie(self.video, self.source, cut_spec(), out, sub, job_path=job, archive_root=self.root / 'archive')
        evidence = result['evidence_archive']; local = Path(evidence['job_record']); central = Path(evidence['archive_bundle']) / 'cut-report.json'
        self.assertEqual(core.file_hash(local), core.file_hash(central)); self.assertEqual(core.file_hash(local), evidence['sha256'])
        self.assertTrue(result['plan']['applied'][0][0] <= 1.1); self.assertTrue(result['plan']['applied'][0][1] >= 1.7)
        self.assertEqual(result['status'], 'cut_needs_playback_review')
        self.assertFalse(any(p.suffix == '.mkv' for p in central.parent.rglob('*')))

    def test_integrity_cli_cannot_truncate_source_media(self):
        victim = self.root / 'victim.mkv'; shutil.copy2(self.video, victim); before = core.file_hash(victim)
        r = subprocess.run([sys.executable, str(SKILL / 'scripts/verify_integrity.py'), '--dir', str(self.root), '--output', str(victim)], capture_output=True, text=True)
        self.assertEqual(core.file_hash(victim), before); self.assertNotEqual(r.returncode, 0)

    def test_font_renamed_internally_same_filename_is_rejected(self):
        folder = self.root / 'fake-font'; folder.mkdir(); name = 'SourceSans3-Regular.otf'
        source = SKILL / 'resources/fonts' / name; fake = folder / name
        raw = source.read_bytes().replace('Source Sans 3'.encode('utf-16-be'), 'Falsif Sans X'.encode('utf-16-be')).replace(b'Source Sans 3', b'Falsif Sans X')
        fake.write_bytes(raw)
        with self.assertRaises(ValueError): mux.inspect_fonts([fake], 'Source Sans 3')


if __name__ == '__main__':
    if hasattr(os, 'sched_setaffinity'):
        os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:4])
    unittest.main(verbosity=2)
