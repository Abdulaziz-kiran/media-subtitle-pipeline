#!/usr/bin/env python3
"""Prepare → active-agent translation → build → actual review → finalize.
No simulated LLM scores, API charges, or implied unattended translation.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import fcntl
import json
import re
import os
from pathlib import Path
import shutil
import sys
import tempfile
import pysubs2
from archive_delivery import archive_delivery, verify_existing_bundle
from subtitle_core import (VERSION, ROOT, file_hash, object_hash, read_json, write_json, load_profile,
                           protected, role, classify_line, build_candidate, save_ass, response_item, visible, ensure_plain_tree, publish_directory)
from series_context import validate_series_context


def ensure_mutable_job(job):
    ensure_plain_tree(job)
    if (Path(job)/'archive-manifest.json').exists():
        raise ValueError('Archived bundles are read-only; use resume-from-archive with a new job path')


def validate_context(context):
    if not isinstance(context,dict): raise ValueError('Context must be an object')
    if context.get('context_prepared') is not True:
        raise ValueError('Context must be explicitly prepared before translation')
    for key in ('title','summary','source_language','target_language'):
        if not isinstance(context.get(key),str) or not context[key].strip():
            raise ValueError('Prepared context needs '+key)
    if not isinstance(context.get('media_type'),str) or not context['media_type'].strip():
        raise ValueError('Prepared context needs a textual media_type')
    if len(context['summary'].strip())<20: raise ValueError('Prepared context summary is too weak to audit')
    for key,kind in (('glossary',dict),('relationships',list),('voices',dict),('uncertainties',list),('songs',list),('context_sources',list)):
        if not isinstance(context.get(key),kind): raise ValueError('Invalid context field: '+key)
    allowed_sources={'subtitle','media_metadata','official_reference','user_instruction','audio_visual_review'}
    if not context['context_sources']: raise ValueError('Prepared context needs at least one concrete source')
    for source in context['context_sources']:
        if (not isinstance(source,dict) or source.get('kind') not in allowed_sources
                or not isinstance(source.get('reference'),str) or len(source['reference'].strip())<3
                or not isinstance(source.get('finding'),str) or len(source['finding'].strip())<10):
            raise ValueError('Prepared context source needs kind, reference and a concrete finding')
    checks=context.get('context_checks'); fields=('glossary','relationships','voices','uncertainties','songs')
    allowed_checks={'populated','reviewed_none_found','not_applicable'}
    if not isinstance(checks,dict) or set(checks)!=set(fields) or any(checks[k] not in allowed_checks for k in fields):
        raise ValueError('Prepared context needs explicit review status for glossary, relationships, voices, uncertainties and songs')
    for key in fields:
        populated=bool(context[key])
        if (checks[key]=='populated')!=populated:
            raise ValueError('Context review status does not match field content: '+key)
    status=context.get('original_audio_status')
    if status not in ('verified','single_stream','unknown','not_applicable'):
        raise ValueError('original_audio_status must be verified, single_stream, unknown or not_applicable')
    if not isinstance(context.get('original_audio_language',''),str) or not isinstance(context.get('original_audio_evidence',''),str):
        raise ValueError('Original audio language/evidence must be text')
    if status in ('verified','single_stream'):
        if not context.get('original_audio_language','').strip() or len(context.get('original_audio_evidence','').strip())<10:
            raise ValueError('Verified original audio needs language and evidence')
    elif context.get('original_audio_language'):
        raise ValueError('Unverified original audio cannot name a language')
    return context


@contextmanager
def job_lock(job):
    with open(Path(job)/'.lock','a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another process is updating this job')
        try: yield
        finally: fcntl.flock(lock,fcntl.LOCK_UN)


def prepare(source, job, profile_path=None, context_path=None, series_context_path=None, episode_id=None):
    source,job=Path(source).resolve(),Path(job).resolve()
    if job.exists():
        raise ValueError('Job already exists; use status/build to resume')
    profile=load_profile(profile_path)
    context=read_json(context_path) if context_path else read_json(ROOT/'resources/context_template.json')
    if not isinstance(context,dict): raise ValueError('Context must be an object')
    if not context.get('title'): context['title']=source.stem
    validate_context(context)
    series_context=None
    if series_context_path:
        series_context=validate_series_context(read_json(series_context_path))
        if not isinstance(episode_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}',episode_id):
            raise ValueError('Series jobs need a safe episode_id')
    elif episode_id is not None:
        raise ValueError('episode_id requires a series context')
    subs=pysubs2.load(source)
    if not subs: raise ValueError('No subtitle events')
    if any(e.start<0 or e.end<=e.start for e in subs if not e.is_comment):
        raise ValueError('Invalid source times; correct the source copy before preparation')
    indices=[i for i,e in enumerate(subs) if classify_line(e,profile)=='TRANSLATABLE']
    if not indices: raise ValueError('No translatable text')
    batches=[]; current=[]
    for i in indices:
        if current and (len(current)>=profile['batch_size'] or subs[i].start-subs[current[-1]].end>=profile['scene_gap_ms']):
            batches.append(current); current=[]
        current.append(i)
    if current: batches.append(current)
    job.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=job.parent) as staging:
        tmp=Path(staging)/'job'; tmp.mkdir()
        source_name='source'+source.suffix.lower()
        shutil.copyfile(source,tmp/source_name)
        sha=file_hash(tmp/source_name)
        write_json(tmp/'profile.json',profile)
        write_json(tmp/'context.json',context)
        if series_context is not None: write_json(tmp/'series_context.json',series_context)
        context_sha=file_hash(tmp/'context.json');profile_sha=file_hash(tmp/'profile.json')
        series_sha=file_hash(tmp/'series_context.json') if series_context is not None else None
        bindings={'source_sha256':sha,'episode_context_sha256':context_sha,'profile_sha256':profile_sha,
                  'series_context_sha256':series_sha}
        translation_input_sha=object_hash(bindings) if series_context is not None else None
        (tmp/'requests').mkdir(); (tmp/'translations').mkdir()
        entries=[]
        for n,ids in enumerate(batches,1):
            name=f'batch-{n:04d}.json'
            before=[i for i in indices if i<ids[0]][-2:]
            after=[i for i in indices if i>ids[-1]][:2]
            def event_record(i):
                e=subs[i]
                return {'index':i,'start_ms':e.start,'end_ms':e.end,'speaker':e.name,'role':role(e),'source':protected(e.text)}
            request_core={'source_sha256':sha,'context_file':'../context.json','profile_file':'../profile.json',
                          'before':[event_record(i) for i in before], 'lines':[event_record(i) for i in ids],
                          'after':[event_record(i) for i in after]}
            if series_context is not None:
                request_core.update(series_context_file='../series_context.json',translation_input_sha256=translation_input_sha,**bindings)
            request_sha=object_hash(request_core)
            response={'source_sha256':sha,'lines':[response_item(subs[i],i) for i in ids]}
            if series_context is not None:
                response.update(request_sha256=request_sha,translation_input_sha256=translation_input_sha,**bindings)
            request=dict(request_core,request_sha256=request_sha,response_shape=response)
            write_json(tmp/'requests'/name,request)
            entry={'file':name,'indices':ids}
            if series_context is not None: entry['request_sha256']=request_sha
            entries.append(entry)
        metadata={'engine_version':VERSION,'source_name':source_name,'source_original':str(source),'source_sha256':sha,
                  'batches':entries,'passthrough':[{'index':i,'role':role(e)} for i,e in enumerate(subs) if i not in indices]}
        if series_context is not None:
            metadata.update(series_id=series_context['series_id'],series_revision=series_context['revision'],episode_id=episode_id,
                            translation_input_sha256=translation_input_sha,translation_bindings=bindings)
        write_json(tmp/'job.json',metadata)
        publish_directory(tmp,job)
    return {'status':'awaiting_translation','job':str(job),'batches':len(batches),'lines':len(indices),'passthrough':len(metadata['passthrough'])}


def load_job(job):
    job=Path(job)
    ensure_plain_tree(job)
    if (job/'archive-manifest.json').is_file():
        verify_existing_bundle(job,read_json(job/'archive-manifest.json'))
    meta=read_json(job/'job.json')
    if not isinstance(meta.get('source_name'),str) or not re.fullmatch(r'source\.[A-Za-z0-9]+',meta['source_name']):
        raise ValueError('Invalid source path')
    source=job/meta['source_name']
    if file_hash(source)!=meta['source_sha256']: raise ValueError('Job source was modified')
    profile=load_profile(job/'profile.json')
    bindings=meta.get('translation_bindings')
    if bindings is not None:
        if not isinstance(bindings,dict) or set(bindings)!={'source_sha256','episode_context_sha256','profile_sha256','series_context_sha256'}:
            raise ValueError('Invalid translation bindings')
        series_path=job/'series_context.json'
        if not series_path.is_file(): raise ValueError('Series context snapshot is missing')
        series=validate_series_context(read_json(series_path))
        current={'source_sha256':meta['source_sha256'],'episode_context_sha256':file_hash(job/'context.json'),
                 'profile_sha256':file_hash(job/'profile.json'),'series_context_sha256':file_hash(series_path)}
        if current!=bindings or object_hash(bindings)!=meta.get('translation_input_sha256'):
            raise ValueError('Series translation inputs changed after preparation')
        if series['series_id']!=meta.get('series_id') or series['revision']!=meta.get('series_revision'):
            raise ValueError('Series context metadata mismatch')
    return meta,source,profile


def read_translation_batch(job,meta,b,names=None):
    names=names if names is not None else set()
    if not isinstance(b,dict) or not isinstance(b.get('file'),str) or not re.fullmatch(r'batch-[0-9]{4,}\.json',b['file']) or b['file'] in names:
        raise ValueError('Invalid/duplicate translation batch path')
    names.add(b['file'])
    p=Path(job)/'translations'/b['file']
    if not p.is_file(): raise ValueError('Missing batch: '+b['file'])
    data=read_json(p)
    if data.get('source_sha256')!=meta['source_sha256']: raise ValueError('Stale batch: '+b['file'])
    bindings=meta.get('translation_bindings')
    if bindings is not None:
        if any(data.get(key)!=value for key,value in bindings.items()):
            raise ValueError('Stale translation binding: '+b['file'])
        if data.get('translation_input_sha256')!=meta.get('translation_input_sha256') or data.get('request_sha256')!=b.get('request_sha256'):
            raise ValueError('Stale request binding: '+b['file'])
    batch=data.get('lines',[])
    ids=[x.get('index') for x in batch]
    if any(type(i) is not int for i in ids) or len(ids)!=len(set(ids)) or set(ids)!=set(b['indices']):
        raise ValueError('Batch coverage mismatch: '+b['file'])
    return batch


def collect(job,meta):
    lines=[];names=set()
    for b in meta['batches']:
        lines.extend(read_translation_batch(job,meta,b,names))
    return {'source_sha256':meta['source_sha256'],'lines':sorted(lines,key=lambda x:x['index'])}


def evaluate(job):
    job=Path(job); meta,source,profile=load_job(job)
    data=collect(job,meta)
    windows=read_json(job/'timing_windows.json') if (job/'timing_windows.json').exists() else {}
    context=validate_context(read_json(job/'context.json'))
    series_context=validate_series_context(read_json(job/'series_context.json')) if (job/'series_context.json').is_file() else None
    subs,report=build_candidate(source,data,profile,windows)
    report['input_sha256']=object_hash({'source':meta['source_sha256'],'translation':data,'profile':profile,'context':context,
                                        'series_context':series_context,'windows':windows,'version':VERSION})
    report['translation_sha256']=object_hash(data)
    report['context_sha256']=object_hash(context)
    report['profile_sha256']=object_hash(profile)
    report['series_context_sha256']=file_hash(job/'series_context.json') if series_context is not None else None
    report['status']='awaiting_review'
    return subs,report,meta,source


def build(job):
    job=Path(job)
    ensure_mutable_job(job)
    with job_lock(job):
        subs,report,meta,source=evaluate(job)
        save_ass(subs,job/'candidate.ass',source,overwrite=True)
        report['candidate_sha256']=file_hash(job/'candidate.ass')
        write_json(job/'technical_report.json',report)
        template={'source_sha256':meta['source_sha256'],'input_sha256':report['input_sha256'],
                  'candidate_sha256':report['candidate_sha256'],'reviewer':'','mode':'same_agent_second_pass',
                  'lines':[{'index':r['index'],'reviewed':False,'formatting_reviewed':False if r['format_sensitive'] else None,'issues':[]} for r in report['lines']],
                  'technical_exceptions':[], 'learning_report_reviewed':False,'learning_report_sha256':None,
                  'learning_report_review_summary':'','summary':''}
        # Existing review is never replaced; it will be rejected if stale.
        write_json(job/'review-template.json',template)
        return {'status':'awaiting_review','candidate':str(job/'candidate.ass'), 'technical_issues':sum(len(r['issues']) for r in report['lines']), 'review_template':str(job/'review-template.json')}


def validate_review(review,report,learning_report=None):
    for key in ('source_sha256','input_sha256','candidate_sha256'):
        if review.get(key)!=report[key]: raise ValueError('Missing/stale review binding: '+key)
    if not isinstance(review.get('reviewer'),str) or not review['reviewer'].strip() or not isinstance(review.get('summary'),str) or len(review['summary'].strip())<20:
        raise ValueError('Actual reviewer and review summary required')
    if review.get('mode') not in ('same_agent_second_pass','independent_agent','human'):
        raise ValueError('Explicit review mode required')
    reviewed=review.get('lines',[])
    indices=[r.get('index') for r in reviewed]
    expected={r['index'] for r in report['lines']}
    if any(type(i) is not int for i in indices) or len(indices)!=len(set(indices)) or set(indices)!=expected:
        raise ValueError('Review coverage incomplete')
    for r in reviewed:
        if r.get('reviewed') is not True or r.get('issues')!=[]:
            raise ValueError('Unreviewed line or unresolved semantic issue: '+str(r.get('index')))
        source_line=next(x for x in report['lines'] if x['index']==r['index'])
        if source_line.get('format_sensitive') and r.get('formatting_reviewed') is not True:
            raise ValueError('Formatting/karaoke placement was not reviewed: '+str(r.get('index')))
    allowed={}
    for e in review.get('technical_exceptions',[]):
        key=(e.get('index'),e.get('code'))
        if type(key[0]) is not int or key in allowed or not str(e.get('reason','')).strip():
            raise ValueError('Invalid exception')
        if key[1] not in ('MIN_DURATION','MAX_DURATION','SHORT_LINGER','CPS_HIGH','CPL_HIGH','TOO_MANY_LINES','DIALOGUE_OVERLAP'):
            raise ValueError('This technical fault cannot be waived')
        allowed[key]=e['reason']
    current={(r['index'],code) for r in report['lines'] for code in r['issues']}
    if set(allowed)-current: raise ValueError('Exception does not match a current issue')
    missing=current-set(allowed)
    if missing: raise ValueError('Unresolved technical issues: '+str(sorted(missing)))
    if learning_report:
        if review.get('learning_report_sha256')!=file_hash(learning_report):
            raise ValueError('Learning report review hash is missing or stale')
        if review.get('learning_report_reviewed') is not True or not isinstance(review.get('learning_report_review_summary'),str) or len(review['learning_report_review_summary'].strip())<20:
            raise ValueError('Learning report needs an explicit semantic review attestation')


def validate_learning_report(job,context,source):
    prefs=read_json(ROOT/'resources/preferences.json')
    language=str(context.get('source_language','')).casefold()
    if not prefs.get('english_learning_report') or language not in ('en','eng','english','ingilizce'):
        return None
    path=Path(job)/'learning_report.json'
    if not path.is_file():
        raise ValueError('English-source job requires learning_report.json')
    report=read_json(path)
    if report.get('learner_profile')!=prefs['english_learner_profile']:
        raise ValueError('Learning report learner profile is missing or stale')
    estimate=report.get('estimated_cefr')
    levels={'A1','A2','B1','B2','C1','C2','A1-A2','A2-B1','B1-B2','B2-C1','C1-C2'}
    if not isinstance(estimate,dict) or estimate.get('with_english_subtitles') not in levels:
        raise ValueError('Learning report needs a controlled subtitle-reading estimate')
    listening=estimate.get('listening_without_subtitles')
    if listening=='not_assessed':
        if (estimate.get('listening_assessment_status')!='not_assessed' or
                not isinstance(estimate.get('listening_limitations'),str) or len(estimate['listening_limitations'].strip())<20):
            raise ValueError('Unassessed listening needs an explicit status and concrete limitation')
    elif listening not in levels or estimate.get('listening_assessment_status','assessed')!='assessed':
        raise ValueError('Learning report needs a controlled listening estimate or honest not_assessed status')
    if estimate.get('confidence') not in ('low','medium','high'):
        raise ValueError('Learning report confidence must be low, medium or high')
    subs=pysubs2.load(source)
    def grounded(items,label):
        if not isinstance(items,list) or not items: raise ValueError('Learning report needs '+label)
        for item in items:
            if not isinstance(item,dict) or type(item.get('line_index')) is not int or not isinstance(item.get('source_excerpt'),str) or not item['source_excerpt'].strip() or not isinstance(item.get('reason'),str) or not item['reason'].strip():
                raise ValueError('Invalid learning report '+label)
            i=item['line_index']
            if i<0 or i>=len(subs) or item['source_excerpt'].strip() not in visible(subs[i].text):
                raise ValueError('Learning report evidence is not grounded in the source')
    grounded(estimate.get('evidence'),'evidence')
    points=report.get('learning_points')
    if not isinstance(points,list) or not points:
        raise ValueError('Learning report needs learning points')
    for point in points:
        if not isinstance(point,dict) or type(point.get('line_index')) is not int or not all(isinstance(point.get(k),str) and point[k].strip() for k in ('source_excerpt','meaning_tr','why_useful')):
            raise ValueError('Invalid learning point')
        i=point['line_index']
        if i<0 or i>=len(subs) or point['source_excerpt'].strip() not in visible(subs[i].text):
            raise ValueError('Learning point is not grounded in the source')
    if report.get('fit_for_learner') not in ('comfortable','productive_stretch','intensive_support'):
        raise ValueError('Learning report fit must use a controlled value')
    if report.get('personal_assessment') is not False:
        raise ValueError('Learning report must state personal_assessment=false')
    if not isinstance(report.get('limitations'),str) or not report['limitations'].strip():
        raise ValueError('Learning report limitation is required')
    return path


def finalize(job,output,review_path=None,archive_root=None):
    job,output=Path(job),Path(output)
    ensure_mutable_job(job)
    with job_lock(job):
        subs,report,meta,source=evaluate(job)
        candidate=job/'candidate.ass'
        import hashlib
        expected=hashlib.sha256(subs.to_string('ass').encode()).hexdigest()
        if not candidate.exists() or file_hash(candidate)!=expected:
            raise ValueError('Candidate missing/stale; run build and review it')
        report['candidate_sha256']=expected
        if read_json(job/'technical_report.json')!=report:
            raise ValueError('Technical report stale; rebuild and review')
        learning_report=validate_learning_report(job,read_json(job/'context.json'),source)
        actual_review=Path(review_path) if review_path else job/'review.json'
        review=read_json(actual_review)
        validate_review(review,report,learning_report)
        if output.resolve()==Path(meta['source_original']).resolve():
            raise ValueError('Cannot overwrite original source')
        sidecar=output.with_suffix(output.suffix+'.qa.json')
        if any(p.exists() or p.is_symlink() for p in (output,sidecar)):
            raise ValueError('Output already exists; choose a new destination')
        output.parent.mkdir(parents=True,exist_ok=True)
        created=[]
        try:
            with tempfile.TemporaryDirectory(dir=output.parent) as staging:
                staged=Path(staging)/output.name
                staged_qa=staged.with_suffix(staged.suffix+'.qa.json')
                save_ass(subs,staged,source)
                cut_records=[{'file':p.name,'sha256':file_hash(p)} for p in sorted((job/'content_filter').glob('cut-*.json'))]
                viewing_break_records=[{'file':p.name,'sha256':file_hash(p)} for p in sorted((job/'viewing_breaks').glob('*.json'))]
                delivery={'status':'delivered','engine_version':VERSION,'output_sha256':file_hash(staged),'source_sha256':meta['source_sha256'],
                          'review_sha256':object_hash(review),'reviewer':review['reviewer'],'review_mode':review['mode'],
                          'semantic_review':'attested_by_reviewer','technical_exceptions':review['technical_exceptions'],
                          'translated_lines':report['translated_lines'],'passthrough_lines':report['passthrough_lines'],
                          'visual_review':'not_verified_by_this_command',
                          'learning_report_sha256':file_hash(learning_report) if learning_report else None,
                          'content_filter_evidence':cut_records,
                          'viewing_break_evidence':viewing_break_records}
                write_json(staged_qa,delivery,overwrite=False)
                prefs=read_json(ROOT/'resources/preferences.json')
                archive=archive_delivery(job,staged,staged_qa,Path(archive_root or prefs['archive_root']).expanduser(),review_path=actual_review)
                delivery['archive']=archive['bundle']
                # Publication happens only after the complete archive has succeeded.
                os.link(staged,output); created.append(output)
                os.link(staged_qa,sidecar); created.append(sidecar)
                write_json(job/'delivery.json',dict(delivery,output=str(output.resolve())))
                return delivery
        except Exception:
            for path in reversed(created): path.unlink(missing_ok=True)
            raise


def status(job):
    meta,source,profile=load_job(job)
    missing=[b['file'] for b in meta['batches'] if not (Path(job)/'translations'/b['file']).is_file()]
    return {'batches':len(meta['batches']),'missing_batches':missing,'candidate_exists':(Path(job)/'candidate.ass').exists(),
            'review_exists':(Path(job)/'review.json').exists(),'note':'Existence is not validation; finalize checks content and hashes.'}


def handoff(job):
    """Return a bounded resume brief without subtitle text, logs, or batch lists."""
    job=Path(job).resolve()
    meta,source,profile=load_job(job)
    missing=[b['file'] for b in meta['batches'] if not (job/'translations'/b['file']).is_file()]
    candidate=(job/'candidate.ass').is_file()
    technical_report=(job/'technical_report.json').is_file()
    review=(job/'review.json').is_file()
    delivered=(job/'delivery.json').is_file()
    next_batch=missing[0] if missing else None
    startup_files=['context.json','profile.json']
    if (job/'series_context.json').is_file(): startup_files.append('series_context.json')
    if next_batch:
        startup_files.append('requests/'+next_batch)
        next_action='translate_next_batch'
    elif not candidate or not technical_report:
        next_action='build_candidate'
    elif not review:
        next_action='review_candidate_in_targeted_chunks'
    elif not delivered:
        next_action='finalize_after_validation'
    else:
        next_action='verify_delivery'
    return {
        'schema_version':1,
        'job':str(job),
        'engine_version':meta.get('engine_version'),
        'source_sha256':meta['source_sha256'],
        'progress':{
            'batches_total':len(meta['batches']),
            'batches_present':len(meta['batches'])-len(missing),
            'batches_missing':len(missing),
            'lines_total':sum(len(b.get('indices',[])) for b in meta['batches']),
        },
        'next_action':next_action,
        'next_batch':next_batch,
        'startup_files':startup_files,
        'artifact_flags':{
            'candidate':candidate,
            'technical_report':technical_report,
            'review':review,
            'delivery':delivered,
        },
        'resume_rule':'Use local job files as continuity. Do not load prior chat, old subtitle dumps, full logs, or prior render images unless a current targeted issue requires them.',
        'note':'File presence is not validation; build/finalize recheck content and hashes.',
    }


def create_receipt(job,stage):
    """Write a fixed-schema machine receipt for the coordinator; never include payload text."""
    job=Path(job).resolve();ensure_mutable_job(job)
    if stage not in ('context','translation','review','delivery'):
        raise ValueError('Unknown receipt stage')
    meta,source,profile=load_job(job)
    bindings=meta.get('translation_bindings') or {
        'source_sha256':meta['source_sha256'],
        'episode_context_sha256':file_hash(job/'context.json'),
        'profile_sha256':file_hash(job/'profile.json'),
        'series_context_sha256':None,
    }
    result={'schema_version':1,'stage':stage,'status':'invalid','series_id':meta.get('series_id'),
            'series_revision':meta.get('series_revision'),'episode_id':meta.get('episode_id'),
            'bindings':bindings,'counts':{'batches_total':len(meta['batches']),'batches_valid':0,
            'batches_missing':0,'lines_total':sum(len(b.get('indices',[])) for b in meta['batches']),
            'technical_issues':0},'artifact_sha256':None,'next_action':'inspect_worker_artifacts','error_code':None}
    try:
        validate_context(read_json(job/'context.json'))
        if stage=='context':
            result.update(status='complete',artifact_sha256=bindings['episode_context_sha256'],next_action='dispatch_translation_worker')
        elif stage=='translation':
            names=set();valid=0;missing=0;lines=[]
            try:
                for b in meta['batches']:
                    if not (job/'translations'/b['file']).is_file(): missing+=1;continue
                    lines.extend(read_translation_batch(job,meta,b,names));valid+=1
            except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError):
                result['error_code']='INVALID_BATCH'
                raise
            result['counts']['batches_valid']=valid;result['counts']['batches_missing']=missing
            if missing:
                result.update(status='incomplete',next_action='dispatch_translation_worker',error_code='MISSING_BATCHES')
            else:
                result.update(status='complete',artifact_sha256=object_hash({'source_sha256':meta['source_sha256'],
                              'lines':sorted(lines,key=lambda x:x['index'])}),next_action='build_candidate')
        elif stage=='review':
            subs,report,loaded_meta,loaded_source=evaluate(job)
            candidate=job/'candidate.ass'
            import hashlib
            expected=hashlib.sha256(subs.to_string('ass').encode()).hexdigest()
            if not candidate.is_file() or file_hash(candidate)!=expected: raise ValueError('Candidate is missing or stale')
            report['candidate_sha256']=expected
            if read_json(job/'technical_report.json')!=report: raise ValueError('Technical report is stale')
            learning=validate_learning_report(job,read_json(job/'context.json'),loaded_source)
            review_path=job/'review.json';review=read_json(review_path);validate_review(review,report,learning)
            result['counts'].update(batches_valid=len(meta['batches']),technical_issues=sum(len(r['issues']) for r in report['lines']))
            result.update(status='complete',artifact_sha256=file_hash(review_path),next_action='finalize')
        else:
            delivery=read_json(job/'delivery.json')
            output=Path(delivery.get('output',''))
            if not output.is_file() or file_hash(output)!=delivery.get('output_sha256'):
                raise ValueError('Delivery output is missing or stale')
            archive=Path(delivery.get('archive',''))
            verify_existing_bundle(archive,read_json(archive/'archive-manifest.json'))
            result['counts']['batches_valid']=len(meta['batches'])
            result.update(status='complete',artifact_sha256=delivery['output_sha256'],next_action='advance_series_context')
    except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError):
        result['error_code']=result['error_code'] or 'VALIDATION_FAILED'
    encoded=json.dumps(result,ensure_ascii=False,separators=(',',':'))
    if len(encoded)>2000: raise ValueError('Coordinator receipt exceeded its fixed budget')
    path=job/'receipts'/f'{stage}.json';write_json(path,result,overwrite=True)
    return {'receipt_path':str(path),'receipt_sha256':file_hash(path),'stage':stage,'status':result['status']}


def resume_from_archive(archive,new_job):
    archive,new_job=Path(archive).resolve(),Path(new_job).resolve()
    if new_job.exists(): raise ValueError('New job destination already exists')
    ensure_plain_tree(archive)
    manifest=verify_existing_bundle(archive,read_json(archive/'archive-manifest.json'))
    keep={'job.json','context.json','profile.json','series_context.json','series_update.json','learning_report.json','timing_windows.json'}
    selected=[i['name'] for i in manifest['files'] if i['name'] in keep or i['name'].startswith('source.') or i['name'].startswith('requests/') or i['name'].startswith('translations/') or i['name'].startswith('content_filter/') or i['name'].startswith('viewing_breaks/')]
    new_job.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=new_job.parent) as staging:
        tmp=Path(staging)/'job'; tmp.mkdir()
        for name in selected:
            target=tmp/name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(archive/name,target)
        meta=read_json(tmp/'job.json'); meta['resumed_from_archive']=str(archive); meta['engine_version']=VERSION
        write_json(tmp/'job.json',meta)
        publish_directory(tmp,new_job)
    return {'status':'resumed','job':str(new_job),'source_archive':str(archive),'copied_files':len(selected)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    cmd=p.add_subparsers(dest='command',required=True)
    q=cmd.add_parser('prepare'); q.add_argument('--input',required=True); q.add_argument('--job',required=True); q.add_argument('--profile'); q.add_argument('--context'); q.add_argument('--series-context'); q.add_argument('--episode-id')
    for name in ('build','status','handoff','finalize'):
        q=cmd.add_parser(name); q.add_argument('--job',required=True)
        if name=='finalize': q.add_argument('--output',required=True); q.add_argument('--review'); q.add_argument('--archive-root')
    q=cmd.add_parser('receipt');q.add_argument('--job',required=True);q.add_argument('--stage',required=True,choices=('context','translation','review','delivery'))
    q=cmd.add_parser('resume-from-archive'); q.add_argument('--archive',required=True); q.add_argument('--job',required=True)
    a=p.parse_args()
    try:
        if a.command=='prepare': result=prepare(a.input,a.job,a.profile,a.context,a.series_context,a.episode_id)
        elif a.command=='build': result=build(a.job)
        elif a.command=='status': result=status(a.job)
        elif a.command=='handoff': result=handoff(a.job)
        elif a.command=='receipt': result=create_receipt(a.job,a.stage)
        elif a.command=='finalize': result=finalize(a.job,a.output,a.review,a.archive_root)
        else: result=resume_from_archive(a.archive,a.job)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,OSError,KeyError,TypeError) as e:
        print(json.dumps({'status':'blocked','reason':str(e)},ensure_ascii=False),file=sys.stderr); sys.exit(2)


if __name__=='__main__': main()
