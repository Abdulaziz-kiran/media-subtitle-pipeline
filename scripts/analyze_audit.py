#!/usr/bin/env python3
"""Aggregate actual per-job technical reports; never synthesize semantic scores."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from subtitle_core import read_json,write_json
from usage_ledger import summarize_usage_ledger


def analyze_reports(paths):
    counts=Counter();errors=[];jobs=[];usage=[]
    for path in paths:
        try:
            r=read_json(path)
            if not isinstance(r.get('lines'),list):raise ValueError('No line records')
            for line in r['lines']:counts.update(line['issues'])
            usage_path=path.parent/'token_usage.json'
            try: token_usage=summarize_usage_ledger(read_json(usage_path) if usage_path.is_file() else None)
            except (ValueError,OSError,KeyError,TypeError): token_usage={'measurement_status':'invalid','runs_total':0,'runs_measured':0,'runs_unavailable':0,'input_tokens':None,'output_tokens':None,'cached_input_tokens':None}
            jobs.append({'path':str(path),'status':r.get('status'),'lines':len(r['lines']),'token_usage':token_usage})
            usage.append(token_usage)
        except (ValueError,OSError,KeyError,TypeError) as e:errors.append({'path':str(path),'error':str(e)})
    complete=[u for u in usage if u['measurement_status']=='measured']
    return {'jobs':jobs,'issue_counts':dict(counts),'malformed_reports':errors,'semantic_quality_score':None,
            'token_usage':{'jobs_total':len(usage),'jobs_fully_measured':len(complete),'jobs_needing_usage_record':len(usage)-len(complete),
                           'input_tokens':sum(u['input_tokens'] for u in complete) if len(complete)==len(usage) else None,
                           'output_tokens':sum(u['output_tokens'] for u in complete) if len(complete)==len(usage) else None,
                           'cached_input_tokens':sum(u['cached_input_tokens'] for u in complete) if len(complete)==len(usage) else None,
                           'note':'Totals remain null until every included job has measured, non-estimated usage.'}}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--jobs-dir',required=True);p.add_argument('--output')
    a=p.parse_args();paths=sorted(Path(a.jobs_dir).rglob('technical_report.json'))
    if not paths:p.error('No technical reports found')
    r=analyze_reports(paths)
    if a.output:write_json(a.output,r,overwrite=False)
    print(json.dumps(r,ensure_ascii=False,indent=2));sys.exit(1 if r['malformed_reports'] else 0)

if __name__=='__main__':main()
