#!/usr/bin/env python3
"""Aggregate actual per-job technical reports; never synthesize semantic scores."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from subtitle_core import read_json,write_json


def analyze_reports(paths):
    counts=Counter();errors=[];jobs=[]
    for path in paths:
        try:
            r=read_json(path)
            if not isinstance(r.get('lines'),list):raise ValueError('No line records')
            for line in r['lines']:counts.update(line['issues'])
            jobs.append({'path':str(path),'status':r.get('status'),'lines':len(r['lines'])})
        except (ValueError,OSError,KeyError,TypeError) as e:errors.append({'path':str(path),'error':str(e)})
    return {'jobs':jobs,'issue_counts':dict(counts),'malformed_reports':errors,'semantic_quality_score':None}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--jobs-dir',required=True);p.add_argument('--output')
    a=p.parse_args();paths=sorted(Path(a.jobs_dir).rglob('technical_report.json'))
    if not paths:p.error('No technical reports found')
    r=analyze_reports(paths)
    if a.output:write_json(a.output,r,overwrite=False)
    print(json.dumps(r,ensure_ascii=False,indent=2));sys.exit(1 if r['malformed_reports'] else 0)

if __name__=='__main__':main()
