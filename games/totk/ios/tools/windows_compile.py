#!/usr/bin/env python3
"""Cross-compile the v143 iOS sources with Windows-hosted LLVM.

This step produces objects; linking and resource packaging are separate steps.
All generated sources, objects and logs stay under --out.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
GAME = ROOT / 'games/totk'
EXTENSIONS = {'.c', '.m', '.S'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('clang', 'sdk', 'generated', 'opus-include', 'vpx-include', 'out'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1: parser.error('--jobs must be positive')
    clang, sdk, generated, opus, vpx, out = (p.resolve() for p in
        (args.clang, args.sdk, args.generated, args.opus_include, args.vpx_include, args.out))
    for path in (generated / 'ios_embed.h', generated / 'embed.S', opus / 'opus.h', vpx / 'vpx/vpx_decoder.h'):
        if not path.is_file(): raise ValueError(f'required input missing: {path}')
    objects, logs = out / 'objects', out / 'logs'
    objects.mkdir(parents=True, exist_ok=True); logs.mkdir(parents=True, exist_ok=True)
    (out / 'inventory.json').unlink(missing_ok=True)  # an interrupted build cannot leave a success manifest
    with tempfile.TemporaryDirectory(prefix='ios-sources-', dir=out) as work:
        work = Path(work)
        for src, dest in ((GAME / 'runtime', work / 'runtime'),
                          (GAME / 'ios/Sources', work / 'ios/Sources'),
                          (GAME / 'third_party/d2r_gfx', work / 'third_party/d2r_gfx'),
                          (ROOT / 'zeldaVR', work / 'zeldaVR')):
            shutil.copytree(src, dest)
        folders = [work / 'runtime', work / 'ios/Sources', work / 'third_party/d2r_gfx/gfx/nvn',
                   work / 'third_party/d2r_gfx/gfx/tex', work / 'zeldaVR/gfx']
        sources = [p for folder in folders for p in folder.rglob('*') if p.is_file() and p.suffix in EXTENSIONS]
        sources = [p for p in sources if p.relative_to(work).as_posix() not in
                   ('runtime/frontend.m', 'runtime/game_patches.c', 'runtime/game_patches_botw.c')]
        if len(sources) != len(set(sources)): raise ValueError('duplicate source paths')
        sources.sort()
        common = [str(clang), '-target', 'arm64-apple-ios26.0', '-isysroot', str(sdk),
                  '-F', str(sdk / 'System/Library/SubFrameworks'), '-DUSE_UIKIT_PUBLIC_HEADERS=1',
                  '-DTOTK_GAME_V143=1', '-fobjc-arc', '-mcpu=apple-a15', '-O2',
                  *[f'-I{x}' for x in (work / 'runtime', work / 'third_party/d2r_gfx/gfx/nvn',
                     work / 'third_party/d2r_gfx/gfx/nvn/include', generated, opus, vpx)]]

        def compile_one(source):
            relative = source.relative_to(work).as_posix()
            name = relative.replace('/', '__') + '.o'
            target = objects / name
            temporary = work / name
            cmd = [*common, *(['-Dmain=totk_host_main'] if relative == 'runtime/loader.c' else []),
                   '-c', str(source), '-o', str(temporary)]
            with (logs / (name + '.log')).open('w', encoding='utf-8') as log:
                result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
            digest = None
            if result.returncode == 0:
                with temporary.open('rb') as f:
                    header = f.read(8)
                    if len(header) != 8 or struct.unpack('<II', header) != (0xfeedfacf, 0x100000c):
                        raise ValueError(f'{relative}: compiler did not produce an ARM64 Mach-O object')
                    f.seek(0); digest = hashlib.file_digest(f, 'sha256').hexdigest()
                temporary.replace(target)
            else: target.unlink(missing_ok=True)
            return {'source': relative, 'object': str(target), 'log': str(logs / (name + '.log')),
                    'exit_code': result.returncode, 'sha256': digest}

        results = []
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [pool.submit(compile_one, source) for source in sources]
            for future in as_completed(futures):
                result = future.result(); results.append(result)
                print(f"[{len(results)}/{len(sources)}] {'OK' if not result['exit_code'] else 'FAIL'} {result['source']}", flush=True)
        results.sort(key=lambda item: item['source'])
        (out / 'inventory.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
        failed = [r for r in results if r['exit_code']]
        for result in failed:
            print(Path(result['log']).read_text(encoding='utf-8', errors='replace'), file=sys.stderr)
        if failed: raise RuntimeError(f'{len(failed)} iOS sources failed to compile; see {logs}')
    print(f'{len(sources)} iOS sources compiled: {objects}')


if __name__ == '__main__':
    main()
