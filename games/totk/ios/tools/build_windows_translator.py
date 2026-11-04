#!/usr/bin/env python3
"""Build the game's Windows shader service and its pinned SPIRV-Cross.

The output and temporary sources belong in a game work directory, not the repository.
The SPIRV-Cross checkout must already be at the revision pinned by build_app.py.
Requires .NET 10, git, and a Windows C++ compiler (for example LLVM-MinGW).
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[4]


def file_hash(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_hash(root, ignored=()):
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in ignored for part in relative.parts): continue
        name = relative.as_posix().encode('utf-8')
        digest.update(len(name).to_bytes(4, 'little')); digest.update(name)
        digest.update(bytes.fromhex(file_hash(path)))
    return digest.hexdigest()


def run(command, **kwargs):
    print(' '.join(map(str, command)), flush=True)
    subprocess.run([str(x) for x in command], check=True, **kwargs)


def pins():
    tree = ast.parse((REPO / 'build_app.py').read_text(encoding='utf-8'))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ('SPIRV_CROSS', 'SPIRV_CROSS_SOURCES'):
                values[name] = ast.literal_eval(node.value)
    return values['SPIRV_CROSS'][1], values['SPIRV_CROSS_SOURCES']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('out', 'dotnet', 'cxx', 'spirv-source'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    out, dotnet, cxx, source = (p.resolve() for p in (args.out, args.dotnet, args.cxx, args.spirv_source))
    revision, sources = pins()
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != revision:
        raise ValueError(f'SPIRV-Cross checkout must be {revision}, got {actual}')
    # Dirty source would make the revision insufficient to identify the compiler.
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        raise ValueError('SPIRV-Cross checkout has local changes')
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, DOTNET_ROOT=str(dotnet.parent), DOTNET_CLI_HOME=str(out / 'dotnet-home'),
               NUGET_PACKAGES=str(out / 'nuget'), DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_NOLOGO='1')
    identity = {'schema': 1, 'ryujinx': source_hash(REPO / 'vendor/ryujinx', ('.git', 'bin', 'obj')),
                'service': source_hash(REPO / 'games/totk/tools/totk_xlate'), 'spirv_revision': revision,
                'spirv_sources': list(sources), 'dotnet': file_hash(dotnet),
                'dotnet_version': subprocess.check_output([str(dotnet), '--version'], text=True, env=env).strip(),
                'cxx': file_hash(cxx), 'cxx_version': subprocess.check_output([str(cxx), '--version'], text=True).splitlines()[0],
                'builder': file_hash(Path(__file__))}
    stamp = out / 'windows-translator.json'
    try:
        saved = json.loads(stamp.read_text(encoding='utf-8'))
        if saved.get('identity') == identity and all(
                (out/name).is_file() and file_hash(out/name) == saved['outputs'][name]
                for name in ('totk_xlate.exe', 'spirv-cross.exe')):
            print(f'reusing verified Windows shader translator: {out}')
            return
    except (OSError, ValueError, KeyError, TypeError):
        pass
    with tempfile.TemporaryDirectory(prefix='translator-build-', dir=out) as temp:
        temp = Path(temp)
        ryujinx = temp / 'ryujinx'
        shutil.copytree(REPO / 'vendor/ryujinx', ryujinx,
                        ignore=shutil.ignore_patterns('.git', 'bin', 'obj'))
        xlate = temp / 'xlate'
        shutil.copytree(REPO / 'games/totk/tools/totk_xlate', xlate)
        for patch in sorted((xlate / 'patches').glob('*.patch')):
            run(['git', '-C', ryujinx, 'apply', '--whitespace=nowarn', patch])
        run([dotnet, 'publish', xlate / 'totk_xlate.csproj', '-c', 'Release', '-r', 'win-x64',
             '--self-contained', 'false', '-p:PublishSingleFile=true', f'-p:RyuSrc={ryujinx}',
             '-o', temp / 'publish'], env=env)
        run([cxx, '-O2', '-DNDEBUG', '-std=c++11', '-Wno-deprecated-declarations', '-static',
             *(source / name for name in sources), '-o', temp / 'spirv-cross.exe'])
        # A single-file service keeps the seed cache's executable hash meaningful.
        os.replace(temp / 'publish/totk_xlate.exe', out / 'totk_xlate.exe')
        os.replace(temp / 'spirv-cross.exe', out / 'spirv-cross.exe')
        result = {'identity': identity, 'outputs': {n: file_hash(out/n) for n in ('totk_xlate.exe', 'spirv-cross.exe')}}
        staged = temp / 'windows-translator.json'
        staged.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        os.replace(staged, stamp)
    print('Set DOTNET_ROOT to the .NET 10 runtime and TOTK_XLATE_SPIRV_CROSS=process when preparing the seed.')


if __name__ == '__main__':
    main()
