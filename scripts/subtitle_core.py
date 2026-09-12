"""Shared deterministic substrate. Translation and semantic review belong to the active agent."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import stat
import unicodedata
import pysubs2

VERSION = '2.3.1'
ROOT = Path(__file__).resolve().parent.parent
TAG = re.compile(r'\{[^{}]*\}')
MARKER = re.compile(r'⟪ASS:(\d+)⟫')
KARAOKE = re.compile(r'\\[kK](?:[of])?\d+')
DRAWING = re.compile(r'\\p[1-9]\d*(?!\d)')
SONG_STYLE = re.compile(r'^(?:op|ed|opening|ending|insert|song)(?:\b|_)', re.I)
SIGN_STYLE = re.compile(r'^(?:sign|tabela|title|next time)(?:\b|_)', re.I)


def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def object_hash(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def write_json(path, data, overwrite=True):
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n', overwrite)


def atomic_text(path, text, overwrite=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if overwrite:
            os.replace(tmp, path)
        else:
            # Atomic no-clobber even when two agents choose the same destination.
            os.link(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save_ass(subs, output, source=None, overwrite=False):
    output = Path(output)
    if output.suffix.lower() != '.ass':
        raise ValueError('Final subtitle output must be .ass')
    if source and output.resolve() == Path(source).resolve():
        raise ValueError('Source and output must differ')
    text = subs.to_string('ass')
    restored = pysubs2.SSAFile.from_string(text, 'ass')
    if len(restored) != len(subs):
        raise ValueError('ASS roundtrip changed event count')
    atomic_text(output, text, overwrite)


def load_profile(path=None):
    profile = read_json(ROOT / 'resources/profile.json')
    if path:
        updates = read_json(path)
        if not isinstance(updates, dict) or set(updates) - set(profile):
            raise ValueError('Unknown profile keys')
        profile.update(updates)
    for key in ('max_cps','max_cpl','max_lines','min_duration_ms','max_duration_ms','short_max_ms','max_extension_ms','gap_ms','batch_size','scene_gap_ms'):
        n = profile[key]
        if isinstance(n, bool) or not isinstance(n, (int,float)) or not math.isfinite(n) or n <= 0:
            raise ValueError('Invalid profile value: '+key)
    for key in ('max_cpl','max_lines','batch_size'):
        if type(profile[key]) is not int:
            raise ValueError(key+' must be an integer')
    if profile['max_lines'] != 2:
        raise ValueError('This wrapping engine supports at most two lines')
    if (type(profile['translate_signs']) is not bool or type(profile['translate_songs']) is not bool
            or (profile['font'] is not None and not isinstance(profile['font'],str))):
        raise ValueError('Invalid font or translation preference type')
    if profile['min_duration_ms'] > profile['max_duration_ms']:
        raise ValueError('Invalid duration interval')
    return profile


def visible(text):
    text = TAG.sub('', text).replace(r'\N','\n').replace(r'\n','\n').replace(r'\h',' ')
    return unicodedata.normalize('NFC', text)


def protected(text):
    tags = TAG.findall(text)
    idx = iter(range(len(tags)))
    return TAG.sub(lambda m: f'⟪ASS:{next(idx)}⟫', text)


def format_parts(text):
    """Return the fixed text slots around ASS tags.

    Translating these slots separately lets the builder put every original tag
    back at the same structural boundary instead of trusting movable markers.
    """
    return TAG.split(text)


def restore_structured_parts(source, parts, scope_change_reason=None):
    source_tags=TAG.findall(source)
    expected=format_parts(source)
    if not isinstance(parts,list) or len(parts)!=len(expected):
        raise ValueError('Tagged line needs one translated part for every fixed ASS boundary')
    output=[]; changed_scope=[]
    for n,item in enumerate(parts):
        if not isinstance(item,dict) or type(item.get('part')) is not int or item.get('part')!=n or not isinstance(item.get('tr_text'),str):
            raise ValueError('Invalid or reordered translated ASS part: '+str(n))
        if item.get('source_text') != expected[n]:
            raise ValueError('Translated ASS part is not bound to its source slot: '+str(n))
        text=item['tr_text']
        if '\n' in text or '\r' in text: raise ValueError('Use ASS \\N line breaks, not literal newlines')
        if TAG.search(text) or '⟪ASS:' in text or re.search(r'[{}]',text):
            raise ValueError('Translated ASS parts cannot contain tags or markers')
        if bool(expected[n].strip()) != bool(text.strip()): changed_scope.append(n)
        output.append(text)
        if n<len(source_tags): output.append(source_tags[n])
    if changed_scope and (not isinstance(scope_change_reason,str) or len(scope_change_reason.strip())<20):
        raise ValueError('Moving text across ASS style slots needs a concrete scope_change_reason')
    return ''.join(output)


def response_item(event,index):
    base={'index':index,'unchanged_reason':''}
    tags=TAG.findall(event.text)
    if role(event)=='karaoke':
        base['tr_text']=''
        base['romaji_status']='verified|unavailable'
        base['romaji_source']=''
        if tags:
            base['scope_change_reason']=''
            base['romaji_parts']=[{'part':n,'source_text':text,'romaji_text':''} for n,text in enumerate(format_parts(event.text))]
        else:
            base['romaji_text']=''
    elif tags:
        base['scope_change_reason']=''
        base['parts']=[{'part':n,'source_text':text,'tr_text':''} for n,text in enumerate(format_parts(event.text))]
    else:
        base['tr_text']=''
    return base


def restore_tags(source, translated):
    if TAG.findall(source):
        raise ValueError('Marker-only tag restoration is unsafe; use fixed translated parts')
    if '\n' in translated or '\r' in translated:
        raise ValueError('Use ASS \\N line breaks, not literal newlines')
    source_tags = TAG.findall(source)
    if MARKER.search(translated):
        found = [int(m) for m in MARKER.findall(translated)]
        if found != list(range(len(source_tags))) or TAG.search(translated):
            raise ValueError('Protected ASS markers missing, reordered or duplicated')
        translated = MARKER.sub(lambda m: source_tags[int(m[1])], translated)
    if TAG.findall(translated) != source_tags:
        raise ValueError('ASS tags must match source in original order')
    if re.search(r'[{}]', TAG.sub('', translated)):
        raise ValueError('Unbalanced ASS braces')
    if '⟪ASS:' in translated:
        raise ValueError('Unresolved ASS marker')
    return translated


def role(event):
    if event.is_comment:
        return 'comment'
    if DRAWING.search(event.text):
        return 'drawing'
    if KARAOKE.search(event.text) or SONG_STYLE.search(event.style or ''):
        return 'karaoke'
    if not visible(event.text).strip():
        return 'empty'
    if SIGN_STYLE.search(event.style or '') or re.search(r'\\(?:pos\(|move\(|an[789](?!\d))', event.text):
        return 'sign'
    return 'dialogue'


def classify_line(event, profile=None):
    profile = profile or load_profile()
    kind = role(event)
    return 'TRANSLATABLE' if (kind=='dialogue' or (kind=='sign' and profile['translate_signs'])
                              or (kind=='karaoke' and profile['translate_songs'])) else 'PASSTHROUGH'


def wrap_text(text, limit=40):
    # Never relocate inline formatting. Insert a break at an existing visible space.
    if r'\N' in text or r'\n' in text or '\n' in text:
        return text
    if len(visible(text)) <= limit:
        return text
    candidates=[]
    for match in re.finditer(r'\{[^{}]*\}|[^{}]+', text):
        part=match[0]
        if part.startswith('{'):
            continue
        for space in re.finditer(' ', part):
            i=match.start()+space.start()
            a,b=visible(text[:i]).strip(),visible(text[i+1:]).strip()
            if not a or not b:
                continue
            overflow=max(0,len(a)-limit)+max(0,len(b)-limit)
            punctuation = 0 if a[-1:] in ',;:.!?' else 4
            candidates.append(((overflow,abs(len(a)-len(b))+punctuation),i))
    if not candidates:
        return text
    _,i=min(candidates)
    return text[:i]+r'\N'+text[i+1:]


def text_issues(text, duration_ms, profile):
    plain=visible(text)
    lines=plain.split('\n')
    cps=len(plain.replace('\n',' '))/max(duration_ms/1000,0.001)
    issues=[]
    if not plain.strip(): issues.append('EMPTY_TEXT')
    if duration_ms<=0: issues.append('INVALID_TIME')
    if duration_ms<profile['min_duration_ms']: issues.append('MIN_DURATION')
    if duration_ms>profile['max_duration_ms']: issues.append('MAX_DURATION')
    if len(plain.split())<=2 and duration_ms>profile['short_max_ms']: issues.append('SHORT_LINGER')
    if cps>profile['max_cps']: issues.append('CPS_HIGH')
    if len(lines)>profile['max_lines']: issues.append('TOO_MANY_LINES')
    if any(len(line)>profile['max_cpl'] for line in lines): issues.append('CPL_HIGH')
    return issues, {'cps':round(cps,2),'max_cpl':max(map(len,lines),default=0),'lines':len(lines),'duration_ms':duration_ms}


def optimize_timing(subs, indices, profile, windows=None):
    # Retiming is possible only inside explicitly audio/scene-verified windows.
    changes=[]
    windows=windows or {}
    dialogue=sorted((i for i,e in enumerate(subs) if role(e)=='dialogue'), key=lambda i:(subs[i].start,subs[i].end,i))
    for pos,i in enumerate(dialogue):
        if i not in indices or str(i) not in windows:
            continue
        ev=subs[i]; w=windows[str(i)]
        low,high=w['min_end_ms'],w['max_end_ms']
        if type(low) is not int or type(high) is not int or not ev.start < low <= ev.end <= high or not w.get('evidence'):
            raise ValueError('Invalid verified timing window for '+str(i))
        if re.search(r'\\(?:t\(|k|K|fad|fade|move)',ev.text):
            continue  # time-dependent ASS effects need a separate edit
        # Preserve existing overlaps. Never create new ones on the same dialogue plane.
        simultaneous=any(j!=i and subs[j].start<ev.end and subs[j].end>ev.start for j in dialogue)
        if simultaneous:
            continue
        next_start=subs[dialogue[pos+1]].start if pos+1<len(dialogue) else high+profile['gap_ms']
        cap=min(high,next_start-profile['gap_ms'],ev.end+profile['max_extension_ms'],ev.start+profile['max_duration_ms'])
        plain=visible(ev.text).replace('\n',' ')
        desired=ev.start+max(profile['min_duration_ms'],math.ceil(len(plain)/profile['max_cps']*1000))
        if len(plain.split())<=2:
            desired=min(desired,ev.start+profile['short_max_ms'])
        # ASS serializes in centiseconds; stay inside the verified interval.
        new_end=max(math.ceil(low/10)*10,min(math.floor(cap/10)*10,math.ceil(desired/10)*10))
        if new_end>cap:
            continue
        if ev.end!=new_end:
            changes.append({'index':i,'before':ev.end,'after':new_end,'evidence':w['evidence']})
            ev.end=new_end
    return changes


def ensure_plain_tree(root):
    """Reject linked or special entries in a job/archive before reading or writing.

    This is integrity checking, not a sandbox against a process with the same
    filesystem permissions. Ordinary source reads need not traverse this helper.
    """
    root=Path(root)
    for path in [root, *root.rglob('*')]:
        info=path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError('Symlink is not allowed in a job/archive: '+str(path))
        if stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                raise ValueError('Hard-linked file is not allowed in a job/archive: '+str(path))
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError('Special file is not allowed in a job/archive: '+str(path))


def publish_directory(staging,destination):
    """Reserve a previously unused name, then replace our own empty reservation.

    Exclusive mkdir also refuses a pre-existing empty directory or broken link.
    Readers must require the manifest before regarding an archive as committed.
    """
    staging,destination=Path(staging),Path(destination)
    destination.mkdir(mode=0o700)
    identity=destination.stat()
    try:
        current=destination.lstat()
        if (current.st_dev,current.st_ino)!=(identity.st_dev,identity.st_ino):
            raise ValueError('Directory reservation changed before publication')
        os.rename(staging,destination)
    except Exception:
        try:
            current=destination.lstat()
            if (current.st_dev,current.st_ino)==(identity.st_dev,identity.st_ino): destination.rmdir()
        except OSError:
            pass
        raise


def plain_song_line(text,label):
    if (not isinstance(text,str) or not text.strip() or
            any(c in text for c in ('\\','\n','\r','{','}')) or '⟪ASS:' in text):
        raise ValueError(label+' must be plain single-line text; line breaks/tags/markers are not allowed')
    return text.strip()


def validate_romaji_provenance(event,item,romaji):
    """Ground in source script/timed text, or record an explicit external attestation.

    An external source's language/meaning and the truth of a review declaration
    remain the active reviewer's responsibility, never an automatic guarantee.
    """
    japanese=re.compile(r'[\u3040-\u30ff\u3400-\u9fff]')
    reference=item.get('romaji_source')
    if not isinstance(reference,str) or len(reference.strip())<3:
        raise ValueError('Verified romaji needs a concrete source reference')
    if japanese.search(visible(event.text)):
        return 'source_japanese_text'
    if KARAOKE.search(event.text) and visible(romaji).strip()==visible(event.text).strip():
        return 'preserved_timed_source_text'
    evidence=item.get('romaji_evidence')
    if not isinstance(evidence,dict) or evidence.get('kind') not in ('japanese_lyrics','original_audio'):
        raise ValueError('English-only meaning subtitles cannot establish Japanese romaji; provide source-bound external review evidence')
    for key,minimum in (('reference',3),('reviewed_by',3),('review_summary',20),('japanese_text',1)):
        if not isinstance(evidence.get(key),str) or len(evidence[key].strip())<minimum:
            raise ValueError('External romaji evidence needs '+key)
    if not japanese.search(evidence['japanese_text']):
        raise ValueError('External romaji evidence needs a Japanese transcription, not English meaning')
    if evidence.get('language') not in ('ja','jpn') or evidence.get('review_attested') is not True:
        raise ValueError('External romaji evidence needs an explicit Japanese-source review attestation')
    if not isinstance(evidence.get('source_sha256'),str) or not re.fullmatch(r'[0-9a-f]{64}',evidence['source_sha256']):
        raise ValueError('External romaji evidence needs the referenced source SHA-256')
    return 'external_source_attested_by_reviewer'


def translated_text(event,item):
    kind=role(event); tags=TAG.findall(event.text)
    if kind=='karaoke':
        turkish=item.get('tr_text')
        status=item.get('romaji_status')
        if not isinstance(turkish,str) or not visible(turkish).strip():
            raise ValueError('Karaoke line needs a Turkish translation')
        turkish=plain_song_line(turkish,'Turkish karaoke line')
        if status not in ('verified','unavailable'):
            raise ValueError('Karaoke romaji status must be verified or unavailable')
        if status=='verified':
            if not str(item.get('romaji_source','')).strip():
                raise ValueError('Verified romaji needs a concrete source')
            if tags:
                raw=[]
                for part in item.get('romaji_parts',[]):
                    raw.append({'part':part.get('part'),'source_text':part.get('source_text'),'tr_text':part.get('romaji_text')})
                romaji=restore_structured_parts(event.text,raw,item.get('scope_change_reason'))
            else:
                romaji=item.get('romaji_text')
                romaji=plain_song_line(romaji,'Romaji line')
            plain_song_line(visible(romaji),'Romaji line')
            if re.search(r'\\[Nnh]',romaji): raise ValueError('Romaji line breaks are controlled by the builder')
            validate_romaji_provenance(event,item,romaji)
            # \r resets style, not the accumulated karaoke clock in libass.
            # A builder-owned zero-time syllable resets the effect at the boundary.
            return romaji+r'{\kt0\k0}{\r}\N'+turkish.strip()
        if item.get('romaji_evidence'):
            raise ValueError('Unavailable romaji cannot carry a source-verification claim')
        if str(item.get('romaji_source','')).strip():
            raise ValueError('Unavailable romaji cannot claim a source')
        # Preserve a timed source lyric when no trustworthy romanization exists;
        # reset formatting before Turkish so karaoke timing never moves to it.
        return (event.text+r'{\kt0\k0}{\r}\N' if tags else '')+turkish.strip()
    if tags:
        if 'tr_text' in item:
            raise ValueError('Tagged lines must use fixed translated parts, not movable markers')
        return restore_structured_parts(event.text,item.get('parts'),item.get('scope_change_reason'))
    text=item.get('tr_text')
    if not isinstance(text,str): raise ValueError('Missing translation')
    return restore_tags(event.text,text).strip()


def validate_translation(subs, data, expected_hash, profile):
    if not isinstance(data,dict) or data.get('source_sha256') != expected_hash:
        raise ValueError('Translation source hash is missing or stale')
    items=data.get('lines')
    if not isinstance(items,list):
        raise ValueError('lines must be a list')
    expected={i for i,e in enumerate(subs) if classify_line(e,profile)=='TRANSLATABLE'}
    seen=set(); output={}
    for item in items:
        i=item.get('index')
        if type(i) is not int or i<0 or i>=len(subs) or i in seen or i not in expected:
            raise ValueError('Invalid/duplicate/unexpected index: '+repr(i))
        seen.add(i)
        text=translated_text(subs[i],item)
        if not visible(text).strip(): raise ValueError('Missing translation: '+str(i))
        if visible(text).strip()==visible(subs[i].text).strip() and not item.get('unchanged_reason','').strip():
            raise ValueError('Unchanged source needs a concrete reason: '+str(i))
        output[i]=text
    if seen!=expected:
        raise ValueError('Incomplete translation; missing indices: '+str(sorted(expected-seen)))
    return output


def build_candidate(source_path, data, profile, timing_windows=None):
    subs=pysubs2.load(source_path)
    translations=validate_translation(subs,data,file_hash(source_path),profile)
    original=copy.deepcopy(subs)
    for i,text in translations.items():
        subs[i].text=wrap_text(text,profile['max_cpl']) if role(original[i])=='dialogue' else text
    changes=optimize_timing(subs,set(translations),profile,timing_windows)
    # Only restyle dialogue styles that aren't shared with signs/karaoke/drawings.
    unsafe_styles={e.style for e in subs if role(e)!='dialogue'}
    changed_styles=set()
    clones={}
    if profile['font']:
        for i in translations:
            e=subs[i]
            if role(original[i])!='dialogue': continue
            if e.style in unsafe_styles:
                original_style=e.style
                new=clones.get(original_style)
                if new is None:
                    new=original_style+'_TR'
                    while new in subs.styles: new+='_'
                    subs.styles[new]=copy.deepcopy(subs.styles[original_style])
                    clones[original_style]=new
                e.style=new
            subs.styles[e.style].fontname=profile['font']
            changed_styles.add(e.style)
    report=[]
    for i,e in enumerate(subs):
        if i not in translations: continue
        kind=role(original[i]); codes,metrics=text_issues(e.text,e.end-e.start,profile)
        if kind=='sign':
            codes=[c for c in codes if c in ('EMPTY_TEXT','INVALID_TIME')]
        elif kind=='karaoke':
            # A romaji + Turkish song line naturally doubles visible text. Dialogue
            # pacing thresholds do not describe timed lyrics; layout still matters.
            codes=[c for c in codes if c in ('EMPTY_TEXT','INVALID_TIME','TOO_MANY_LINES','CPL_HIGH')]
        if e.start<0: codes.append('NEGATIVE_TIME')
        # Report simultaneous dialogue for visual review, not automatic rejection of two-speaker scenes.
        if kind=='dialogue' and any(j!=i and role(other)=='dialogue' and other.start<e.end and other.end>e.start for j,other in enumerate(subs)):
            codes.append('DIALOGUE_OVERLAP')
        report.append({'index':i,'role':kind,'format_sensitive':bool(TAG.findall(original[i].text)) or kind=='karaoke','issues':codes,'metrics':metrics})
    return subs, {'engine_version':VERSION,'source_sha256':file_hash(source_path),'translated_lines':len(translations), 'passthrough_lines':len(subs)-len(translations),'timing_changes':changes,'remapped_styles':sorted(changed_styles),'lines':report}
