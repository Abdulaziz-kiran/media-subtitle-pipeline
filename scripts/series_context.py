#!/usr/bin/env python3
"""Maintain immutable, hash-chained series context without subtitle payloads."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unicodedata
from subtitle_core import file_hash, object_hash, read_json, write_json, ensure_plain_tree, publish_directory

SHA256=re.compile(r'[0-9a-f]{64}')
IDENTIFIER=re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}')
COLLECTIONS=('glossary','relationships','voices','uncertainties')
ENTRY_FIELDS={
    'glossary':({'preferred_tr','aliases','note','state','scope','evidence'},'preferred_tr'),
    'relationships':({'description','state','scope','evidence'},'description'),
    'voices':({'guidance','state','scope','evidence'},'guidance'),
    'uncertainties':({'question','status','resolution','state','scope','evidence'},'question'),
}
EVIDENCE_KINDS={'subtitle_line_ids','audio_visual_review','official_reference','user_instruction'}


def bounded_text(value,label,minimum=1,maximum=1000):
    if not isinstance(value,str): raise ValueError(label+' must be text')
    value=unicodedata.normalize('NFC',value).strip()
    if not minimum<=len(value)<=maximum or '\x00' in value:
        raise ValueError(label+' has an invalid length')
    return value


def identifier(value,label):
    value=bounded_text(value,label,1,100)
    if not IDENTIFIER.fullmatch(value): raise ValueError(label+' is not a safe identifier')
    return value


def normalized_label(value):
    """Normalize human labels for collision checks, including repeated whitespace."""
    return ' '.join(unicodedata.normalize('NFC',value).casefold().split())


def evidence_rows(value):
    if not isinstance(value,list) or len(value)>100:
        raise ValueError('Series evidence must be a bounded list')
    for row in value:
        if not isinstance(row,dict) or set(row)!={'episode_id','source_sha256','line_indices','kind'}:
            raise ValueError('Invalid series evidence fields')
        identifier(row['episode_id'],'episode_id')
        if not isinstance(row['source_sha256'],str) or not SHA256.fullmatch(row['source_sha256']):
            raise ValueError('Series evidence needs a source hash')
        ids=row['line_indices']
        if (not isinstance(ids,list) or len(ids)>100 or any(type(i) is not int or i<0 for i in ids)
                or len(ids)!=len(set(ids))):
            raise ValueError('Series evidence line ids are invalid')
        if row['kind'] not in EVIDENCE_KINDS:
            raise ValueError('Invalid series evidence kind')


def validate_entry(collection,key,value):
    identifier(key,collection+' entry id')
    allowed,required=ENTRY_FIELDS[collection]
    if not isinstance(value,dict) or set(value)!=allowed:
        raise ValueError('Invalid '+collection+' entry fields')
    bounded_text(value[required],collection+' entry',1,500)
    if value['state'] not in ('active','retired','conflict') or value['scope'] not in ('series','season'):
        raise ValueError('Invalid series entry state or scope')
    if collection=='glossary':
        if not isinstance(value['aliases'],list) or len(value['aliases'])>50:
            raise ValueError('Glossary aliases must be bounded')
        aliases=[]
        for alias in value['aliases']:
            aliases.append(normalized_label(bounded_text(alias,'glossary alias',1,160)))
        if len(aliases)!=len(set(aliases)): raise ValueError('Duplicate normalized glossary alias')
        bounded_text(value['note'],'glossary note',0,500)
    if collection=='uncertainties':
        if value['status'] not in ('open','resolved'): raise ValueError('Invalid uncertainty status')
        bounded_text(value['resolution'],'uncertainty resolution',0,500)
        if value['status']=='resolved' and not value['resolution'].strip():
            raise ValueError('Resolved uncertainty needs a resolution')
    evidence_rows(value['evidence'])


def validate_series_context(data):
    expected={'schema_version','series_id','title','revision','parent_sha256','through_episode',*COLLECTIONS,'sources'}
    if not isinstance(data,dict) or set(data)!=expected:
        raise ValueError('Invalid series context fields')
    if len(json.dumps(data,ensure_ascii=False))>2_000_000:
        raise ValueError('Series context is too large')
    if data['schema_version']!=1: raise ValueError('Unsupported series context version')
    identifier(data['series_id'],'series_id'); bounded_text(data['title'],'series title',1,200)
    if type(data['revision']) is not int or data['revision']<0: raise ValueError('Invalid series revision')
    parent=data['parent_sha256']
    if data['revision']==0:
        if parent is not None: raise ValueError('Initial series context cannot have a parent')
    elif not isinstance(parent,str) or not SHA256.fullmatch(parent):
        raise ValueError('Series context revision needs a parent hash')
    if data['through_episode'] is not None: identifier(data['through_episode'],'through_episode')
    normalized={}
    for collection in COLLECTIONS:
        values=data[collection]
        if not isinstance(values,dict) or len(values)>5000: raise ValueError(collection+' must be a bounded object')
        for key,value in values.items():
            validate_entry(collection,key,value)
            folded=normalized_label(key)
            if folded in normalized.get(collection,set()): raise ValueError('Normalized series entry collision')
            normalized.setdefault(collection,set()).add(folded)
    aliases={}
    for key,value in data['glossary'].items():
        for alias in [key,*value['aliases']]:
            folded=normalized_label(alias)
            owner=aliases.setdefault(folded,key)
            if owner!=key: raise ValueError('Glossary alias collision')
    if not isinstance(data['sources'],list) or len(data['sources'])>5000:
        raise ValueError('Series sources must be a bounded list')
    for row in data['sources']:
        if not isinstance(row,dict) or set(row)!={'kind','reference','finding'}:
            raise ValueError('Invalid series source fields')
        if row['kind'] not in EVIDENCE_KINDS: raise ValueError('Invalid series source kind')
        bounded_text(row['reference'],'series source reference',3,1000)
        bounded_text(row['finding'],'series source finding',10,500)
    return data


def counts(data):
    return {name:len(data[name]) for name in COLLECTIONS}|{'sources':len(data['sources'])}


def current_context(series_root):
    root=Path(series_root).resolve();ensure_plain_tree(root)
    manifest=read_json(root/'current.json')
    expected={'schema_version','series_id','current_revision','current_file','current_sha256'}
    if not isinstance(manifest,dict) or set(manifest)!=expected or manifest['schema_version']!=1:
        raise ValueError('Invalid series current manifest')
    identifier(manifest['series_id'],'series_id')
    if type(manifest['current_revision']) is not int or manifest['current_revision']<0:
        raise ValueError('Invalid current series revision')
    name=manifest['current_file']
    if not isinstance(name,str) or not re.fullmatch(r'revisions/[0-9]{6}--[0-9a-f]{12}\.json',name):
        raise ValueError('Unsafe series revision path')
    path=root/name
    if not path.is_file() or file_hash(path)!=manifest['current_sha256']:
        raise ValueError('Series current revision integrity failure')
    data=validate_series_context(read_json(path))
    if data['series_id']!=manifest['series_id'] or data['revision']!=manifest['current_revision']:
        raise ValueError('Series manifest/revision mismatch')
    return root,manifest,path,data


def init_series(series_root,series_id,title):
    root=Path(series_root).resolve()
    if root.exists(): raise ValueError('Series root already exists')
    data={'schema_version':1,'series_id':identifier(series_id,'series_id'),'title':bounded_text(title,'series title',1,200),
          'revision':0,'parent_sha256':None,'through_episode':None,
          'glossary':{},'relationships':{},'voices':{},'uncertainties':{},'sources':[]}
    validate_series_context(data);root.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent) as staging:
        tmp=Path(staging)/'series';(tmp/'revisions').mkdir(parents=True);(tmp/'updates').mkdir()
        draft=tmp/'revisions/draft.json';write_json(draft,data,overwrite=False);digest=file_hash(draft)
        name=f'revisions/{data["revision"]:06d}--{digest[:12]}.json';draft.rename(tmp/name)
        write_json(tmp/'current.json',{'schema_version':1,'series_id':data['series_id'],'current_revision':0,
                   'current_file':name,'current_sha256':digest},overwrite=False)
        publish_directory(tmp,root)
    return inspect_series(root)


@contextmanager
def series_lock(root):
    with open(Path(root)/'.lock','a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('Another agent is updating this series context')
        try: yield
        finally: fcntl.flock(lock,fcntl.LOCK_UN)


def validate_update(update,base,base_hash):
    expected={'schema_version','series_id','episode_id','base_revision','base_sha256','reviewed_by','review_summary','changes','next_context'}
    if not isinstance(update,dict) or set(update)!=expected or update['schema_version']!=1:
        raise ValueError('Invalid series update fields')
    identifier(update['series_id'],'series_id');identifier(update['episode_id'],'episode_id')
    bounded_text(update['reviewed_by'],'series update reviewer',1,160)
    bounded_text(update['review_summary'],'series update review summary',20,1000)
    if update['series_id']!=base['series_id'] or update['base_revision']!=base['revision'] or update['base_sha256']!=base_hash:
        raise ValueError('Stale series update base')
    nxt=validate_series_context(update['next_context'])
    if (nxt['series_id']!=base['series_id'] or nxt['title']!=base['title'] or nxt['revision']!=base['revision']+1
            or nxt['parent_sha256']!=base_hash or nxt['through_episode']!=update['episode_id']):
        raise ValueError('Series update lineage mismatch')
    required_changes={}
    for collection in COLLECTIONS:
        if set(base[collection])-set(nxt[collection]): raise ValueError('Series entries cannot be deleted; retire them')
        for key in set(base[collection])&set(nxt[collection]):
            if object_hash(base[collection][key])!=object_hash(nxt[collection][key]):
                required_changes[(collection,key)]=object_hash(base[collection][key])
    if nxt['sources'][:len(base['sources'])]!=base['sources']:
        raise ValueError('Existing series sources cannot be changed or removed')
    changes=update['changes']
    if not isinstance(changes,list) or len(changes)>1000: raise ValueError('Series changes must be a bounded list')
    provided={}
    for row in changes:
        if not isinstance(row,dict) or set(row)!={'collection','key','expected_entry_sha256','reason'}:
            raise ValueError('Invalid series change record')
        key=(row['collection'],row['key'])
        if row['collection'] not in COLLECTIONS or key in provided:
            raise ValueError('Invalid or duplicate series change target')
        identifier(row['key'],'series change key')
        if not isinstance(row['expected_entry_sha256'],str) or not SHA256.fullmatch(row['expected_entry_sha256']):
            raise ValueError('Series change needs an entry hash')
        bounded_text(row['reason'],'series change reason',20,1000)
        provided[key]=row['expected_entry_sha256']
    if provided!=required_changes: raise ValueError('Changed series entries need exact prior hashes and reasons')
    return nxt


def advance_series(series_root,update_path):
    root=Path(series_root).resolve();update_path=Path(update_path).resolve()
    with series_lock(root):
        root,manifest,base_path,base=current_context(root);base_hash=manifest['current_sha256']
        update=read_json(update_path);nxt=validate_update(update,base,base_hash)
        with tempfile.TemporaryDirectory(dir=root/'revisions') as staging:
            draft=Path(staging)/'next.json';write_json(draft,nxt,overwrite=False);digest=file_hash(draft)
            name=f'revisions/{nxt["revision"]:06d}--{digest[:12]}.json';target=root/name
            if target.exists():
                if file_hash(target)!=digest: raise ValueError('Series revision destination collision')
            else: shutil.copy2(draft,target)
        update_digest=file_hash(update_path);update_name=f'updates/{nxt["revision"]:06d}--{update_digest[:12]}.json'
        update_target=root/update_name
        if update_target.exists():
            if file_hash(update_target)!=update_digest: raise ValueError('Series update destination collision')
        else: shutil.copy2(update_path,update_target)
        write_json(root/'current.json',{'schema_version':1,'series_id':nxt['series_id'],'current_revision':nxt['revision'],
                   'current_file':name,'current_sha256':digest},overwrite=True)
    return inspect_series(root)


def inspect_series(series_root):
    root,manifest,path,data=current_context(series_root)
    result={'schema_version':1,'series_root':str(root),'series_id':data['series_id'],'current_revision':data['revision'],
            'current_sha256':manifest['current_sha256'],'current_file':manifest['current_file'],
            'through_episode':data['through_episode'],'counts':counts(data)}
    if len(json.dumps(result,ensure_ascii=False))>2000: raise ValueError('Series receipt exceeded its fixed budget')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);cmd=p.add_subparsers(dest='command',required=True)
    q=cmd.add_parser('init');q.add_argument('--series-root',required=True);q.add_argument('--series-id',required=True);q.add_argument('--title',required=True)
    q=cmd.add_parser('inspect');q.add_argument('--series-root',required=True)
    q=cmd.add_parser('advance');q.add_argument('--series-root',required=True);q.add_argument('--update',required=True)
    q=cmd.add_parser('validate');q.add_argument('--context',required=True)
    a=p.parse_args()
    try:
        if a.command=='init': result=init_series(a.series_root,a.series_id,a.title)
        elif a.command=='inspect': result=inspect_series(a.series_root)
        elif a.command=='advance': result=advance_series(a.series_root,a.update)
        else:
            data=validate_series_context(read_json(a.context));result={'status':'valid','sha256':file_hash(a.context),'counts':counts(data)}
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError) as e:
        print(json.dumps({'status':'blocked','reason':str(e)},ensure_ascii=False),file=sys.stderr);sys.exit(2)


if __name__=='__main__': main()
