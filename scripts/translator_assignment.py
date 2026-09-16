#!/usr/bin/env python3
"""Create contiguous translator-worker assignments for one prepared episode/film job."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys
from subtitle_core import read_json, write_json, file_hash


def plan(job_path, profile_path):
    job=Path(job_path).resolve(); meta=read_json(job/'job.json'); profile=read_json(profile_path)
    cfg=profile.get('translator_partition')
    if not isinstance(cfg,dict): raise ValueError('Missing translator_partition profile')
    required={'never_mix_episode_ids','one_worker_per_normal_episode','split_threshold_translatable_lines','target_lines_per_worker_after_split','max_workers_per_episode','split_only_at_existing_batch_or_scene_boundaries'}
    if set(cfg)!=required or cfg['never_mix_episode_ids'] is not True or cfg['split_only_at_existing_batch_or_scene_boundaries'] is not True:
        raise ValueError('Invalid translator partition policy')
    threshold=cfg['split_threshold_translatable_lines']; target=cfg['target_lines_per_worker_after_split']; max_workers=cfg['max_workers_per_episode']
    if any(type(v) is not int or v<1 for v in (threshold,target,max_workers)): raise ValueError('Translator partition limits must be positive integers')
    batches=[]
    for row in meta.get('batches',[]):
        if not isinstance(row,dict) or not isinstance(row.get('file'),str) or not isinstance(row.get('indices'),list) or not row['indices']:
            raise ValueError('Invalid prepared batch metadata')
        batches.append({'file':row['file'],'indices':row['indices'],'line_count':len(row['indices'])})
    if not batches: raise ValueError('Prepared job has no translatable batches')
    total=sum(b['line_count'] for b in batches)
    workers=1 if total<=threshold else min(max_workers,max(2,math.ceil(total/target)))
    # Balance only across existing batch boundaries; no line from another job/episode can enter this plan.
    remaining_lines=total; remaining_workers=workers; groups=[]; current=[]; current_lines=0
    for i,batch in enumerate(batches):
        desired=math.ceil(remaining_lines/remaining_workers)
        batches_left=len(batches)-i
        # Close a non-empty group when adding the next batch would overshoot the balanced target
        # and enough batches remain to give each future worker at least one batch.
        if current and remaining_workers>1 and batches_left>=remaining_workers and current_lines+batch['line_count']>desired:
            groups.append(current); remaining_lines-=current_lines; remaining_workers-=1; current=[]; current_lines=0
        current.append(batch); current_lines+=batch['line_count']
    if current: groups.append(current)
    # If coarse scene batches prevented the requested count, accept fewer workers rather than split a batch.
    episode_id=meta.get('episode_id') or job.name
    result={'schema_version':1,'job':str(job),'episode_id':episode_id,'source_sha256':meta['source_sha256'],
            'policy_sha256':file_hash(profile_path),'total_translatable_lines':total,'worker_count':len(groups),'workers':[]}
    for n,group in enumerate(groups,1):
        indices=[idx for b in group for idx in b['indices']]
        result['workers'].append({'worker_id':f'translator-{n:02d}','batch_files':[b['file'] for b in group],
                                  'line_count':len(indices),'first_index':min(indices),'last_index':max(indices)})
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--job',required=True);p.add_argument('--profile',default=str(Path(__file__).resolve().parents[1]/'resources/orchestration_profile.json'));p.add_argument('--output')
    a=p.parse_args()
    try:
        result=plan(a.job,a.profile)
        output=Path(a.output) if a.output else Path(a.job)/'translator_plan.json'
        write_json(output,result,overwrite=True)
        print(json.dumps({'status':'ready','output':str(output.resolve()),'sha256':file_hash(output),'worker_count':result['worker_count'],'total_translatable_lines':result['total_translatable_lines']},ensure_ascii=False,indent=2))
    except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError) as e:
        print(json.dumps({'status':'blocked','reason':str(e)},ensure_ascii=False),file=sys.stderr);sys.exit(2)
if __name__=='__main__': main()
