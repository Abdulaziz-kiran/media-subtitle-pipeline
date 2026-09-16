"""Small policy/evidence helpers for automatic viewing-break orchestration."""
import hashlib
import json
from pathlib import Path

from subtitle_core import ROOT, read_json


def auto_enabled(preferences_path=None):
    path = Path(preferences_path) if preferences_path else ROOT / 'resources/preferences.json'
    value=read_json(path).get('auto_viewing_breaks')
    if type(value) is not bool:
        raise ValueError('auto_viewing_breaks must be a boolean')
    return value


def analysis_cache_key(source_sha256, subtitle_sha256, analysis_params):
    payload = {'source_sha256': source_sha256, 'subtitle_sha256': subtitle_sha256,
               'analysis_params': analysis_params}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def no_media_outcome(source_sha256=None, subtitle_sha256=None):
    return {'status': 'no_media', 'assessment': 'not_assessed',
            'source_sha256': source_sha256, 'subtitle_sha256': subtitle_sha256,
            'reason': 'No video source was supplied; viewing breaks were not assessed.'}


def reviewed_no_suitable_outcome(source_sha256, subtitle_sha256, analysis_params,
                                 candidate_analysis_sha256, reason, reviewed_by):
    if not isinstance(reason, str) or len(reason.strip()) < 20:
        raise ValueError('No-suitable outcome needs a concrete story-review reason')
    if not isinstance(reviewed_by, str) or len(reviewed_by.strip()) < 3:
        raise ValueError('No-suitable outcome needs a reviewer')
    return {'status': 'reviewed_no_suitable', 'assessment': 'complete',
            'source_sha256': source_sha256, 'subtitle_sha256': subtitle_sha256,
            'analysis_params': analysis_params,
            'candidate_analysis_sha256': candidate_analysis_sha256,
            'reason': reason.strip(), 'reviewed_by': reviewed_by.strip()}


def validate_reviewed_no_suitable(outcome, source_sha256, subtitle_sha256, analysis_params):
    if not isinstance(outcome, dict) or outcome.get('status') != 'reviewed_no_suitable':
        raise ValueError('Expected reviewed_no_suitable outcome')
    for key, expected in (('source_sha256', source_sha256), ('subtitle_sha256', subtitle_sha256),
                          ('analysis_params', analysis_params)):
        if outcome.get(key) != expected:
            raise ValueError('No-suitable outcome evidence is stale or mismatched')
    if not isinstance(outcome.get('candidate_analysis_sha256'), str) or not outcome['candidate_analysis_sha256']:
        raise ValueError('No-suitable outcome needs candidate analysis evidence')
    if outcome.get('assessment') != 'complete' or len(str(outcome.get('reason', '')).strip()) < 20:
        raise ValueError('No-suitable outcome needs complete review evidence')
    return True
