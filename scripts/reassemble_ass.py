#!/usr/bin/env python3
"""Strict candidate assembly; delivery requires run_pipeline finalize review."""
import argparse
import json
import sys
from pathlib import Path
from subtitle_core import build_candidate, load_profile, read_json, save_ass, write_json, text_issues, wrap_text


def fix_line_ergonomics(text, duration_sec):
    profile=load_profile()
    fixed=wrap_text(text,profile['max_cpl'])
    issues,_=text_issues(fixed,round(duration_sec*1000),profile)
    return fixed,issues


def reassemble_ass(source_ass,translated_json,output_ass,font_map=None,profile_path=None):
    if font_map is not None:
        raise ValueError('Use --profile with a single font choice; legacy font maps are no longer applied')
    sidecar=Path(str(output_ass)+'.qa.json')
    if sidecar.exists() or sidecar.is_symlink(): raise ValueError('QA output already exists')
    subs,report=build_candidate(source_ass,read_json(translated_json),load_profile(profile_path))
    report['status']='candidate_needs_review'
    save_ass(subs,output_ass,source_ass)
    try:
        write_json(sidecar,report,overwrite=False)
    except Exception:
        Path(output_ass).unlink(missing_ok=True)
        raise
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True); p.add_argument('--translated',required=True)
    p.add_argument('--output',required=True); p.add_argument('--profile')
    a=p.parse_args()
    try: print(json.dumps(reassemble_ass(a.source,a.translated,a.output,profile_path=a.profile),ensure_ascii=False,indent=2))
    except (ValueError,OSError,TypeError,KeyError) as e:
        print(str(e),file=sys.stderr); sys.exit(2)

if __name__=='__main__': main()
