#!/usr/bin/env python3
"""One-to-one time pairing with blinded randomized A/B labels and a separate key."""
import argparse
import json
from pathlib import Path
import random
import sys
import pysubs2
from subtitle_core import visible,write_json


def compare_subtitles(file_a,file_b,sample_size=20,seed=None):
    if sample_size<=0: raise ValueError('Positive sample size required')
    a=[e for e in pysubs2.load(file_a) if not e.is_comment and visible(e.text).strip()]
    b=[e for e in pysubs2.load(file_b) if not e.is_comment and visible(e.text).strip()]
    used=set(); pairs=[]
    for ea in sorted(a,key=lambda e:e.start):
        candidates=[(abs(ea.start-eb.start),j,eb) for j,eb in enumerate(b) if j not in used and abs(ea.start-eb.start)<1500 and min(ea.end,eb.end)>max(ea.start,eb.start)]
        if not candidates:continue
        _,j,eb=min(candidates,key=lambda x:x[0]);used.add(j)
        pairs.append((ea,eb))
    rng=random.Random(seed); selected=rng.sample(pairs,min(sample_size,len(pairs)))
    public=[];key={}
    for n,(ea,eb) in enumerate(selected,1):
        reverse=bool(rng.getrandbits(1))
        public.append({'id':n,'time_ms':ea.start,'A':visible(eb.text if reverse else ea.text),'B':visible(ea.text if reverse else eb.text)})
        key[str(n)]={'A':'baseline' if reverse else 'pipeline','B':'pipeline' if reverse else 'baseline'}
    return {'pairs':public,'matched_pairs':len(pairs),'unmatched_a':len(a)-len(pairs),'unmatched_b':len(b)-len(pairs),'scope':'Time pairing is heuristic; verify scene equivalence before judging.'},key


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pipeline',required=True);p.add_argument('--baseline',required=True);p.add_argument('--sample',type=int,default=20)
    p.add_argument('--output',required=True);p.add_argument('--key',required=True);p.add_argument('--seed',type=int)
    a=p.parse_args()
    try:
        if Path(a.output).resolve()==Path(a.key).resolve() or Path(a.output).exists() or Path(a.key).exists():raise ValueError('Choose separate new public/key paths')
        public,key=compare_subtitles(a.pipeline,a.baseline,a.sample,a.seed)
        if not public['pairs']:raise ValueError('No aligned dialogue pairs')
        write_json(a.output,public,False);write_json(a.key,key,False)
        print(json.dumps({'status':'blind_sample_ready','pairs':len(public['pairs'])},ensure_ascii=False))
    except (ValueError,OSError) as e:print(str(e),file=sys.stderr);sys.exit(2)

if __name__=='__main__':main()
