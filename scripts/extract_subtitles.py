#!/usr/bin/env python3
"""Select an unambiguous text subtitle stream and extract an ASS working copy."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from subtitle_core import write_json

TEXT_CODECS={'ass','ssa','subrip','srt','mov_text','webvtt','text'}


def subtitle_streams(filepath):
    r=subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',str(filepath)],capture_output=True,text=True,check=True)
    return [s for s in json.loads(r.stdout).get('streams',[]) if s.get('codec_type')=='subtitle']


def select_stream(streams,language='eng',index=None,prefer_keywords=None):
    if index is not None:
        matching=[s for s in streams if s['index']==index]
        if len(matching)!=1 or matching[0]['codec_name'] not in TEXT_CODECS: raise ValueError('Selected stream missing or image-based; OCR is a separate task')
        return matching[0]
    languages={'eng','en'} if language in ('eng','en') else {language}
    candidates=[]
    for s in streams:
        tags=s.get('tags',{}); title=tags.get('title','').lower()
        if s.get('codec_name') not in TEXT_CODECS or tags.get('language','und').lower() not in languages: continue
        if s.get('disposition',{}).get('forced') or ('sign' in title and 'full' not in title): continue
        score=(20 if 'full' in title else 0)+sum(10 for k in (prefer_keywords or []) if k.lower() in title)
        candidates.append((score,s))
    candidates.sort(key=lambda x:x[0],reverse=True)
    if not candidates: raise ValueError('No full text subtitle in requested language; inspect streams and select explicitly')
    if len(candidates)>1 and candidates[0][0]==candidates[1][0]:
        raise ValueError('Ambiguous subtitle streams '+str([s['index'] for _,s in candidates])+': use --stream')
    return candidates[0][1]


def find_best_sub_stream(filepath,prefer_keywords=None):
    s=select_stream(subtitle_streams(filepath),prefer_keywords=prefer_keywords)
    return {'index':s['index'],'codec':s['codec_name'],'language':s.get('tags',{}).get('language'),'title':s.get('tags',{}).get('title','')}


def extract_subtitle(filepath,stream_index,output_path):
    output=Path(output_path)
    if output.suffix.lower()!='.ass' or output.exists(): raise ValueError('Choose an unused .ass output')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        candidate=Path(tmp)/'candidate.ass'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(filepath),'-map',f'0:{stream_index}','-c:s','ass',str(candidate)],capture_output=True,text=True,check=True)
        import pysubs2
        if not pysubs2.load(candidate): raise ValueError('Extracted subtitle is empty')
        os.link(candidate,output)
    return True


def inspect_stream_content(filepath,streams):
    """Produce grounded samples for an agent/user when metadata cannot decide."""
    import pysubs2
    report=[]
    with tempfile.TemporaryDirectory() as tmp:
        for stream in streams:
            if stream.get('codec_name') not in TEXT_CODECS: continue
            path=Path(tmp)/f"stream-{stream['index']}.ass"
            subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(filepath),'-map',f"0:{stream['index']}",'-c:s','ass',str(path)],capture_output=True,text=True,check=True)
            subs=pysubs2.load(path); samples=[]
            for event in subs:
                text=__import__('re').sub(r'\{[^{}]*\}','',event.text).replace(r'\N',' ').strip()
                if text and text not in samples: samples.append(text)
                if len(samples)==5: break
            report.append({'index':stream['index'],'codec':stream.get('codec_name'),'language':stream.get('tags',{}).get('language'),
                           'title':stream.get('tags',{}).get('title',''),'event_count':len(subs),
                           'first_ms':subs[0].start if subs else None,'last_ms':max((e.end for e in subs),default=None),'samples':samples})
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group(required=True); group.add_argument('--dir'); group.add_argument('--video')
    p.add_argument('--output',required=True,help='Output directory'); p.add_argument('--stream',type=int); p.add_argument('--language',default='eng'); p.add_argument('--prefer',nargs='*')
    a=p.parse_args()
    if a.dir and a.stream is not None: p.error('--stream is only valid with --video')
    root=Path(a.dir or Path(a.video).parent).resolve()
    paths=[Path(a.video).resolve()] if a.video else sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in ('.mkv','.mp4','.m4v','.mov'))
    if not paths: p.error('No media files found')
    report=[]
    for path in paths:
        try:
            s=select_stream(subtitle_streams(path),a.language,a.stream,a.prefer)
            rel=path.relative_to(root)
            # Keep the original extension in the basename to avoid foo.mp4/foo.mkv collision.
            output=Path(a.output)/rel.parent/(rel.name+'.ass')
            extract_subtitle(path,s['index'],output)
            report.append({'file':str(path),'stream':s['index'],'output':str(output),'status':'extracted'})
        except (OSError,ValueError,subprocess.CalledProcessError) as e:
            item={'file':str(path),'status':'failed','reason':str(e)}
            if 'Ambiguous subtitle streams' in str(e):
                item['content_inspection']=inspect_stream_content(path,subtitle_streams(path))
                item['reason']+='; inspect content_inspection and rerun with --stream'
            report.append(item)
    write_json(Path(a.output)/'_extraction_report.json',report,overwrite=False)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    sys.exit(1 if any(r['status']=='failed' for r in report) else 0)

if __name__=='__main__': main()
