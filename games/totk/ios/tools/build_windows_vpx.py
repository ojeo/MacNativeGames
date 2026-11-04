#!/usr/bin/env python3
"""Cross-compile the pinned iOS libvpx dependency on Windows with Git Bash and LLVM."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

REVISION = '1024874c5919305883187e2953de8fcb4c3d7fa6'  # v1.16.0, as build_deps.py


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'build', 'sdk', 'toolchain', 'bash', 'make'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1: parser.error('--jobs must be positive')
    source, build, sdk, tools, bash, make = (p.resolve() for p in
        (args.source, args.build, args.sdk, args.toolchain, args.bash, args.make))
    # libvpx's configure and Makefiles split compiler and SDK paths on spaces.
    if any(any(c.isspace() for c in str(p)) for p in (source, build, sdk, tools)):
        raise ValueError('source, build, SDK and toolchain paths must not contain whitespace')
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != REVISION: raise ValueError(f'libvpx must be checked out at {REVISION}')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        raise ValueError('libvpx source has local changes')
    version = str(json.loads((sdk / 'SDKSettings.json').read_text(encoding='utf-8'))['Version'])
    build.mkdir(parents=True, exist_ok=True)
    wrappers = build / 'windows-tools'; wrappers.mkdir(exist_ok=True)
    lld = wrappers / 'ld64.lld.exe'
    if not lld.exists():
        try: os.link(tools / 'lld.exe', lld)
        except OSError: shutil.copyfile(tools / 'lld.exe', lld)
    # Configure only uses Xcode's version to decide whether NEON is available; arm64 iOS has NEON.
    (wrappers / 'xcodebuild').write_text("#!/bin/sh\necho 'Xcode 26.0'\necho 'Build version WindowsCross'\n", encoding='ascii')
    xcrun = f'''#!/bin/sh
bin='{tools.as_posix()}'
sdk='{sdk.as_posix()}'
case "$*" in
  *--show-sdk-path*) printf '%s\\n' "$sdk";;
  *--show-sdk-version*) echo '{version}';;
  *--find\\ clang++) echo "$bin/clang++.exe";;
  *--find\\ clang) echo "$bin/clang.exe";;
  *--find\\ ar) echo "$bin/llvm-ar.exe";;
  *--find\\ as) echo "$bin/clang.exe";;
  *--find\\ strip) echo "$bin/llvm-strip.exe";;
  *) exit 1;;
esac
'''
    (wrappers / 'xcrun').write_text(xcrun, encoding='utf-8', newline='\n')
    temp = build / 'temp'; temp.mkdir(exist_ok=True)
    env = dict(os.environ, CFLAGS='-target arm64-apple-ios26.0 -Wno-overriding-option',
               CXXFLAGS='-target arm64-apple-ios26.0 -Wno-overriding-option',
               LDFLAGS=f'-target arm64-apple-ios26.0 -Wno-overriding-option --ld-path={lld.as_posix()} '
                       f'-Wl,-platform_version,ios,26.0,{version}',
               TMP=str(temp), TEMP=str(temp), TMPDIR=temp.as_posix())
    git_unix = bash.parent.parent / 'usr/bin'
    env['PATH'] = os.pathsep.join(map(str, (git_unix, wrappers, tools, make.parent))) + os.pathsep + env.get('PATH', '')
    configure = [str(bash), (source / 'configure').as_posix(), '--target=arm64-darwin-gcc',
                 '--disable-examples', '--disable-tools', '--disable-docs', '--disable-unit-tests',
                 '--disable-webm-io', '--enable-pic', '--disable-shared', '--enable-static',
                 '--disable-runtime-cpu-detect', '--disable-neon-asm', '--enable-neon', '--disable-neon-dotprod',
                 '--disable-neon-i8mm', '--disable-sve', '--disable-sve2']
    subprocess.run(configure, cwd=build, env=env, check=True)
    subprocess.run([str(make), f'-j{args.jobs}', 'libvpx.a'], cwd=build, env=env, check=True)
    if not (build / 'libvpx.a').is_file(): raise RuntimeError('libvpx archive was not produced')
    print(f'libvpx archive: {build / "libvpx.a"}; headers: {source}')


if __name__ == '__main__':
    main()
