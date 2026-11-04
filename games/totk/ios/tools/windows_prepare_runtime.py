#!/usr/bin/env python3
"""Prepare v143 runtime tables from hash-verified Windows extraction and rewrites."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
GAME = ROOT / 'games/totk'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(GAME / 'ios/tools'))
sys.path.insert(0, str(GAME / 'scripts'))
from build_app import OUTPUT_SIZES, VERSIONS, font_report  # noqa: E402
from extract_romfs import index_romfs  # noqa: E402
from windows_export import validate_images  # noqa: E402


def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('exefs', 'rewritten', 'fonts', 'romfs', 'tree'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    exefs, rewritten, fonts, romfs, tree = (p.resolve() for p in
        (args.exefs, args.rewritten, args.fonts, args.romfs, args.tree))
    expected = VERSIONS['v143']['exefs_sha256']
    for name in ('main', 'rtld', 'sdk', 'subsdk0'):
        if sha(exefs / name) != expected[name]: raise ValueError(f'{name}: unsupported ExeFS image')
    validate_images(rewritten)
    font_manifest = font_report(fonts)
    manifest = json.loads((romfs / 'index.json').read_text(encoding='utf-8'))
    want = VERSIONS['v143']['romfs']
    if (manifest.get('status') != 'pass' or manifest.get('romfs_sha256') != want['sha256'] or
            manifest.get('romfs_size') != want['size'] or (romfs / 'romfs.bin').stat().st_size != want['size']):
        raise ValueError('RomFS was not indexed as the verified v143 image')
    if sha(romfs / 'romfs.bin') != want['sha256']: raise ValueError('RomFS bytes changed after indexing')
    if manifest.get('files') != index_romfs(romfs / 'romfs.bin'): raise ValueError('RomFS index does not match the verified image')
    dest_exefs = tree / 'extracted/v143/exefs'; dest_rewritten = tree / 'rewritten/v143'
    dest_fonts = tree / 'extracted/firmware/shared-fonts'
    for dest in (dest_exefs, dest_rewritten, dest_fonts): dest.mkdir(parents=True, exist_ok=True)
    for name in ('main', 'rtld', 'sdk', 'subsdk0'): shutil.copy2(exefs / name, dest_exefs / name)
    for source in rewritten.iterdir():
        if source.is_file(): shutil.copy2(source, dest_rewritten / source.name)
    for row in font_manifest['fonts']:
        name = f"{row['type']}-{row['name']}.bfttf"
        shutil.copy2(fonts / name, dest_fonts / name)
    (dest_fonts / 'manifest.json').write_text(json.dumps(font_manifest, indent=2) + '\n', encoding='utf-8')
    report = {'status': 'pass', 'rom_version': 'v143', 'scope': 'exact supported ExeFS and rewritten image hashes',
              'module_file_sha256': {**{f'extracted/v143/exefs/{n}': expected[n] for n in ('main', 'sdk', 'subsdk0')},
                                     **{f'rewritten/v143/{n}.patched.bin': VERSIONS['v143']['rewritten_sha256'][f'{n}.patched.bin']
                                        for n in ('main', 'sdk', 'subsdk0')}}}
    analysis = tree / 'analysis/v143-port'; analysis.mkdir(parents=True, exist_ok=True)
    (analysis / 'phase12-validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    def run(script, *arguments):
        subprocess.run([sys.executable, str(GAME / 'scripts' / script), *map(str, arguments)], check=True)
    run('prepare_modules.py', dest_exefs, '--output', tree / 'extracted/v143/elf')
    run('prepare_runtime.py', '--version', 'v143', '--tree', tree)
    run('prepare_shared_fonts.py', '--version', 'v143', '--tree', tree)
    run('prepare_romfs_backend.py', '--version', 'v143', '--romfs-dir', romfs,
        '--output-dir', tree / 'build/game-data/v143')
    run('make_romfs_patches.py', '--version', 'v143', '--romfs-dir', romfs,
        '--output-dir', tree / 'extracted/v143/romfs-patches')
    overlay = tree / 'extracted/v143/romfs-patches-out'
    for size in OUTPUT_SIZES:
        run('make_output_res_overlay.py', size, '--version', 'v143', '--romfs-dir', romfs, '--output-root', overlay)
    for canvas in ('1920x1080', *OUTPUT_SIZES):
        for scene in ('1920x1080', *OUTPUT_SIZES):
            run('make_output_res_overlay.py', canvas, '--scene', scene, '--version', 'v143', '--romfs-dir', romfs,
                '--output-root', overlay)
    print(f'runtime data: {tree / "build/game-data/v143"}')


if __name__ == '__main__':
    main()
