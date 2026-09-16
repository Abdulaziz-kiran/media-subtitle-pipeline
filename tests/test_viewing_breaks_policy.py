import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import viewing_breaks_policy as policy


class ViewingBreakPolicyTests(unittest.TestCase):
    def test_preference_and_cache_key_are_stable(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'preferences.json'; p.write_text('{"auto_viewing_breaks":true}')
            self.assertTrue(policy.auto_enabled(p))
        params = {'parts': 2, 'top_candidates': 5}
        self.assertEqual(policy.analysis_cache_key('s', 't', params), policy.analysis_cache_key('s', 't', params))
        self.assertNotEqual(policy.analysis_cache_key('s', 't', params), policy.analysis_cache_key('s2', 't', params))

    def test_preference_requires_a_boolean(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'preferences.json';p.write_text('{"auto_viewing_breaks":"true"}')
            with self.assertRaisesRegex(ValueError,'boolean'):
                policy.auto_enabled(p)

    def test_no_media_is_honest_not_assessed(self):
        outcome = policy.no_media_outcome('source', 'subtitle')
        self.assertEqual(outcome['status'], 'no_media')
        self.assertEqual(outcome['assessment'], 'not_assessed')

    def test_reviewed_no_suitable_requires_matching_evidence(self):
        params = {'parts': 2, 'top_candidates': 5}
        outcome = policy.reviewed_no_suitable_outcome('source', 'subtitle', params, 'candidate',
                                                       'Yakın görüntü, ses ve diyalog incelendi; güvenli durak bulunamadı.', 'reviewer')
        self.assertTrue(policy.validate_reviewed_no_suitable(outcome, 'source', 'subtitle', params))
        with self.assertRaises(ValueError): policy.validate_reviewed_no_suitable(outcome, 'other', 'subtitle', params)
        changed = dict(outcome); changed['candidate_analysis_sha256'] = ''
        with self.assertRaises(ValueError): policy.validate_reviewed_no_suitable(changed, 'source', 'subtitle', params)


if __name__ == '__main__': unittest.main()
