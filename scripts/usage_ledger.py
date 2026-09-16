#!/usr/bin/env python3
"""Validate honest per-agent token-usage ledgers without estimating missing data."""
from __future__ import annotations

USAGE_STATUSES={'measured','unavailable'}
ROLES={'translator','reviewer','context_curator','season_context','preparation','repair','adjudicator','content_filter_reviewer','coordinator','renderer','other'}


def blank_usage_ledger():
    return {'schema_version':1,'runs':[]}


def _text(value,label,minimum=0,maximum=500):
    if not isinstance(value,str) or not minimum<=len(value.strip())<=maximum:
        raise ValueError(label+' must be bounded text')
    return value.strip()


def _count(value,label,required):
    if value is None and not required: return None
    if type(value) is not int or value<0: raise ValueError(label+' must be a non-negative integer')
    return value


def validate_usage_ledger(data):
    if not isinstance(data,dict) or set(data)!={'schema_version','runs'} or data['schema_version']!=1:
        raise ValueError('Invalid token usage ledger')
    runs=data['runs']
    if not isinstance(runs,list) or len(runs)>1000: raise ValueError('Token usage runs must be bounded')
    for run in runs:
        fields={'role','measurement_status','source','model','input_tokens','output_tokens','cached_input_tokens','reason'}
        if not isinstance(run,dict) or set(run)!=fields: raise ValueError('Invalid token usage run')
        if run['role'] not in ROLES or run['measurement_status'] not in USAGE_STATUSES:
            raise ValueError('Invalid token usage role or status')
        _text(run['source'],'Token usage source',3,500)
        _text(run['model'],'Token usage model',0,160)
        if run['measurement_status']=='measured':
            input_tokens=_count(run['input_tokens'],'input_tokens',True)
            _count(run['output_tokens'],'output_tokens',True)
            cached=_count(run['cached_input_tokens'],'cached_input_tokens',False)
            if cached is not None and cached>input_tokens:
                raise ValueError('cached_input_tokens cannot exceed input_tokens')
            # Genuine zero-token runs are valid, but every measured value needs
            # enough provenance to distinguish it from an empty template.
            _text(run['reason'],'Measured token usage reason',10,500)
        else:
            if any(run[name] is not None for name in ('input_tokens','output_tokens','cached_input_tokens')):
                raise ValueError('Unavailable token usage cannot contain estimated counts')
            _text(run['reason'],'Unavailable token usage reason',10,500)
    return data


def summarize_usage_ledger(data):
    if data is None:
        return {'measurement_status':'missing','runs_total':0,'runs_measured':0,'runs_unavailable':0,
                'input_tokens':None,'output_tokens':None,'cached_input_tokens':None}
    data=validate_usage_ledger(data);runs=data['runs']
    measured=[r for r in runs if r['measurement_status']=='measured']
    unavailable=len(runs)-len(measured)
    status='not_recorded' if not runs else 'measured' if not unavailable else 'partial'
    complete=bool(runs) and not unavailable
    return {'measurement_status':status,'runs_total':len(runs),'runs_measured':len(measured),'runs_unavailable':unavailable,
            'input_tokens':sum(r['input_tokens'] for r in measured) if complete else None,
            'output_tokens':sum(r['output_tokens'] for r in measured) if complete else None,
            'cached_input_tokens':sum(r['cached_input_tokens'] or 0 for r in measured) if complete else None}
