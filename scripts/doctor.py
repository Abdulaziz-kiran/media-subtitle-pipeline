#!/usr/bin/env python3
"""Read-only runtime capability report. No download or configuration mutation."""
import json
import platform
import shutil
import subprocess
import sys
import pysubs2
from verify_render_qa import find_renderer


def main():
    result={'python':platform.python_version(),'pysubs2':pysubs2.__version__,'ffmpeg':shutil.which('ffmpeg'),'ffprobe':shutil.which('ffprobe')}
    try:result['libass_renderer']=find_renderer()
    except ValueError as e:result['libass_renderer']=None;result['render_reason']=str(e)
    result['translation_ready']=bool(result['ffprobe'] and result['ffmpeg'])
    result['render_ready']=bool(result['libass_renderer'])
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['translation_ready'] and result['render_ready'] else 1

if __name__=='__main__':sys.exit(main())
