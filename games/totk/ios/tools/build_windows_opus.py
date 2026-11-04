#!/usr/bin/env python3
"""Cross-compile the iOS Opus dependency on Windows using a pinned source checkout."""
import argparse
from pathlib import Path
import subprocess

OPUS_REVISION = '22244de5a79bd1d6d623c32e72bf1954b56235be'  # v1.6.1, as build_deps.py


def run(command):
    print(' '.join(map(str, command)), flush=True)
    subprocess.run([str(x) for x in command], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'build', 'sdk', 'toolchain', 'cmake', 'ninja'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1: parser.error('--jobs must be positive')
    source, build, sdk, tools, cmake, ninja = (p.resolve() for p in
        (args.source, args.build, args.sdk, args.toolchain, args.cmake, args.ninja))
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != OPUS_REVISION: raise ValueError(f'Opus must be checked out at {OPUS_REVISION}')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        raise ValueError('Opus source has local changes')
    build.mkdir(parents=True, exist_ok=True)
    # Generic avoids CMake's macOS-only xcrun discovery. Apple arm64 always has NEON; Opus 1.6.1 needs
    # MAY_HAVE declarations along with PRESUME when runtime feature probing is disabled for this target.
    run([cmake, '-S', source, '-B', build, '-G', 'Ninja', '-DCMAKE_SYSTEM_NAME=Generic',
         '-DCMAKE_SYSTEM_PROCESSOR=arm64', f'-DCMAKE_C_COMPILER={tools / "clang.exe"}',
         '-DCMAKE_C_COMPILER_TARGET=arm64-apple-ios26.0', f'-DCMAKE_SYSROOT={sdk}',
         f'-DCMAKE_AR={tools / "llvm-ar.exe"}', f'-DCMAKE_RANLIB={tools / "llvm-ranlib.exe"}',
         f'-DCMAKE_MAKE_PROGRAM={ninja}', '-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY',
         '-DCMAKE_BUILD_TYPE=Release', '-DOPUS_BUILD_SHARED_LIBRARY=OFF', '-DOPUS_BUILD_TESTING=OFF',
         '-DOPUS_BUILD_PROGRAMS=OFF', '-DOPUS_INSTALL_PKG_CONFIG_MODULE=OFF',
         '-DOPUS_MAY_HAVE_NEON=OFF', '-DOPUS_PRESUME_NEON=ON',
         '-DCMAKE_C_FLAGS=-DOPUS_ARM_MAY_HAVE_NEON -DOPUS_ARM_MAY_HAVE_NEON_INTR'])
    run([cmake, '--build', build, '--parallel', str(args.jobs)])
    if not (build / 'libopus.a').is_file(): raise RuntimeError('Opus archive was not produced')
    print(f'Opus archive: {build / "libopus.a"}; headers: {source / "include"}')


if __name__ == '__main__':
    main()
