#!/usr/bin/env python3
"""Small, file-backed evidence contract for multi-worker subtitle jobs.

The contract records *what was observed*, and binds worker receipts to the
current local artifacts.  It does not claim that an external platform run ID
or a worker name cryptographically proves a person's or model's identity.
"""
from __future__ import annotations

from pathlib import Path
import re

from subtitle_core import file_hash, object_hash, read_json, write_json


PLAN_SCHEMA_VERSION = 1
STRICT_MARKER_VERSION = 1
CAPABILITY_STATUSES = {'unresolved', 'available', 'unavailable'}
PROVENANCE_KINDS = {'agent_declared', 'platform_observed', 'unavailable'}
RUNTIME_STATUSES = {'observed', 'unavailable'}
WORKER_ROLES = {'translator', 'reviewer'}


def _text(value, label, minimum=0, maximum=500, *, empty=False):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError(label + ' must be bounded text')
    value = value.strip()
    if not empty and not value:
        raise ValueError(label + ' is required')
    return value


def blank_orchestration_plan():
    return {
        'schema_version': PLAN_SCHEMA_VERSION,
        'subagent_capability': {
            'status': 'unresolved',
            'source': '',
            'reason': 'Coordinator must record whether a separate reviewer was available for this job.',
        },
        'reviewer_policy': 'independent_when_available',
        'fallback_reason': '',
    }


def validate_orchestration_plan(data, *, require_resolved=False):
    if not isinstance(data, dict) or set(data) != {'schema_version', 'subagent_capability', 'reviewer_policy', 'fallback_reason'}:
        raise ValueError('Invalid orchestration plan')
    if data['schema_version'] != PLAN_SCHEMA_VERSION or data['reviewer_policy'] != 'independent_when_available':
        raise ValueError('Unsupported orchestration plan')
    capability = data['subagent_capability']
    if not isinstance(capability, dict) or set(capability) != {'status', 'source', 'reason'}:
        raise ValueError('Invalid subagent capability observation')
    status = capability['status']
    if status not in CAPABILITY_STATUSES:
        raise ValueError('Invalid subagent capability status')
    _text(capability['source'], 'Subagent capability source', 0, 500, empty=True)
    _text(capability['reason'], 'Subagent capability reason', 0, 1000, empty=True)
    fallback = _text(data['fallback_reason'], 'Reviewer fallback reason', 0, 1000, empty=True)
    if status == 'unresolved':
        if require_resolved:
            raise ValueError('Strict orchestration needs an explicit subagent capability observation before finalization')
    else:
        _text(capability['source'], 'Subagent capability source', 10, 500)
        _text(capability['reason'], 'Subagent capability reason', 10, 1000)
    if status == 'available' and fallback:
        raise ValueError('Available subagents cannot use a reviewer fallback')
    if status == 'unavailable' and not fallback:
        raise ValueError('Unavailable subagents need a reviewer fallback reason')
    return data


def validate_run_input(data):
    fields = {'role', 'worker_id', 'provenance', 'runtime', 'capability', 'fallback_reason'}
    if not isinstance(data, dict) or set(data) != fields or data['role'] not in WORKER_ROLES:
        raise ValueError('Invalid worker run input')
    _text(data['worker_id'], 'Worker identifier', 2, 160)
    provenance = data['provenance']
    if not isinstance(provenance, dict) or set(provenance) != {'kind', 'reference', 'reason'} or provenance['kind'] not in PROVENANCE_KINDS:
        raise ValueError('Invalid worker provenance')
    _text(provenance['reference'], 'Worker provenance reference', 0, 500, empty=True)
    _text(provenance['reason'], 'Worker provenance reason', 0, 1000, empty=True)
    if provenance['kind'] == 'unavailable':
        _text(provenance['reason'], 'Unavailable worker provenance reason', 10, 1000)
    else:
        _text(provenance['reference'], 'Worker provenance reference', 3, 500)
    runtime = data['runtime']
    if not isinstance(runtime, dict) or set(runtime) != {'model_status', 'model', 'effort_status', 'effort', 'reason'}:
        raise ValueError('Invalid worker runtime observation')
    for status_key, value_key, label in (('model_status', 'model', 'model'), ('effort_status', 'effort', 'effort')):
        if runtime[status_key] not in RUNTIME_STATUSES:
            raise ValueError('Invalid runtime ' + label + ' status')
        _text(runtime[value_key], 'Runtime ' + label, 0, 160, empty=True)
        if runtime[status_key] == 'observed':
            _text(runtime[value_key], 'Observed runtime ' + label, 1, 160)
        elif runtime[value_key]:
            raise ValueError('Unavailable runtime ' + label + ' cannot name a value')
    _text(runtime['reason'], 'Worker runtime reason', 0, 1000, empty=True)
    if 'unavailable' in (runtime['model_status'], runtime['effort_status']):
        _text(runtime['reason'], 'Unavailable runtime reason', 10, 1000)
    capability = data['capability']
    if capability is not None:
        if not isinstance(capability, dict) or set(capability) != {'status', 'source', 'reason'}:
            raise ValueError('Invalid capability update')
        validate_orchestration_plan({
            'schema_version': PLAN_SCHEMA_VERSION, 'subagent_capability': capability,
            'reviewer_policy': 'independent_when_available', 'fallback_reason': data['fallback_reason'],
        })
    elif data['fallback_reason']:
        _text(data['fallback_reason'], 'Reviewer fallback reason', 10, 1000)
    return data


def plan_path(job):
    return Path(job) / 'orchestration.json'


def required_for_job(meta):
    return meta.get('orchestration_required') == STRICT_MARKER_VERSION


def load_plan(job, meta, *, require_resolved=False):
    path = plan_path(job)
    if not required_for_job(meta):
        return None
    if not path.is_file():
        raise ValueError('Strict orchestration plan is missing')
    return validate_orchestration_plan(read_json(path), require_resolved=require_resolved)


def update_capability(plan, capability, fallback_reason):
    updated = dict(plan)
    updated['subagent_capability'] = dict(capability)
    updated['fallback_reason'] = fallback_reason.strip()
    return validate_orchestration_plan(updated)


def receipt_path(job, role):
    return Path(job) / 'worker_receipts' / (role + '.json')


def write_worker_receipt(job, role, worker_id, provenance, runtime, bindings, review_mode=None, fallback_reason=''):
    if role not in WORKER_ROLES:
        raise ValueError('Unknown worker role')
    receipt = {
        'schema_version': 1,
        'role': role,
        'worker_id': worker_id.strip(),
        'provenance': provenance,
        'runtime': runtime,
        'bindings': bindings,
        'review_mode': review_mode,
        'fallback_reason': fallback_reason.strip(),
        'attestation_scope': 'Artifact hashes are locally verified; worker identity and platform execution remain declared unless platform-observed evidence is supplied.',
    }
    path = receipt_path(job, role)
    write_json(path, receipt, overwrite=True)
    return receipt


def _validate_receipt_common(receipt, role):
    expected = {'schema_version', 'role', 'worker_id', 'provenance', 'runtime', 'bindings', 'review_mode', 'fallback_reason', 'attestation_scope'}
    if not isinstance(receipt, dict) or set(receipt) != expected or receipt['schema_version'] != 1 or receipt['role'] != role:
        raise ValueError('Invalid worker receipt')
    validate_run_input({'role': role, 'worker_id': receipt['worker_id'], 'provenance': receipt['provenance'],
                        'runtime': receipt['runtime'], 'capability': None, 'fallback_reason': receipt['fallback_reason']})
    if not isinstance(receipt['bindings'], dict):
        raise ValueError('Worker receipt bindings are invalid')
    if receipt['attestation_scope'] != 'Artifact hashes are locally verified; worker identity and platform execution remain declared unless platform-observed evidence is supplied.':
        raise ValueError('Invalid worker attestation scope')
    return receipt


def validate_worker_receipts(job, meta, report, review, translation_sha256, usage):
    """Enforce strict new-job evidence while leaving pre-marker jobs readable."""
    plan = load_plan(job, meta, require_resolved=True)
    if plan is None:
        return None
    required_roles = {'translator', 'reviewer', 'coordinator'}
    present_roles = {run['role'] for run in usage['runs']}
    if not required_roles <= present_roles:
        raise ValueError('Strict orchestration needs token records or explicit unavailable records for translator, reviewer and coordinator')
    translator_path = receipt_path(job, 'translator')
    reviewer_path = receipt_path(job, 'reviewer')
    if not translator_path.is_file() or not reviewer_path.is_file():
        raise ValueError('Strict orchestration needs translator and reviewer worker receipts')
    translator = _validate_receipt_common(read_json(translator_path), 'translator')
    reviewer = _validate_receipt_common(read_json(reviewer_path), 'reviewer')
    source_sha = meta['source_sha256']
    # A reviewer may make a legitimate correction and rebuild after translation.
    # Keep the translator's source-bound snapshot as historical provenance; the
    # reviewer receipt below binds the final candidate and input hash.
    translator_bindings = translator['bindings']
    if (set(translator_bindings) != {'source_sha256', 'translation_sha256'} or
            translator_bindings.get('source_sha256') != source_sha or
            not isinstance(translator_bindings.get('translation_sha256'), str) or
            not re.fullmatch(r'[0-9a-f]{64}', translator_bindings['translation_sha256'])):
        raise ValueError('Translator worker receipt has invalid source binding')
    expected_review = {'source_sha256': source_sha, 'input_sha256': report['input_sha256'],
                       'candidate_sha256': report['candidate_sha256'], 'review_sha256': object_hash(review)}
    if reviewer['bindings'] != expected_review or reviewer['worker_id'] != review['reviewer'] or reviewer['review_mode'] != review['mode']:
        raise ValueError('Reviewer worker receipt is stale')
    capability = plan['subagent_capability']['status']
    if capability == 'available':
        if review['mode'] not in ('independent_agent', 'human') or reviewer['fallback_reason']:
            raise ValueError('Available subagents require an independent reviewer receipt')
    elif review['mode'] == 'same_agent_second_pass':
        if not plan['fallback_reason'] or reviewer['fallback_reason'] != plan['fallback_reason']:
            raise ValueError('Same-agent review needs the recorded reviewer fallback reason')
    return {'capability_status': capability, 'receipt_hashes': {role: file_hash(receipt_path(job, role)) for role in WORKER_ROLES}}


def compact_summary(job, meta):
    plan = load_plan(job, meta)
    if plan is None:
        return {'policy': 'legacy_no_orchestration_marker', 'capability_status': 'not_recorded', 'worker_receipts': []}
    present = [role for role in sorted(WORKER_ROLES) if receipt_path(job, role).is_file()]
    return {'policy': 'strict_v1', 'capability_status': plan['subagent_capability']['status'],
            'worker_receipts': present, 'fallback_recorded': bool(plan['fallback_reason'])}
