#!/usr/bin/env python3
"""Archive a completed subtitle job as a self-contained, hash-addressed bundle."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata
from subtitle_core import file_hash, read_json, write_json, ensure_plain_tree, publish_directory


def safe_name(value):
    value=unicodedata.normalize('NFC',str(value)).strip()
    value=re.sub(r'[\\/:*?"<>|\x00-\x1f]+','-',value)
    value=re.sub(r'\s+',' ',value).strip(' .-')
    return value[:120] or 'Adsız'


def verify_existing_bundle(destination,manifest,expected_files=None):
    destination=Path(destination)
    ensure_plain_tree(destination)
    if not isinstance(manifest,dict) or manifest.get('immutable') is not True:
        raise ValueError('Archive bundle is not marked immutable')
    recorded=manifest.get('files')
    if not isinstance(recorded,list) or not recorded:
        raise ValueError('Archive integrity violation: missing file inventory')
    names=[]
    for item in recorded:
        if not isinstance(item,dict): raise ValueError('Invalid archive file record')
        name=item.get('name'); digest=item.get('sha256')
        if (not isinstance(name,str) or not name or '\\' in name or
                Path(name).is_absolute() or '..' in Path(name).parts or
                Path(name).as_posix()!=name or name=='archive-manifest.json' or
                not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest)):
            raise ValueError('Archive integrity violation: unsafe file record')
        names.append(name)
    if len(names)!=len(set(names)):
        raise ValueError('Archive integrity violation: duplicate file record')
    if expected_files is not None and recorded!=expected_files:
        raise ValueError('Archive destination collision / integrity violation')
    actual_names={p.relative_to(destination).as_posix() for p in destination.rglob('*')
                  if p.is_file() and p!=destination/'archive-manifest.json'}
    if actual_names!=set(names):
        raise ValueError('Archive integrity violation: file inventory changed')
    for item in recorded:
        path=destination/item['name']
        if not path.is_file() or file_hash(path)!=item['sha256']:
            raise ValueError('Archive integrity violation: '+item['name'])
    return manifest


def archive_delivery(job_path, output_path, qa_path, archive_root, review_path=None):
    job,output,qa=map(Path,(job_path,output_path,qa_path))
    ensure_plain_tree(job)
    root=Path(archive_root).expanduser()
    if not output.is_file() or not qa.is_file():
        raise ValueError('Final subtitle and QA sidecar are required for archive')
    context=read_json(job/'context.json')
    title=safe_name(context.get('title') or output.stem)
    bundle_name=safe_name(output.stem)+'--'+file_hash(output)[:12]
    parent=root/title
    destination=parent/bundle_name
    meta=read_json(job/'job.json')
    if not isinstance(meta.get('source_name'),str) or not re.fullmatch(r'source\.[A-Za-z0-9]+',meta['source_name']):
        raise ValueError('Invalid source path in job metadata')
    files=[('final.ass',output),('final.ass.qa.json',qa),('source'+Path(meta['source_name']).suffix,job/meta['source_name']),
           ('job.json',job/'job.json'),('context.json',job/'context.json'),('profile.json',job/'profile.json'),
           ('candidate.ass',job/'candidate.ass'),('review-template.json',job/'review-template.json'),
           ('review.json',Path(review_path) if review_path else job/'review.json'),('technical_report.json',job/'technical_report.json')]
    for folder in ('requests','translations'):
        for p in sorted((job/folder).glob('batch-*.json')):
            files.append((f'{folder}/{p.name}',p))
    for optional in ('series_context.json','series_update.json','learning_report.json','timing_windows.json'):
        p=job/optional
        if p.is_file(): files.append((optional,p))
    for folder in ('content_filter','viewing_breaks','receipts'):
        for p in sorted((job/folder).glob('*.json')):
            files.append((f'{folder}/{p.name}',p))
    manifest={'status':'archived','immutable':True,'title':title,'bundle':str(destination.resolve()),'files':[]}
    parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        old=read_json(destination/'archive-manifest.json')
        verify_existing_bundle(destination,old,[{'name':name,'sha256':file_hash(p)} for name,p in files])
        return old
    with tempfile.TemporaryDirectory(dir=parent) as temp_dir:
        staging=Path(temp_dir)/bundle_name
        staging.mkdir()
        for name,source in files:
            target=staging/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target)
            manifest['files'].append({'name':name,'sha256':file_hash(target)})
        write_json(staging/'archive-manifest.json',manifest,overwrite=False)
        publish_directory(staging,destination)
    return manifest


if __name__=='__main__':
    raise SystemExit('This helper is called by run_pipeline.py finalize.')
