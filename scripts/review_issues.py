#!/usr/bin/env python3
"""Validate reviewer issue reports before a repair worker edits translations."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys
import pysubs2
from subtitle_core import file_hash, read_json

CATEGORIES={
    'meaning_shift','negation','subject_object','possessive','question','speaker','address','terminology',
    'character_voice','register','callback','wordplay','omission','addition','format','karaoke','other'
}
SHA256=re.compile(r'[0-9a-f]{64}')


def validate(data, source=None, candidate=None):
    if not isinstance(data,dict) or set(data)!={'schema_version','source_sha256','candidate_sha256','reviewer','issues'} or data['schema_version']!=1:
        raise ValueError('Invalid review issues file')
    for key in ('source_sha256','candidate_sha256'):
        if not isinstance(data[key],str) or not SHA256.fullmatch(data[key]): raise ValueError(key+' must be SHA-256')
    if not isinstance(data['reviewer'],str) or not data['reviewer'].strip(): raise ValueError('reviewer is required')
    if not isinstance(data['issues'],list) or not data['issues']: raise ValueError('issues must be a non-empty list')
    seen=set(); max_index=None
    if source is not None:
        source=Path(source); max_index=len(pysubs2.load(source))-1
        if file_hash(source)!=data['source_sha256']: raise ValueError('Stale source binding in issues file')
    if candidate is not None:
        candidate=Path(candidate)
        if file_hash(candidate)!=data['candidate_sha256']: raise ValueError('Stale candidate binding in issues file')
    for row in data['issues']:
        if not isinstance(row,dict) or set(row)!={'index','category','reason','repair_instruction'}:
            raise ValueError('Invalid issue row')
        if type(row['index']) is not int or row['index']<0 or (max_index is not None and row['index']>max_index):
            raise ValueError('Invalid issue line index')
        if row['category'] not in CATEGORIES: raise ValueError('Invalid issue category')
        key=(row['index'],row['category'])
        if key in seen: raise ValueError('Duplicate issue category for line')
        seen.add(key)
        if not isinstance(row['reason'],str) or len(row['reason'].strip())<10: raise ValueError('Issue needs a concrete reason')
        if not isinstance(row['repair_instruction'],str) or len(row['repair_instruction'].strip())<5: raise ValueError('Issue needs a repair instruction')
    return data


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True);p.add_argument('--source');p.add_argument('--candidate')
    a=p.parse_args()
    try:
        data=validate(read_json(a.input),a.source,a.candidate)
        print(json.dumps({'status':'valid','issues':len(data['issues']),'sha256':file_hash(a.input)},ensure_ascii=False,indent=2))
    except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError) as e:
        print(json.dumps({'status':'blocked','reason':str(e)},ensure_ascii=False),file=sys.stderr);sys.exit(2)
if __name__=='__main__': main()
