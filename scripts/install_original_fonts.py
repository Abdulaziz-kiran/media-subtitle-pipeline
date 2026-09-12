#!/usr/bin/env python3
"""Restore the user's original font assets locally; no network or arbitrary extraction."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ORIGINAL_ZIP_SHA256='3e0d285c42c11f09e008331248c1435e30a57546db4af3fe1057df8f610c995d'
FONT_SHA256={
    'SourceSans3-Regular.otf':'08df266400933d3178d081a45f94a08814c3e55b4b7dd2e0ff69cb1329f13ab6',
    'SourceSans3-Bold.otf':'7776ddb9f3eb58683e59f28d558d8896b768c2d0c80799fb3f1c56c54dfd98c9',
}
ROOT=Path(__file__).resolve().parents[1]

def digest_file(path: Path) -> str:
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def install(original_zip: Path, fonts_dir: Path | None=None) -> dict:
    original_zip=Path(original_zip)
    if not original_zip.is_file() or digest_file(original_zip)!=ORIGINAL_ZIP_SHA256:
        raise ValueError('The supplied original ZIP does not match the independently recorded SHA-256')
    target=Path(fonts_dir) if fonts_dir is not None else ROOT/'resources/fonts'
    if any(p.is_symlink() for p in [target,*target.parents]):
        raise ValueError('Font installation target must not traverse a symbolic link')
    payloads={}
    with zipfile.ZipFile(original_zip) as archive:
        names=archive.namelist()
        for name,digest in FONT_SHA256.items():
            member='media-subtitle-pipeline/resources/fonts/'+name
            if names.count(member)!=1:
                raise ValueError('Expected exactly one original font member: '+member)
            info=archive.getinfo(member)
            if info.file_size>10_000_000 or ((info.external_attr>>16)&0o170000)==0o120000:
                raise ValueError('Invalid original font member')
            data=archive.read(info)
            if hashlib.sha256(data).hexdigest()!=digest:
                raise ValueError('Original font payload hash mismatch: '+name)
            destination=target/name
            if destination.exists() and (not destination.is_file() or destination.is_symlink() or
                                         destination.stat().st_nlink!=1 or digest_file(destination)!=digest):
                raise ValueError('Refusing to overwrite a different existing font: '+str(destination))
            payloads[name]=data
    target.mkdir(parents=True,exist_ok=True)
    created=[]
    try:
        with tempfile.TemporaryDirectory(prefix='.font-install-',dir=target) as td:
            for name,data in payloads.items():
                destination=target/name
                if destination.exists(): continue
                staged=Path(td)/name;staged.write_bytes(data)
                os.link(staged,destination);created.append(destination)
    except Exception:
        for path in reversed(created): path.unlink(missing_ok=True)
        raise
    return {'status':'original_fonts_verified_and_available','network_used':False,
            'original_zip_sha256':ORIGINAL_ZIP_SHA256,'fonts':FONT_SHA256}

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-zip',required=True,type=Path)
    args=parser.parse_args()
    try:
        print(json.dumps(install(args.original_zip),ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,zipfile.BadZipFile) as exc:
        print(str(exc),file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
