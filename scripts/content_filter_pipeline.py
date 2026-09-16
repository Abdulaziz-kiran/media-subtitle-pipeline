#!/usr/bin/env python3
"""Explicit cut plans, interval algebra and validated stream-copy MKV output.
This module does not detect sensitive scenes. Cut intervals must come from review.
"""
from __future__ import annotations
import argparse
import copy
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import pysubs2
from subtitle_core import ROOT, file_hash, read_json, save_ass, write_json, visible, ensure_plain_tree, publish_directory
from archive_delivery import safe_name,verify_existing_bundle


def probe(path):
    r=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-show_chapters','-of','json',str(path)],capture_output=True,text=True,check=True)
    return json.loads(r.stdout)


def get_video_duration(path): return float(probe(path)['format']['duration'])




def default_filter_categories():
    profile=read_json(ROOT/'resources/content_filter_profile.json')
    if not isinstance(profile,dict) or profile.get('schema_version')!=1 or not isinstance(profile.get('categories'),list):
        raise ValueError('Invalid default content filter profile')
    categories=set()
    for row in profile['categories']:
        if not isinstance(row,dict) or set(row)!={'id','action','definition'} or row.get('action')!='cut':
            raise ValueError('Invalid default content filter category')
        category=str(row.get('id','')).strip()
        if len(category)<3 or len(str(row.get('definition','')).strip())<20:
            raise ValueError('Invalid default content filter category')
        categories.add(category)
    if not categories:
        raise ValueError('Default content filter profile has no cut categories')
    return categories

def normalize_cuts(cuts, duration=None):
    rows=[]
    for c in cuts:
        if len(c) not in (2,3): raise ValueError('Cut must be [start,end,optional note]')
        start,end=c[0],c[1]
        if isinstance(start,bool) or isinstance(end,bool) or not isinstance(start,(int,float)) or not isinstance(end,(int,float)) or not math.isfinite(start) or not math.isfinite(end):
            raise ValueError('Finite numeric cut boundaries required')
        if start<0 or end<=start or (duration is not None and end>duration): raise ValueError('Invalid cut range')
        note=c[2] if len(c)==3 else None
        if note is not None and not isinstance(note,str): raise ValueError('Context note must be text')
        rows.append([start,end,[note.strip()] if note and note.strip() else []])
    merged=[]
    for start,end,notes in sorted(rows,key=lambda x:(x[0],x[1])):
        if merged and start<=merged[-1][1]:
            merged[-1][1]=max(end,merged[-1][1])
            merged[-1][2].extend(n for n in notes if n not in merged[-1][2])
        else: merged.append([start,end,notes])
    return [(s,e,' '.join(notes) or None) for s,e,notes in merged]


def reviewed_cut_requests(cut_spec,duration,require_policy=False):
    policy=None
    cuts=cut_spec
    if isinstance(cut_spec,dict):
        cuts=cut_spec.get('cuts')
        raw=cut_spec.get('policy')
        if not isinstance(raw,dict): raise ValueError('Cut plan envelope needs a policy object')
        if raw.get('authorized') is not True:
            raise ValueError('Cut policy must record authorized=true')
        if len(str(raw.get('requested_by','')).strip())<3 or len(str(raw.get('instruction','')).strip())<20 or len(str(raw.get('source_reference','')).strip())<10:
            raise ValueError('Cut policy needs requested_by, concrete instruction and source_reference')
        policy={'authorized':True,'requested_by':raw['requested_by'].strip(),'instruction':raw['instruction'].strip(),
                'source_reference':raw['source_reference'].strip()}
    elif require_policy:
        raise ValueError('Production cuts need an authorized policy envelope')
    if not isinstance(cuts,list) or not cuts: raise ValueError('Cuts must be a non-empty list')
    rows=[]; evidence=[]
    for n,c in enumerate(cuts):
        if not isinstance(c,dict):
            raise ValueError('Production cuts must be objects with evidence and reviewed_by')
        if len(str(c.get('evidence','')).strip())<20 or len(str(c.get('reviewed_by','')).strip())<3:
            raise ValueError('Every cut needs concrete review evidence and reviewed_by')
        category=str(c.get('category','')).strip(); reason=str(c.get('cut_reason','')).strip()
        if require_policy and (len(category)<3 or len(reason)<10):
            raise ValueError('Every production cut needs category and cut_reason')
        if policy and 'content_filter_profile.json' in policy['source_reference'] and category not in default_filter_categories():
            raise ValueError('Default content filter policy cannot cut category outside the configured profile')
        note=c.get('context_note')
        if note is not None and (not isinstance(note,str) or (note.strip() and len(note.strip())<10)):
            raise ValueError('Context note must be empty or concrete text')
        rows.append([c.get('start'),c.get('end'),note])
        evidence.append({'request_index':n,'start':c.get('start'),'end':c.get('end'),
                         'evidence':c['evidence'].strip(),'reviewed_by':c['reviewed_by'].strip(),
                         'category':category or None,'cut_reason':reason or None,
                         'context_note':note.strip() if isinstance(note,str) and note.strip() else None})
    return normalize_cuts(rows,duration),evidence,policy


def kept_segments(cuts,duration):
    kept=[]; t=0
    for s,e,*_ in cuts:
        if t<s: kept.append((t,s))
        t=e
    if t<duration: kept.append((t,duration))
    return kept


def splice_subtitles(subs, cut_intervals_ms, context_notes=None, note_duration_ms=8000, duration_ms=None):
    if context_notes is not None and len(context_notes)!=len(cut_intervals_ms): raise ValueError('Notes must correspond to cuts')
    with_notes=[(c[0],c[1],context_notes[i] if context_notes else None) for i,c in enumerate(cut_intervals_ms)]
    cuts=normalize_cuts(with_notes,duration_ms)
    duration=duration_ms if duration_ms is not None else max([e.end for e in subs]+[c[1] for c in cuts]+[1])
    kept=kept_segments(cuts,duration)
    new=copy.deepcopy(subs); new.events=[]
    # Intersect every source event with each retained segment. Both sides survive.
    offset=0
    for start,end in kept:
        for ev in subs:
            a,b=max(ev.start,start),min(ev.end,end)
            if b>a:
                e=ev.copy(); e.start=round(offset+a-start); e.end=round(offset+b-start)
                if e.end>e.start: new.events.append(e)
        offset+=end-start
    if context_notes:
        style=copy.deepcopy(new.styles.get('Default',pysubs2.SSAStyle()))
        style.alignment=pysubs2.Alignment.TOP_CENTER; style.fontsize=24
        new.styles['CutContext']=style
        shift=0
        for start,end,note in cuts:
            when=start-shift
            if note and when<offset:
                # Do not interpret note prose as ASS tags or escape commands.
                if any(c in note for c in '{}\\'): raise ValueError('Context notes must be plain text')
                text='[HİKAYE BAĞLAMI] '+note
                new.events.append(pysubs2.SSAEvent(start=round(when),end=round(min(offset,when+note_duration_ms)),text=text,style='CutContext'))
            shift+=end-start
    new.events.sort(key=lambda e:(e.start,e.end,e.layer))
    return new


def keyframes(path):
    r=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-skip_frame','nokey','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(path)],capture_output=True,text=True,check=True)
    frames=sorted({float(f['best_effort_timestamp_time']) for f in json.loads(r.stdout).get('frames',[]) if 'best_effort_timestamp_time' in f})
    if not frames: raise ValueError('No verified keyframes; cannot guarantee stream-copy boundaries')
    return frames


def plan_cuts(video_path,cut_intervals,require_policy=False):
    info=probe(video_path); duration=float(info['format']['duration'])
    if abs(float(info['format'].get('start_time',0)))>0.05:
        raise ValueError('Nonzero source start timestamp; normalize a working copy before cut planning')
    requested,reviews,policy=reviewed_cut_requests(cut_intervals,duration,require_policy)
    if not requested: raise ValueError('No cuts specified')
    frames=keyframes(video_path); aligned=[]
    for start,end,note in requested:
        before=[t for t in frames if t<=start+0.001]
        after=[t for t in frames if t>=end-0.001]
        a=max(before) if before else 0.0
        b=min(after) if after else duration
        aligned.append((a,b,note))
    applied=normalize_cuts(aligned,duration)
    kept=kept_segments(applied,duration)
    if not kept: raise ValueError('Cut would remove the entire video')
    return {'source':str(Path(video_path).resolve()),'source_sha256':file_hash(video_path),'duration':duration,'policy':policy,'requested':requested,'cut_reviews':reviews,'applied':applied,'kept':kept,
            'extra_removed_seconds':round(sum(e-s for s,e,_ in applied)-sum(e-s for s,e,_ in requested),6),
            'stream_types':[s['codec_type'] for s in info['streams']], 'chapters_removed':bool(info.get('chapters'))}


def media_signature(info):
    return [(s.get('codec_type'),s.get('codec_name'),s.get('tags',{}).get('language'),s.get('tags',{}).get('filename')) for s in info['streams']]


def packet_span(path,selector='v:0'):
    r=subprocess.run(['ffprobe','-v','error','-select_streams',selector,'-show_packets','-show_entries','packet=pts_time,duration_time','-of','json',str(path)],capture_output=True,text=True,check=True)
    rows=[]
    for p in json.loads(r.stdout).get('packets',[]):
        if 'pts_time' in p:
            start=float(p['pts_time']); rows.append((start,start+float(p.get('duration_time') or 0)))
    if not rows: raise ValueError('No timestamped packets for duration verification')
    return max(e for _,e in rows)-min(s for s,_ in rows)


def stream_payload_hashes(path,kind):
    if kind not in ('v','a'): raise ValueError('Only video and audio payload hashes are supported')
    r=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(path),'-map',f'0:{kind}?','-c','copy',
                      '-f','streamhash','-hash','sha256','-'],capture_output=True,text=True)
    if r.returncode: raise ValueError(f'Cannot hash {kind} stream payloads')
    return [line.strip().split('=',1)[-1] for line in r.stdout.splitlines() if line.strip()]


def decode_window(path,at):
    r=subprocess.run(['ffmpeg','-nostdin','-v','error','-ss',str(max(0,at-0.5)),'-i',str(path),'-t','1.5',
                      '-map','0:v?','-map','0:a?','-f','null','-'],capture_output=True,text=True)
    if r.returncode: raise ValueError('Decode failed at join: '+str(at))
    return r.stderr.strip()


def reencode_video_losslessly(video_path,kept,audio_base,output,original_info):
    videos=[s for s in original_info['streams'] if s.get('codec_type')=='video']
    if len(videos)!=1 or videos[0].get('codec_name') not in ('h264','hevc'):
        raise ValueError('Safe open-GOP fallback supports one H.264 or H.265 video stream')
    filters=[]; labels=[]
    for n,(start,end) in enumerate(kept):
        label=f'v{n}';filters.append(f'[0:v:0]trim=start={start}:end={end},setpts=PTS-STARTPTS[{label}]');labels.append(f'[{label}]')
    if len(labels)==1: filters.append(labels[0]+'null[vout]')
    else: filters.append(''.join(labels)+f'concat=n={len(labels)}:v=1:a=0[vout]')
    encoded=output.with_name('lossless-video.mkv')
    codec=videos[0]['codec_name']
    cmd=['ffmpeg','-nostdin','-v','error','-i',str(video_path),'-filter_complex',';'.join(filters),'-map','[vout]','-an','-sn','-dn']
    if codec=='h264': cmd+=['-c:v','libx264','-preset','medium','-crf','0']
    else: cmd+=['-c:v','libx265','-preset','medium','-x265-params','lossless=1:log-level=error']
    cmd.append(str(encoded));subprocess.run(cmd,capture_output=True,text=True,check=True)
    cmd=['ffmpeg','-nostdin','-v','error','-i',str(encoded),'-i',str(audio_base),'-map','0:v:0','-map','1:a?','-map','1:t?','-map','1:d?',
         '-map_metadata','1','-map_chapters','-1','-c','copy',str(output)]
    subprocess.run(cmd,capture_output=True,text=True,check=True)
    before_audio=stream_payload_hashes(audio_base,'a');after_audio=stream_payload_hashes(output,'a')
    if before_audio!=after_audio: raise ValueError('Audio payload changed during video-only fallback')
    return {'audio_payload_sha256_before':before_audio,'audio_payload_sha256_after':after_audio,
            'codec':codec,'encoder':'libx264-crf0' if codec=='h264' else 'libx265-lossless',
            'reason':'stream-copy segment or aggregate display span exceeded strict tolerance'}


def render_cut_plan(video_path,plan,output_video_path,tolerance_sec=0.1):
    raise ValueError('Direct cut rendering is disabled; use sanitize_movie for policy, source binding and evidence archiving')


def _render_cut_plan(video_path,plan,output_video_path,tolerance_sec=0.1):
    if plan.get('source_sha256')!=file_hash(video_path) or plan.get('source')!=str(Path(video_path).resolve()):
        raise ValueError('Cut plan source binding is missing or stale')
    if not isinstance(plan.get('policy'),dict) or plan['policy'].get('authorized') is not True:
        raise ValueError('Cut rendering needs an authorized policy')
    output=Path(output_video_path)
    if output.suffix.lower()!='.mkv': raise ValueError('Validated stream-copy output must be MKV')
    if output.exists() or output.resolve()==Path(video_path).resolve(): raise ValueError('Output exists or equals source')
    original=probe(video_path)
    original_subs=[s for s in original['streams'] if s['codec_type']=='subtitle']
    if any(s['codec_name'] not in ('ass','ssa','subrip','srt','mov_text','webvtt','text') for s in original_subs):
        raise ValueError('Image-based embedded subtitles cannot be retimed by this text engine; provide a text replacement or explicit removal plan')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        tmp=Path(tmp); parts=[]
        retimed=[]
        for n,stream in enumerate(original_subs):
            raw=tmp/f'source-sub-{n}.ass'; updated=tmp/f'cut-sub-{n}.ass'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(video_path),'-map',f"0:{stream['index']}",'-c:s','ass',str(raw)],capture_output=True,text=True,check=True)
            original_events=pysubs2.load(raw)
            if any(__import__('re').search(r'\\(?:t\(|k|K|fad|fade|move)',e.text) and any(e.start<b*1000 and e.end>a*1000 for a,b,_ in plan['applied']) for e in original_events):
                raise ValueError('A cut intersects time-dependent effects in an embedded subtitle track')
            adjusted=splice_subtitles(original_events,[(round(a*1000),round(b*1000)) for a,b,_ in plan['applied']],duration_ms=round(plan['duration']*1000))
            save_ass(adjusted,updated,raw)
            retimed.append(updated)
        # Split once at every verified keyframe. Repeated input seeking can retain
        # decoder-delay packets around H.264/H.265 B-frame boundaries.
        boundaries=sorted({x for a,b,_ in plan['applied'] for x in (a,b) if x>0.001 and x<plan['duration']-0.001})
        pattern=tmp/'source-part-%04d.mkv'
        cmd=['ffmpeg','-nostdin','-v','error','-i',str(video_path),'-map','0','-map','-0:s?','-map','-0:t?','-map_metadata','0','-map_chapters','-1','-c','copy']
        if boundaries: cmd+=['-f','segment','-segment_times',','.join(map(str,boundaries)),'-reset_timestamps','1']
        cmd.append(str(pattern))
        subprocess.run(cmd,capture_output=True,text=True,check=True)
        generated=sorted(tmp.glob('source-part-*.mkv'))
        points=[0.0]+boundaries+[plan['duration']]
        source_intervals=list(zip(points,points[1:]))
        if len(generated)!=len(source_intervals): raise ValueError('Keyframe segment count mismatch; no output published')
        def retained(interval):
            mid=sum(interval)/2
            return not any(a<=mid<b for a,b,_ in plan['applied'])
        reencode_reasons=[]
        for i,(path,interval) in enumerate(zip(generated,source_intervals)):
            if not retained(interval): continue
            actual=packet_span(path)
            expected_part=interval[1]-interval[0]
            if abs(actual-expected_part)>tolerance_sec:
                reencode_reasons.append({'segment':i,'video_span_drift':round(actual-expected_part,6)})
            parts.append((path,expected_part))
        listing=tmp/'concat.txt'
        listing.write_text(''.join(f"file '{p.name}'\nduration {duration:.9f}\n" for p,duration in parts))
        base=tmp/'base-copy.mkv';candidate=tmp/'candidate.mkv'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','concat','-safe','1','-i',str(listing),'-map','0','-map_metadata','0','-map_chapters','-1','-c','copy',str(base)],capture_output=True,text=True,check=True)
        copy_span=packet_span(base)
        expected_total=sum(end-start for start,end in plan['kept'])
        if abs(copy_span-expected_total)>tolerance_sec:
            reencode_reasons.append({'scope':'concatenated_base','video_span_drift':round(copy_span-expected_total,6)})
        reencode=None
        if reencode_reasons:
            rebased=tmp/'base-lossless-reencoded.mkv'
            reencode=reencode_video_losslessly(video_path,plan['kept'],base,rebased,original)
            reencode['trigger_details']=reencode_reasons;base=rebased
        base_payloads={'video':stream_payload_hashes(base,'v'),'audio':stream_payload_hashes(base,'a')}
        cmd=['ffmpeg','-nostdin','-v','error','-i',str(base)]
        for path in retimed: cmd+=['-i',str(path)]
        # Attachments are timeless: concat demuxing can lose their stream type.
        # Map them once from the immutable original instead of segmenting them.
        cmd+=['-i',str(video_path),'-map','0']
        for n in range(len(retimed)): cmd+=['-map',f'{n+1}:0']
        cmd+=['-map',f'{len(retimed)+1}:t?']
        cmd+=['-map_metadata','0','-map_chapters','-1','-c','copy']
        for n,stream in enumerate(original_subs):
            for key,value in stream.get('tags',{}).items():
                if key.lower() not in ('duration','encoder'): cmd+=[f'-metadata:s:s:{n}',f'{key}={value}']
            flags='+'.join(k for k,v in stream.get('disposition',{}).items() if v)
            cmd+=[f'-disposition:s:{n}',flags or '0']
        cmd.append(str(candidate))
        subprocess.run(cmd,capture_output=True,text=True,check=True)
        info=probe(candidate)
        candidate_payloads={'video':stream_payload_hashes(candidate,'v'),'audio':stream_payload_hashes(candidate,'a')}
        if candidate_payloads!=base_payloads:
            raise ValueError('Audio/video payload changed while remuxing subtitles; no output published')
        from collections import Counter
        expected_signature=[(kind,'ass' if kind=='subtitle' else codec,lang,filename) for kind,codec,lang,filename in media_signature(original)]
        if Counter(media_signature(info))!=Counter(expected_signature): raise ValueError('Stream/attachment preservation check failed')
        expected=sum(b-a for a,b in plan['kept']); actual=packet_span(candidate)
        if abs(actual-expected)>tolerance_sec:
            raise ValueError(f'Accumulated video span drift {actual-expected:.3f}s exceeds tolerance; no output published')
        # Decode around every join: catches corrupt random access and timestamp failures.
        joins=[]; t=0
        for a,b in plan['kept'][:-1]: t+=b-a; joins.append(t)
        decode_warnings=[]
        for t in [0]+joins:
            warning=decode_window(candidate,t)
            if warning: decode_warnings.append({'at':t,'stderr':warning[-2000:]})
        import os
        os.link(candidate,output)
    return {'duration_expected':expected,'duration_actual':actual,'container_duration':float(info['format']['duration']),'duration_metric':'video_packet_span',
            'tolerance_sec':tolerance_sec,'joins_decode_checked':joins,'decode_warnings':decode_warnings,'stream_signature_preserved':True,
            'postprocess_av_payloads_preserved':True,'base_av_payload_sha256':base_payloads,
            'final_av_payload_sha256':candidate_payloads,'audio_processing':'stream_copy',
            'video_bitstream_identical_to_source':False if reencode else 'not_claimed_after_cut',
            'video_processing':'lossless_reencode' if reencode else 'stream_copy','video_reencode':reencode,
            'subtitle_tracks_retimed':len(original_subs),'subtitle_format':'ass','visual_audio_sync':'requires_playback_review','hdr_metadata':'not_independently_verified'}


def lossless_cut_video(video_path,cut_intervals_sec,output_video_path,align_keyframes=True):
    raise ValueError('Direct video-only cutting is disabled; use sanitize_movie with an authorized policy, reviewed evidence and a prepared job')


def persist_cut_evidence(job_path,report,archive_root=None):
    job=Path(job_path)
    ensure_plain_tree(job)
    if not (job/'job.json').is_file() or not (job/'context.json').is_file():
        raise ValueError('A prepared subtitle job is required to preserve cut evidence')
    if (job/'archive-manifest.json').exists(): raise ValueError('Archived job is read-only')
    from run_pipeline import load_job, validate_context
    load_job(job)  # Validate the copied source hash and profile, not just two filenames.
    validate_context(read_json(job/'context.json'))
    job=job.resolve()
    folder=job/'content_filter'; folder.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=folder,prefix='.pending-',suffix='.json',delete=False) as handle:
        temp=Path(handle.name)
    local=None; local_created=False
    try:
        write_json(temp,report,overwrite=True)
        digest=file_hash(temp); local=folder/f'cut-{digest[:12]}.json'
        if local.exists():
            if file_hash(local)!=digest: raise ValueError('Cut evidence collision')
        prefs=read_json(ROOT/'resources/preferences.json')
        root=Path(archive_root or prefs['archive_root']).expanduser()
        context=read_json(job/'context.json'); title=safe_name(context.get('title') or 'Adsız')
        destination=root/title/f'content-filter--{digest[:12]}'
        expected=[{'name':'cut-report.json','sha256':digest}]
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists() or destination.is_symlink():
            manifest=read_json(destination/'archive-manifest.json')
            verify_existing_bundle(destination,manifest,expected)
        else:
            with tempfile.TemporaryDirectory(dir=destination.parent) as temp_dir:
                staging=Path(temp_dir)/destination.name; staging.mkdir(); shutil.copy2(temp,staging/'cut-report.json')
                manifest={'status':'archived_content_filter','immutable':True,'title':title,'bundle':str(destination.resolve()),
                          'media_copied':False,'files':expected}
                write_json(staging/'archive-manifest.json',manifest,overwrite=False)
                publish_directory(staging,destination)
        # Do not leave a job record claiming delivery when central archiving fails.
        if not local.exists():
            try:
                os.link(temp,local); local_created=True
            except FileExistsError:
                if file_hash(local)!=digest: raise ValueError('Cut evidence collision')
        return {'job_record':str(local),'archive_bundle':str(destination),'sha256':digest,'media_copied':False}
    except Exception:
        if local_created and local is not None: local.unlink(missing_ok=True)
        raise
    finally:
        temp.unlink(missing_ok=True)


def sanitize_movie(video_path,subtitle_ass_path,cut_intervals,output_video_path=None,output_ass_path=None,note_duration_ms=8000,job_path=None,archive_root=None):
    video=Path(video_path); subtitle=Path(subtitle_ass_path)
    outvideo=Path(output_video_path or video.with_name(video.stem+'.clean.mkv'))
    outsub=Path(output_ass_path or subtitle.with_name(subtitle.stem+'.clean.ass'))
    report_path=outvideo.with_suffix('.cut-report.json')
    outputs=[outvideo,outsub,report_path]
    if outvideo.suffix.lower()!='.mkv' or outsub.suffix.lower()!='.ass':
        raise ValueError('Cut output must be a new MKV plus ASS')
    if any(p.exists() for p in outputs) or len({p.resolve() for p in outputs})!=3: raise ValueError('Choose separate unused output paths')
    if any(p.resolve() in (video.resolve(),subtitle.resolve()) for p in outputs): raise ValueError('Source files are immutable')
    if job_path is None: raise ValueError('A prepared --job is required so cut times and notes are archived')
    ensure_plain_tree(Path(job_path))
    if (Path(job_path)/'archive-manifest.json').exists(): raise ValueError('Archived job is read-only')
    from run_pipeline import load_job, validate_context
    load_job(job_path)
    validate_context(read_json(Path(job_path)/'context.json'))
    input_hashes=(file_hash(video),file_hash(subtitle))
    plan=plan_cuts(video,cut_intervals,require_policy=True)
    subs=pysubs2.load(subtitle)
    if any(__import__('re').search(r'\\(?:t\(|k|K|fad|fade|move)',e.text) and any(e.start<b*1000 and e.end>a*1000 for a,b,_ in plan['applied']) for e in subs):
        raise ValueError('A cut intersects time-dependent ASS effects; retime those effects explicitly first')
    new=splice_subtitles(subs,[(round(s*1000),round(e*1000)) for s,e,_ in plan['applied']],
                         [note for _,_,note in plan['applied']],note_duration_ms,round(plan['duration']*1000))
    outvideo.parent.mkdir(parents=True,exist_ok=True);outsub.parent.mkdir(parents=True,exist_ok=True)
    created=[]
    try:
        with tempfile.TemporaryDirectory(dir=outvideo.parent) as video_stage, tempfile.TemporaryDirectory(dir=outsub.parent) as sub_stage:
            staged_video=Path(video_stage)/'output.mkv';staged_sub=Path(sub_stage)/'output.ass'
            checks=_render_cut_plan(video,plan,staged_video)
            save_ass(new,staged_sub,subtitle)
            if (file_hash(video),file_hash(subtitle))!=input_hashes:
                raise ValueError('Source media/subtitle changed during cutting; no output published')
            report={'status':'cut_needs_playback_review','plan':plan,'checks':checks,
                    'source_video':str(video.resolve()),'source_video_sha256':input_hashes[0],'source_subtitle':str(subtitle.resolve()),'source_subtitle_sha256':input_hashes[1],
                    'output_video':str(outvideo.resolve()),'output_video_sha256':file_hash(staged_video),'output_subtitle':str(outsub.resolve()),'output_subtitle_sha256':file_hash(staged_sub)}
            preserved=persist_cut_evidence(job_path,report,archive_root)
            os.link(staged_video,outvideo);created.append(outvideo)
            os.link(staged_sub,outsub);created.append(outsub)
            report['evidence_archive']=preserved
            write_json(report_path,report,overwrite=False);created.append(report_path)
    except Exception:
        for path in reversed(created): path.unlink(missing_ok=True)
        raise
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',required=True); p.add_argument('--cuts',required=True,help='JSON list of reviewed cut objects; each needs start, end, evidence and reviewed_by')
    p.add_argument('--subtitle'); p.add_argument('--output-video'); p.add_argument('--output-ass'); p.add_argument('--job'); p.add_argument('--archive-root'); p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    try:
        cuts=read_json(a.cuts)
        if not a.apply: result=plan_cuts(a.video,cuts)
        else:
            if not a.subtitle: raise ValueError('--subtitle required with --apply')
            result=sanitize_movie(a.video,a.subtitle,cuts,a.output_video,a.output_ass,job_path=a.job,archive_root=a.archive_root)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,OSError,subprocess.CalledProcessError) as e:
        print(str(e),file=sys.stderr); sys.exit(2)

if __name__=='__main__': main()
