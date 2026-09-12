#!/usr/bin/env python3
"""Render actual subtitle pixels to PNG samples; image inspection is a separate attestation."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import re
import pysubs2
from subtitle_core import file_hash,load_profile,text_issues,write_json,role


def find_renderer():
    candidates=[os.getenv('SUBTITLE_FFMPEG'),shutil.which('ffmpeg'),
                '/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg','/usr/local/opt/ffmpeg-full/bin/ffmpeg']
    for candidate in dict.fromkeys(c for c in candidates if c):
        if not Path(candidate).is_file(): continue
        r=subprocess.run([candidate,'-hide_banner','-filters'],capture_output=True,text=True)
        if r.returncode==0 and re.search(r'^\s*\S+\s+ass\s+V->V',r.stdout,re.M): return candidate
    raise ValueError('FFmpeg with libass required. On macOS install ffmpeg-full, or set SUBTITLE_FFMPEG to a compatible binary.')


def render_samples(video,ass,output_dir,times=None,fonts_dir=None):
    video,ass,out=Path(video).resolve(),Path(ass).resolve(),Path(output_dir).resolve()
    if out.exists(): raise ValueError('Choose a new render directory')
    subs=pysubs2.load(ass)
    events=[e for e in subs if not e.is_comment and e.text.strip()]
    if not events: raise ValueError('No subtitle events to render')
    if times is None:
        profile=load_profile()
        dense=max(events,key=lambda e:text_issues(e.text,e.end-e.start,profile)[1]['cps'])
        selected=[events[0],events[len(events)//2],events[-1],dense]
        times=sorted({round((e.start+e.end)/2000,3) for e in selected})
    if any(not isinstance(t,(int,float)) or t<0 or not __import__('math').isfinite(t) for t in times): raise ValueError('Invalid sample times')
    renderer=find_renderer()
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as temp:
        tmp=Path(temp); staging=tmp/'renders'; staging.mkdir()
        shutil.copyfile(ass,tmp/'subtitle.ass')
        if fonts_dir:
            shutil.copytree(fonts_dir,tmp/'fonts')
        else: (tmp/'fonts').mkdir()
        samples=[]
        for n,t in enumerate(times,1):
            png=staging/f'frame-{n:03d}.png'
            # Input-side seek avoids decoding from the beginning for every sample;
            # copyts keeps ASS evaluation on the original media timeline.
            cmd=[renderer,'-nostdin','-v','info','-ss',str(t),'-copyts','-i',str(video),'-vf','ass=filename=subtitle.ass:fontsdir=fonts','-frames:v','1','-update','1',str(png)]
            r=subprocess.run(cmd,cwd=tmp,capture_output=True,text=True,check=True)
            if not png.is_file() or png.stat().st_size==0: raise ValueError('No decoded frame at '+str(t))
            font_lines=[line for line in r.stderr.splitlines() if 'fontselect' in line or 'Glyph' in line or 'glyph' in line]
            active=[{'text':e.text,'style':e.style} for e in events if e.start<=t*1000<e.end]
            samples.append({'time':t,'image':png.name,'active_subtitles':active,'font_log':font_lines,'image_sha256':file_hash(png)})
        report={'status':'images_ready_for_visual_review','video':str(video),'renderer':renderer,'subtitle_sha256':file_hash(ass),'samples':samples,
                'seek_mode':'input_fast_seek_with_copyts',
                'checks_needed':['Turkish glyphs','inline formatting','line breaks','overlap/safe area','font fallback','cut joins if relevant'],
                'scope':'FFmpeg/libass snapshots; target player and HDR fidelity require separate viewing.'}
        write_json(staging/'render-report.json',report)
        os.rename(staging,out)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',required=True);p.add_argument('--ass',required=True);p.add_argument('--output',required=True)
    p.add_argument('--times',nargs='+',type=float);p.add_argument('--fonts')
    a=p.parse_args()
    try: print(json.dumps(render_samples(a.video,a.ass,a.output,a.times,a.fonts),ensure_ascii=False,indent=2))
    except (ValueError,OSError,subprocess.CalledProcessError) as e: print(str(e),file=sys.stderr);sys.exit(2)

if __name__=='__main__':main()
