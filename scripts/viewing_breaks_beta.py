#!/usr/bin/env python3
"""Beta: propose reviewable viewing breaks and add reviewed breaks as MKV chapters.

Mechanical signals only rank candidates. Story suitability belongs to an active
agent or human who has inspected the nearby picture, audio and dialogue.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import pysubs2

from content_filter_pipeline import keyframes, media_signature, probe, stream_payload_hashes
from subtitle_core import file_hash, read_json, visible, write_json, ensure_plain_tree


BETA_VERSION = 'viewing-breaks-beta.1'


def _finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + ' must be a finite number')
    return float(value)


def subtitle_gaps(subtitle_path, minimum_seconds=1.2):
    if not subtitle_path:
        return []
    subs = pysubs2.load(subtitle_path)
    events = sorted((e for e in subs if not e.is_comment and visible(e.text).strip()), key=lambda e: (e.start, e.end))
    gaps = []
    covered_end = 0
    for event in events:
        if event.start > covered_end:
            duration = (event.start - covered_end) / 1000
            if duration >= minimum_seconds:
                gaps.append({'start': covered_end / 1000, 'end': event.start / 1000, 'duration': duration})
        covered_end = max(covered_end, event.end)
    return gaps


def audio_silences(video_path, minimum_seconds=0.8, noise='-35dB'):
    info = probe(video_path)
    if not any(s.get('codec_type') == 'audio' for s in info.get('streams', [])):
        return []
    result = subprocess.run(
        ['ffmpeg', '-nostdin', '-hide_banner', '-v', 'info', '-i', str(video_path), '-map', '0:a:0',
         '-af', f'silencedetect=noise={noise}:d={minimum_seconds}', '-vn', '-f', 'null', '-'],
        capture_output=True, text=True,
    )
    if result.returncode:
        raise ValueError('Audio silence scan failed')
    starts = []
    rows = []
    for line in result.stderr.splitlines():
        start = re.search(r'silence_start:\s*([0-9.]+)', line)
        end = re.search(r'silence_end:\s*([0-9.]+)', line)
        if start:
            starts.append(float(start.group(1)))
        if end and starts:
            a, b = starts.pop(0), float(end.group(1))
            if b > a:
                rows.append({'start': a, 'end': b, 'duration': b - a})
    return rows


def suggested_part_count(duration_seconds, requested=None):
    if requested is not None:
        if type(requested) is not int or requested < 2 or requested > 12:
            raise ValueError('Requested viewing part count must be an integer from 2 to 12')
        return requested
    if duration_seconds <= 30 * 60:
        return 2
    return max(2, min(12, math.ceil(duration_seconds / (45 * 60))))


def _nearby_interval(time_value, intervals, margin=0.75):
    matches = [row for row in intervals if row['start'] - margin <= time_value <= row['end'] + margin]
    return max(matches, key=lambda row: row['duration']) if matches else None


def analyze_breaks(video_path, subtitle_path=None, parts=None, top_candidates=5):
    video = Path(video_path)
    if not video.is_file():
        raise ValueError('Video source is missing')
    duration = float(probe(video)['format']['duration'])
    if duration < 120:
        raise ValueError('Viewing-break analysis is intended for media at least two minutes long')
    part_count = suggested_part_count(duration, parts)
    frames = keyframes(video)
    gaps = subtitle_gaps(subtitle_path)
    silences = audio_silences(video)
    edge_guard = min(300.0, duration / 5)
    usable = [t for t in frames if edge_guard <= t <= duration - edge_guard]
    if not usable:
        raise ValueError('No usable internal keyframe for viewing breaks')
    groups = []
    segment = duration / part_count
    search_window = min(300.0, max(45.0, segment * 0.18))
    for number in range(1, part_count):
        ideal = segment * number
        candidates = [t for t in usable if abs(t - ideal) <= search_window]
        if not candidates:
            candidates = sorted(usable, key=lambda t: abs(t - ideal))[:top_candidates]
        ranked = []
        for time_value in candidates:
            gap = _nearby_interval(time_value, gaps)
            silence = _nearby_interval(time_value, silences)
            proximity = max(0.0, 45.0 * (1 - abs(time_value - ideal) / max(search_window, 0.001)))
            score = proximity + (25.0 + min(10.0, gap['duration'] * 2) if gap else 0)
            score += 20.0 + min(10.0, silence['duration'] * 2) if silence else 0
            ranked.append({
                'applied_time': round(time_value, 3),
                'distance_from_ideal_seconds': round(time_value - ideal, 3),
                'score': round(min(100.0, score), 2),
                'signals': {
                    'keyframe': True,
                    'subtitle_gap': gap,
                    'audio_silence': silence,
                },
                'story_review_required': True,
            })
        ranked.sort(key=lambda row: (-row['score'], abs(row['distance_from_ideal_seconds']), row['applied_time']))
        groups.append({'break_number': number, 'ideal_time': round(ideal, 3), 'candidates': ranked[:top_candidates]})
    analysis_params={'parts':parts,'top_candidates':top_candidates}
    return {
        'status': 'beta_candidates_needing_story_review',
        'beta_feature': 'viewing_breaks',
        'beta_version': BETA_VERSION,
        'astra_reviewed': False,
        'source': str(video.resolve()),
        'source_sha256': file_hash(video),
        'subtitle_sha256': file_hash(subtitle_path) if subtitle_path else None,
        'analysis_params': analysis_params,
        'duration': duration,
        'suggested_parts': part_count,
        'subtitle': str(Path(subtitle_path).resolve()) if subtitle_path else None,
        'method': 'keyframes ranked by distance, subtitle gaps and audio silence',
        'limitations': 'Mechanical ranking does not establish a story-safe stopping point; inspect nearby picture, audio and dialogue.',
        'break_groups': groups,
        'review_template': {
            'beta_feature': 'viewing_breaks',
            'beta_version': BETA_VERSION,
            'source_sha256': file_hash(video),
            'review_status': 'needs_story_review',
            'reviewed_by': '',
            'review_summary': '',
            'breaks': [],
        },
    }


def validate_reviewed_plan(video_path, plan):
    video = Path(video_path)
    if not isinstance(plan, dict) or plan.get('beta_feature') != 'viewing_breaks':
        raise ValueError('Invalid viewing-break plan')
    if plan.get('beta_version') != BETA_VERSION or plan.get('source_sha256') != file_hash(video):
        raise ValueError('Viewing-break plan is stale or belongs to another source')
    if plan.get('review_status') != 'reviewed':
        raise ValueError('Viewing-break plan still needs story review')
    if not isinstance(plan.get('reviewed_by'), str) or len(plan['reviewed_by'].strip()) < 3:
        raise ValueError('Reviewed plan needs a reviewer')
    if not isinstance(plan.get('review_summary'), str) or len(plan['review_summary'].strip()) < 20:
        raise ValueError('Reviewed plan needs a concrete story-review summary')
    duration = float(probe(video)['format']['duration'])
    minimum_segment = min(300.0, duration / 5)
    available = keyframes(video)
    rows = plan.get('breaks')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Reviewed plan needs at least one selected break')
    result = []
    for number, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError('Every viewing break must be an object')
        requested = _finite_number(row.get('requested_time'), 'requested_time')
        applied = _finite_number(row.get('applied_time'), 'applied_time')
        if row.get('story_safe') is not True:
            raise ValueError('Every break needs story_safe=true after actual review')
        if not isinstance(row.get('evidence'), str) or len(row['evidence'].strip()) < 20:
            raise ValueError('Every break needs concrete picture/audio/story evidence')
        if not any(abs(applied - frame) <= 0.05 for frame in available):
            raise ValueError('Applied viewing break must match a verified video keyframe')
        title = row.get('next_title') or f'İzleme Bölümü {number + 1}'
        if not isinstance(title, str) or not title.strip() or any(c in title for c in '\r\n'):
            raise ValueError('Viewing chapter title must be plain text')
        result.append({'requested_time': requested, 'applied_time': applied,
                       'evidence': row['evidence'].strip(), 'story_safe': True,
                       'next_title': title.strip()})
    applied = [row['applied_time'] for row in result]
    if applied != sorted(set(applied)):
        raise ValueError('Viewing breaks must be unique and chronological')
    boundaries = [0.0, *applied, duration]
    if any(b - a < minimum_segment for a, b in zip(boundaries, boundaries[1:])):
        raise ValueError('Viewing breaks create an impractically short segment')
    return result, duration


def _metadata_escape(value):
    return str(value).replace('\\', '\\\\').replace('=', '\\=').replace(';', '\\;').replace('#', '\\#').replace('\n', ' ')


def chapter_metadata(breaks, duration):
    boundaries = [0.0, *[row['applied_time'] for row in breaks], duration]
    titles = ['İzleme Bölümü 1', *[row['next_title'] for row in breaks]]
    lines = [';FFMETADATA1']
    chapters = []
    for number, (start, end, title) in enumerate(zip(boundaries, boundaries[1:], titles), 1):
        start_ms, end_ms = round(start * 1000), round(end * 1000)
        lines += ['[CHAPTER]', 'TIMEBASE=1/1000', f'START={start_ms}', f'END={end_ms}', f'title={_metadata_escape(title)}']
        chapters.append({'number': number, 'start': start, 'end': end, 'title': title})
    return '\n'.join(lines) + '\n', chapters


def apply_chapters(video_path, plan_path, output_path, job_path=None, replace_existing_chapters=False):
    video, output = Path(video_path), Path(output_path)
    plan = read_json(plan_path)
    breaks, duration = validate_reviewed_plan(video, plan)
    sidecar = output.with_suffix(output.suffix + '.viewing-breaks.json')
    if output.suffix.lower() != '.mkv' or output.resolve() == video.resolve():
        raise ValueError('Beta chapter output must be a new MKV')
    if output.exists() or output.is_symlink() or sidecar.exists() or sidecar.is_symlink():
        raise ValueError('Choose unused viewing-break output paths')
    original = probe(video)
    original_chapters = original.get('chapters', [])
    if original_chapters and not replace_existing_chapters:
        raise ValueError('Source already has chapters; pass --replace-existing-chapters for a new untouched copy')
    if job_path:
        from run_pipeline import load_job, validate_context
        job = Path(job_path)
        ensure_plain_tree(job)
        if (job / 'archive-manifest.json').exists():
            raise ValueError('Archived job is read-only')
        load_job(job)
        validate_context(read_json(job / 'context.json'))
    output.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        with tempfile.TemporaryDirectory(dir=output.parent) as temp_dir:
            temp = Path(temp_dir)
            metadata, chapters = chapter_metadata(breaks, duration)
            meta_path = temp / 'chapters.ffmeta'
            meta_path.write_text(metadata)
            candidate = temp / 'chaptered.mkv'
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(video), '-f', 'ffmetadata', '-i', str(meta_path),
                            '-map', '0', '-map_metadata', '0', '-map_chapters', '1', '-c', 'copy', str(candidate)],
                           capture_output=True, text=True, check=True)
            produced = probe(candidate)
            if Counter(media_signature(original)) != Counter(media_signature(produced)):
                raise ValueError('Stream or attachment inventory changed while adding viewing chapters')
            payload_before = {'video': stream_payload_hashes(video, 'v'), 'audio': stream_payload_hashes(video, 'a')}
            payload_after = {'video': stream_payload_hashes(candidate, 'v'), 'audio': stream_payload_hashes(candidate, 'a')}
            if payload_before != payload_after:
                raise ValueError('Audio/video payload changed while adding viewing chapters')
            got_chapters = produced.get('chapters', [])
            if len(got_chapters) != len(chapters):
                raise ValueError('Viewing chapter count verification failed')
            for expected, actual in zip(chapters, got_chapters):
                if abs(float(actual['start_time']) - expected['start']) > 0.02 or abs(float(actual['end_time']) - expected['end']) > 0.02:
                    raise ValueError('Viewing chapter timestamp verification failed')
            report = {
                'status': 'beta_chapters_need_playback_review',
                'beta_feature': 'viewing_breaks', 'beta_version': BETA_VERSION, 'astra_reviewed': False,
                'source': str(video.resolve()), 'source_sha256': file_hash(video),
                'output': str(output.resolve()), 'output_sha256': file_hash(candidate),
                'reviewed_plan': plan, 'chapters': chapters,
                'original_chapter_count': len(original_chapters),
                'existing_chapters_replaced_in_new_copy': bool(original_chapters),
                'streams_and_attachments_preserved': True,
                'audio_video_payloads_preserved': True,
                'payload_sha256_before': payload_before, 'payload_sha256_after': payload_after,
                'video_processing': 'stream_copy', 'source_modified': False,
                'playback_review': 'required',
            }
            os.link(candidate, output); created.append(output)
            write_json(sidecar, report, overwrite=False); created.append(sidecar)
            if job_path:
                folder = Path(job_path) / 'viewing_breaks'; folder.mkdir(exist_ok=True)
                record = folder / f'chapters-{report["output_sha256"][:12]}.json'
                write_json(record, report, overwrite=False); created.append(record)
            return report
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_subparsers(dest='command', required=True)
    analyze = command.add_parser('analyze')
    analyze.add_argument('--video', required=True); analyze.add_argument('--subtitle')
    analyze.add_argument('--parts', type=int); analyze.add_argument('--top-candidates', type=int, default=5)
    analyze.add_argument('--output', required=True)
    apply = command.add_parser('apply')
    apply.add_argument('--video', required=True); apply.add_argument('--plan', required=True); apply.add_argument('--output', required=True)
    apply.add_argument('--job'); apply.add_argument('--replace-existing-chapters', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'analyze':
            if args.top_candidates < 1 or args.top_candidates > 10:
                raise ValueError('top-candidates must be from 1 to 10')
            result = analyze_breaks(args.video, args.subtitle, args.parts, args.top_candidates)
            write_json(args.output, result, overwrite=False)
        else:
            result = apply_chapters(args.video, args.plan, args.output, args.job, args.replace_existing_chapters)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
