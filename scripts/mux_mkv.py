#!/usr/bin/env python3
"""Copy all streams, add Turkish ASS/fonts and verify defaults without re-encoding."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
from content_filter_pipeline import probe,media_signature
from subtitle_core import write_json
from subtitle_core import ROOT,read_json,load_profile,file_hash


LANG_EQUIV={'ja':'jpn','jpn':'jpn','en':'eng','eng':'eng','ko':'kor','kor':'kor','fr':'fra','fre':'fra','fra':'fra','de':'deu','ger':'deu','deu':'deu','es':'spa','spa':'spa','it':'ita','ita':'ita','zh':'zho','chi':'zho','zho':'zho'}


def norm_lang(value):
    value=str(value or '').strip().casefold()
    return LANG_EQUIV.get(value,value)


def choose_original_audio(audio,audio_lang=None,context=None):
    if not audio: raise ValueError('No audio streams found')
    context=context or {}
    if not isinstance(context,dict): raise ValueError('Audio context must be an object')
    def select(wanted,reason):
        matches=[i for i,s in enumerate(audio) if norm_lang(s.get('tags',{}).get('language'))==wanted]
        if len(matches)>1:
            filtered=[i for i in matches if 'commentary' not in audio[i].get('tags',{}).get('title','').casefold() and not audio[i].get('disposition',{}).get('commentary')]
            if len(filtered)==1:
                matches=filtered
        if len(matches)!=1: raise ValueError('Original audio language missing or ambiguous: '+wanted)
        return matches[0],wanted,reason
    if audio_lang:
        if not isinstance(audio_lang,str): raise ValueError('Explicit audio language must be text')
        return select(norm_lang(audio_lang),'explicit_language')
    if str(context.get('media_type','')).casefold()=='anime':
        matches=[i for i,s in enumerate(audio) if norm_lang(s.get('tags',{}).get('language'))=='jpn']
        if matches:
            return select('jpn','anime_original_fallback')
    status=context.get('original_audio_status')
    if status in ('verified','single_stream'):
        language=context.get('original_audio_language'); evidence=context.get('original_audio_evidence')
        if not isinstance(language,str) or not language.strip() or not isinstance(evidence,str) or len(evidence.strip())<10:
            raise ValueError('Verified original audio needs a language and concrete textual evidence')
        if status=='single_stream' and len(audio)!=1:
            raise ValueError('single_stream audio claim contradicts the probed stream count')
        return select(norm_lang(language),'verified_context_original_language')
    original=[i for i,s in enumerate(audio) if s.get('disposition',{}).get('original')]
    if len(original)==1:
        lang=norm_lang(audio[original[0]].get('tags',{}).get('language'))
        return original[0],lang or 'und','stream_original_flag'
    if len(audio)==1:
        lang=norm_lang(audio[0].get('tags',{}).get('language'))
        return 0,lang or 'und','single_audio_stream'
    raise ValueError('Original audio cannot be determined; provide verified context or an explicit user choice')


def font_metadata(path):
    data=Path(path).read_bytes()
    if len(data)<12 or data[:4]==b'ttcf': raise ValueError('Unsupported or invalid font container: '+str(path))
    count=struct.unpack_from('>H',data,4)[0]; name_table=None
    for i in range(count):
        pos=12+i*16
        if pos+16>len(data): raise ValueError('Invalid font table directory: '+str(path))
        tag,_,offset,length=struct.unpack_from('>4sIII',data,pos)
        if tag==b'name': name_table=(offset,length)
    if not name_table: raise ValueError('Font has no name metadata: '+str(path))
    start,length=name_table
    if start+length>len(data) or start+6>len(data): raise ValueError('Invalid font name table: '+str(path))
    _,records,string_offset=struct.unpack_from('>HHH',data,start); names={}
    for i in range(records):
        pos=start+6+i*12
        if pos+12>start+length: raise ValueError('Invalid font name record: '+str(path))
        platform,encoding,language,name_id,size,offset=struct.unpack_from('>HHHHHH',data,pos)
        if name_id not in (1,2,16,17): continue
        raw_start=start+string_offset+offset; raw=data[raw_start:raw_start+size]
        if len(raw)!=size: raise ValueError('Invalid font name string: '+str(path))
        try: value=raw.decode('utf-16-be' if platform in (0,3) else 'mac_roman').strip('\x00').strip()
        except UnicodeDecodeError: continue
        if value: names.setdefault(name_id,[]).append((platform==3 and language==0x409,value))
    def pick(primary,fallback):
        rows=names.get(primary) or names.get(fallback) or []
        return next((v for english,v in rows if english),rows[0][1] if rows else '')
    family,style=pick(16,1),pick(17,2)
    if not family or not style: raise ValueError('Font family/style metadata missing: '+str(path))
    return {'file':Path(path).name,'family':family,'style':style,'sha256':file_hash(path)}


def inspect_fonts(fonts,expected_family=None,require_regular_bold=False):
    rows=[font_metadata(f) for f in fonts]
    norm=lambda s:''.join(str(s).casefold().split())
    if expected_family and any(norm(r['family'])!=norm(expected_family) for r in rows):
        raise ValueError('Font family does not match requested profile: '+str(expected_family))
    styles={r['style'].casefold() for r in rows}
    if require_regular_bold and (not any('regular' in s or 'normal' in s for s in styles) or not any('bold' in s for s in styles)):
        raise ValueError('Default font package needs real Regular and Bold faces')
    return rows


def av_payload_hashes(path,info):
    """Hash encoded audio/video payloads so subtitle duration cannot fake preservation."""
    result=[]
    empty_sha256='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    for stream in info['streams']:
        if stream.get('codec_type') not in ('audio','video'): continue
        r=subprocess.run(['ffmpeg','-nostdin','-v','error','-fflags','+noparse+nofillin','-i',str(path),'-map',f"0:{stream['index']}",'-c','copy','-f','streamhash','-hash','sha256','-'],capture_output=True,text=True,check=True)
        digest=r.stdout.strip().split('=',1)[-1].strip()
        if not digest or digest==empty_sha256: raise ValueError('Could not verify encoded media payload: empty or missing stream data')
        result.append((stream['codec_type'],stream.get('codec_name'),digest))
    return result


def mux_single(video_path,ass_path,output_path,font_path=None,sub_lang='tur',sub_title='Türkçe',audio_lang=None,context_path=None,font_family=None):
    video,ass,output=map(Path,(video_path,ass_path,output_path))
    if not video.is_file() or not ass.is_file(): raise ValueError('Source video/subtitle missing')
    if output.exists() or output.resolve() in (video.resolve(),ass.resolve()) or output.suffix.lower()!='.mkv': raise ValueError('Choose a new MKV destination')
    info=probe(video); streams=info['streams']
    subs=[s for s in streams if s['codec_type']=='subtitle']; audio=[s for s in streams if s['codec_type']=='audio']
    attachments=[s for s in streams if s['codec_type']=='attachment']
    context=read_json(context_path) if context_path else {}
    audio_idx,audio_language,audio_reason=choose_original_audio(audio,audio_lang,context)
    default_fonts=font_path is None
    if default_fonts:
        fonts=[ROOT/'resources/fonts/SourceSans3-Regular.otf',ROOT/'resources/fonts/SourceSans3-Bold.otf']
    else:
        fonts=[Path(font_path)] if isinstance(font_path,(str,Path)) else [Path(f) for f in font_path]
    if any(not f.is_file() for f in fonts): raise ValueError('Requested font missing')
    font_info=inspect_fonts(fonts,font_family or (load_profile()['font'] if default_fonts else None),default_fonts)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        candidate=Path(tmp)/'candidate.mkv'
        # Dual-input architecture:
        # Input 0: +noparse+nofillin prevents dropping AV1 keyframes (show_frame=0) in stream-copy.
        # Input 1: normal parser ensures audio (Opus etc.) correctly calculates PTS timestamps.
        # Input 2: Turkish ASS subtitle.
        cmd=['ffmpeg','-nostdin','-v','error',
             '-fflags','+noparse+nofillin','-i',str(video),
             '-i',str(video),
             '-i',str(ass),
             '-map','0:v',
             '-map','1:a',
             '-map','1:s?',
             '-map','2:0',
             '-map','1:t?',
             '-map_metadata','1','-map_chapters','1','-c','copy',
             '-max_interleave_delta','0']
        for i in range(len(subs)): cmd += [f'-disposition:s:{i}','-default']
        cmd += [f'-metadata:s:s:{len(subs)}',f'language={sub_lang}',f'-metadata:s:s:{len(subs)}',f'title={sub_title}',f'-disposition:s:{len(subs)}','default']
        if audio_idx is not None:
            for i in range(len(audio)): cmd += [f'-disposition:a:{i}','-default']
            cmd += [f'-disposition:a:{audio_idx}','+default']
        for i,f in enumerate(fonts):
            mime='application/vnd.ms-opentype' if f.suffix.lower()=='.otf' else 'application/x-truetype-font'
            cmd += ['-attach',str(f),f'-metadata:s:t:{len(attachments)+i}',f'mimetype={mime}',f'-metadata:s:t:{len(attachments)+i}',f'filename={f.name}']
        cmd.append(str(candidate))
        subprocess.run(cmd,capture_output=True,text=True,check=True)
        got=probe(candidate)
        old_sig=media_signature(info); new_sig=media_signature(got)
        # ffmpeg groups stream types in some containers; compare multiplicity, not global order.
        from collections import Counter
        required=Counter(old_sig)
        if required-Counter(new_sig): raise ValueError('Original streams/attachments missing')
        outsubs=[s for s in got['streams'] if s['codec_type']=='subtitle']
        if len(outsubs)!=len(subs)+1 or outsubs[-1].get('tags',{}).get('language')!=sub_lang:
            raise ValueError('New subtitle not present as expected')
        if sum(bool(s.get('disposition',{}).get('default')) for s in outsubs)!=1 or not outsubs[-1].get('disposition',{}).get('default'):
            raise ValueError('Subtitle default flag verification failed')
        if audio_idx is not None:
            outaudio=[s for s in got['streams'] if s['codec_type']=='audio']
            if [i for i,s in enumerate(outaudio) if s.get('disposition',{}).get('default')]!=[audio_idx]: raise ValueError('Audio default verification failed')
        if av_payload_hashes(video,info)!=av_payload_hashes(candidate,got):
            raise ValueError('Audio/video payload changed during mux')
        os.link(candidate,output)
    return {'status':'muxed','output':str(output),'streams_preserved':True,'turkish_default':True,
            'audio_video_payloads_preserved':True,'attached_fonts':font_info,
            'default_audio_language':audio_language,'default_audio_reason':audio_reason,
            'max_interleave_delta_us':0,'visual_playback':'not_checked'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',required=True); p.add_argument('--ass',required=True); p.add_argument('--output',required=True)
    p.add_argument('--font',action='append'); p.add_argument('--font-family'); p.add_argument('--audio-lang'); p.add_argument('--context'); p.add_argument('--sub-lang',default='tur'); p.add_argument('--sub-title',default='Türkçe')
    a=p.parse_args()
    sidecar=Path(a.output+'.mux.json')
    if sidecar.exists() or sidecar.is_symlink():
        print('Mux report output already exists; choose new output paths',file=sys.stderr); sys.exit(2)
    created=False
    try:
        r=mux_single(a.video,a.ass,a.output,a.font,a.sub_lang,a.sub_title,a.audio_lang,a.context,a.font_family)
        created=True
        write_json(sidecar,r,overwrite=False)
        print(json.dumps(r,ensure_ascii=False,indent=2))
    except (ValueError,OSError,subprocess.CalledProcessError) as e:
        if created: Path(a.output).unlink(missing_ok=True)
        print(str(e),file=sys.stderr); sys.exit(2)

if __name__=='__main__': main()
