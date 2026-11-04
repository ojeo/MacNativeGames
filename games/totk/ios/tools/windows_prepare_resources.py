#!/usr/bin/env python3
"""Prepare the external iOS GameData folder after all device metallibs are built."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

from build_ipa import seed_fingerprint
from compile_seed import METAL_FLAGS
from install_device import write_pack

ROOT = Path(__file__).resolve().parents[4]
GAME = ROOT / 'games/totk'
sys.path.insert(0, str(ROOT))
from build_app import VERSIONS  # noqa: E402

SEED_FILE = re.compile(r'^(?:[0-9a-f]{64}\.variants|[0-9a-f]{64}-[0-9a-f]{12}_b\.(?:metal|json|metallib)|pso_manifest\.tsv|shader-keys\.json)$')


def shader_chain():
    header = (GAME / 'third_party/d2r_gfx/gfx/nvn/dmsh_chain.h').read_text(encoding='utf-8')
    match = re.search(r'^#define\s+DMSH_CHAIN\s+"([^"]+)"\s*$', header, re.MULTILINE)
    if not match: raise ValueError('runtime shader chain header is invalid')
    return match.group(1)


def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


class PackReader:
    """Read a logical stream from the ordered, size-limited pack parts."""
    def __init__(self, paths):
        self.paths = iter(paths)
        self.stream = None

    def read(self, size):
        result = bytearray()
        while len(result) < size:
            if self.stream is None:
                path = next(self.paths, None)
                if path is None: break
                self.stream = path.open('rb')
            chunk = self.stream.read(size-len(result))
            if chunk: result.extend(chunk)
            else: self.stream.close(); self.stream = None
        return bytes(result)

    def close(self):
        if self.stream is not None: self.stream.close()


def verify_pack(parts, seed, names, hashes):
    """Check the exact byte stream the iOS unpacker will consume, including part boundaries."""
    stream = PackReader(parts)
    def take(n):
        data = stream.read(n)
        if len(data) != n: raise ValueError('shader pack is truncated')
        return data
    try:
        if take(9) != b'TOTKPACK1': raise ValueError('invalid shader pack header')
        for i, expected_name in enumerate(names, 1):
            length = struct.unpack('<H', take(2))[0]
            if not length or length >= 256: raise ValueError('invalid shader pack name length')
            name = take(length).decode('utf-8')
            size = struct.unpack('<Q', take(8))[0]
            if name != expected_name or size != (seed/name).stat().st_size:
                raise ValueError(f'shader pack entry differs: {expected_name}')
            digest = hashlib.sha256()
            while size:
                chunk = take(min(size, 4 << 20)); digest.update(chunk); size -= len(chunk)
            if digest.hexdigest() != hashes[expected_name]: raise ValueError(f'shader pack hash differs: {name}')
            if i % 5000 == 0: print(f'verified {i}/{len(names)} packed shader files', flush=True)
        if take(2) != b'\0\0' or stream.read(1): raise ValueError('invalid shader pack ending')
    finally:
        stream.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('romfs', 'source-seed', 'device-seed', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    romfs, source, seed, out = (p.resolve() for p in (args.romfs, args.source_seed, args.device_seed, args.out))
    if out in (romfs, source, seed) or any(p in out.parents for p in (romfs, source, seed)):
        raise ValueError('output must be outside all input folders')
    expected = VERSIONS['v143']['romfs']
    image = romfs / 'romfs.bin'
    if image.stat().st_size != expected['size'] or sha(image) != expected['sha256']:
        raise ValueError('RomFS does not match v143')
    src_manifest = json.loads((source / 'seed-manifest.json').read_text(encoding='utf-8'))
    manifest_path = seed / 'seed-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('version') != 'v143' or manifest.get('source_romfs_sha256') != expected['sha256']:
        raise ValueError('device shader seed is not for this RomFS')
    if (manifest.get('chain') != shader_chain() or manifest.get('chain') != src_manifest.get('chain') or
            any(manifest['files'].get(k) != v for k, v in src_manifest['files'].items())):
        raise ValueError('device seed does not match the translated source seed')
    shaders = sorted(n for n in src_manifest['files'] if n.endswith('_b.metal'))
    if manifest.get('ios_metallibs') != len(shaders) or manifest.get('ios_metal_flags') != ' '.join(METAL_FLAGS):
        raise ValueError('device metallib compilation is incomplete')
    for n in shaders:
        lib = n.removesuffix('.metal') + '.metallib'
        if lib not in manifest['files']: raise ValueError(f'device metallib missing from manifest: {lib}')
    # The iOS importer validates every listed file before using the seed, including the MSL and reflection files.
    # Check them here too, before emitting a multi-gigabyte pack or its completion marker.
    files = manifest['files']
    for i, (name, digest) in enumerate(sorted(files.items()), 1):
        if (not isinstance(name, str) or not SEED_FILE.fullmatch(name) or not isinstance(digest, str) or
                not re.fullmatch('[a-f0-9]{64}', digest)):
            raise ValueError('invalid shader seed manifest entry')
        path = seed / name
        if not path.is_file() or sha(path) != digest: raise ValueError(f'shader seed file missing or changed: {name}')
        if i % 5000 == 0: print(f'checked {i}/{len(files)} shader files', flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ios-resources-', dir=out.parent) as temp:
        temp = Path(temp); lists = temp / 'lists'; lists.mkdir()
        subprocess.run([sys.executable, str(GAME / 'scripts/shader_list.py'), 'resolve', str(source),
                        str(GAME / 'assets/shader_list.tsv'), str(lists / 'pso_list.tsv'),
                        str(lists / 'pso_title.tsv')], check=True)
        (seed / 'shader_map.tsv').write_bytes(b'# TOTK control-code-sha256-v1\n')
        manifest['ios_source_manifest_sha256'] = sha(source / 'seed-manifest.json')
        manifest['ios_sdk'] = 'iphoneos'
        # Use the validated manifest, not every file in the directory: an interrupted older compile can leave .air files.
        manifest['files'] = dict(sorted(manifest['files'].items()))
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        fingerprint = seed_fingerprint(seed, lists)
        if not re.fullmatch('[a-f0-9]{64}', fingerprint): raise ValueError('invalid shader fingerprint')
        for name in ('pso_list.tsv', 'pso_title.tsv'): shutil.copyfile(lists / name, seed / name)
        (seed / 'fingerprint.txt').write_bytes((fingerprint + '\n').encode('ascii'))
        folder = f'shader-seed-{fingerprint[:12]}-windows'
        seed_names = sorted(set(manifest['files']) | {'seed-manifest.json', 'shader_map.tsv', 'fingerprint.txt',
                                                      'pso_list.tsv', 'pso_title.tsv'})
        hashes = {name: manifest['files'].get(name) or sha(seed/name) for name in seed_names}
        if out.exists():
            if not out.is_dir(): raise ValueError(f'external resource output is not a folder: {out}')
            try:
                old_marker = (out / 'shader-seed.txt').read_bytes()
                if old_marker != f'{folder}\n{fingerprint}\n'.encode('ascii'):
                    raise ValueError('existing shader marker differs or is not LF-terminated; use a new output or repair the marker')
                rom_mark = (out / 'romfs.sha256').read_text(encoding='ascii').strip()
                old_image = out / 'romfs.bin'
                parts = sorted(out.glob(folder + '.pack.*'))
                if (rom_mark != expected['sha256'] or
                        old_image.stat().st_size != expected['size'] or sha(old_image) != expected['sha256'] or
                        not parts or any(p.name != f'{folder}.pack.{i:03d}' for i, p in enumerate(parts))):
                    raise ValueError('existing external resources differ')
                verify_pack(parts, seed, seed_names, hashes)
            except (OSError, UnicodeError) as e:
                raise ValueError('existing external resources are incomplete; preserve or move the folder before retrying') from e
            print(f'reusing verified external GameData: {out}')
            return
        result = temp / 'GameData'; result.mkdir()
        parts = []
        def complete_part(path):
            parts.append(path)
            print(f'created {path.name}', flush=True)
        write_pack(seed, seed_names, result, folder, 1 << 30, complete_part)
        verify_pack(parts, seed, seed_names, hashes)
        shutil.copyfile(image, result / 'romfs.bin')
        if sha(result / 'romfs.bin') != expected['sha256']: raise ValueError('copied RomFS hash differs')
        # These files are consumed on iOS: do not let Windows translate LF to CRLF.
        (result / 'romfs.sha256').write_bytes((expected['sha256'] + '\n').encode('ascii'))
        (result / 'shader-seed.txt').write_bytes(f'{folder}\n{fingerprint}\n'.encode('ascii'))
        os.replace(result, out)
    print(f'external GameData ready: {out}; copy the marker files after their data')


if __name__ == '__main__':
    main()
