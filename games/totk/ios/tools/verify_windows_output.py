#!/usr/bin/env python3
"""Verify a Windows-built IPA and external GameData without signing or installing them."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import plistlib
import re
import struct
import sys
import zipfile

from windows_link import layout
from windows_pack_ipa import is_runtime_metadata_path
from windows_prepare_resources import PackReader, SEED_FILE, sha, shader_chain

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from build_app import VERSIONS  # noqa: E402


def verify_pack(folder, marker):
    marker_bytes = marker.read_bytes()
    if b'\r' in marker_bytes or not marker_bytes.endswith(b'\n'):
        raise ValueError('shader seed marker must use LF line endings')
    lines = marker_bytes.decode('ascii').splitlines()
    if len(lines) != 2 or not re.fullmatch(r'shader-seed-[0-9a-f]{12}-windows', lines[0]) or not re.fullmatch(r'[0-9a-f]{64}', lines[1]):
        raise ValueError('invalid shader seed marker')
    name, fingerprint = lines
    parts = sorted(folder.glob(name + '.pack.*'))
    if not parts or any(p.name != f'{name}.pack.{i:03d}' for i, p in enumerate(parts)):
        raise ValueError('shader pack parts are missing or not consecutive')
    stream = PackReader(parts)
    def take(n):
        data = stream.read(n)
        if len(data) != n: raise ValueError('truncated shader pack')
        return data
    metadata_names = {'seed-manifest.json', 'shader_map.tsv', 'pso_list.tsv', 'pso_title.tsv', 'fingerprint.txt'}
    hashes, metadata, previous = {}, {}, ''
    try:
        if take(9) != b'TOTKPACK1': raise ValueError('invalid shader pack header')
        while True:
            name_length = struct.unpack('<H', take(2))[0]
            if not name_length: break
            if name_length >= 256: raise ValueError('invalid shader pack name length')
            item = take(name_length).decode('utf-8')
            if item <= previous or not (SEED_FILE.fullmatch(item) or item in metadata_names):
                raise ValueError('unsafe, duplicate or unordered shader pack entry')
            previous = item
            remaining = struct.unpack('<Q', take(8))[0]
            if item in metadata_names and remaining > 64 << 20: raise ValueError('oversized seed metadata')
            digest = hashlib.sha256(); retained = bytearray() if item in metadata_names else None
            while remaining:
                chunk = take(min(remaining, 4 << 20)); digest.update(chunk); remaining -= len(chunk)
                if retained is not None: retained.extend(chunk)
            hashes[item] = digest.hexdigest()
            if retained is not None: metadata[item] = bytes(retained)
            if len(hashes) % 10000 == 0: print(f'checked {len(hashes)} packed shader files', flush=True)
        if stream.read(1): raise ValueError('trailing shader pack bytes')
    finally:
        stream.close()
    if set(metadata) != metadata_names: raise ValueError('shader pack metadata is incomplete')
    if metadata['shader_map.tsv'].splitlines()[:1] != [b'# TOTK control-code-sha256-v1']:
        raise ValueError('shader map schema is invalid')
    manifest = json.loads(metadata['seed-manifest.json'])
    if (manifest.get('schema') != 1 or manifest.get('version') != 'v143' or manifest.get('chain') != shader_chain() or not manifest.get('shaders') or
            manifest.get('source_romfs_sha256') != VERSIONS['v143']['romfs']['sha256']):
        raise ValueError('shader seed identity is invalid')
    files = manifest.get('files')
    if not isinstance(files, dict) or set(hashes) != set(files) | metadata_names:
        raise ValueError('shader seed manifest and pack entries differ')
    for item, digest in files.items():
        if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest) or hashes.get(item) != digest:
            raise ValueError(f'shader pack hash differs: {item}')
    shaders = [item for item in files if item.endswith('_b.metal')]
    if (not shaders or manifest.get('ios_metallibs') != len(shaders) or
            any(item.removesuffix('.metal') + '.metallib' not in files for item in shaders)):
        raise ValueError('device shader libraries are incomplete')
    calculated = hashlib.sha256(b''.join(metadata[n] for n in ('seed-manifest.json', 'shader_map.tsv', 'pso_list.tsv', 'pso_title.tsv'))).hexdigest()
    if calculated != fingerprint or metadata['fingerprint.txt'].decode('ascii').strip() != fingerprint:
        raise ValueError('shader pack fingerprint differs')
    return {'files': len(hashes), 'parts': len(parts), 'fingerprint': fingerprint,
            'metallibs': manifest.get('ios_metallibs'), 'skipped': len(manifest.get('skipped', []))}


def verify_runtime_text(z):
    prefix = 'Payload/TOTK.app/GameData/'
    for name in z.namelist():
        if name.startswith(prefix) and is_runtime_metadata_path(PurePosixPath(name[len(prefix):])):
            if b'\r' in z.read(name): raise ValueError(f'non-LF runtime metadata: {name}')


def verify_ipa(ipa):
    with zipfile.ZipFile(ipa) as z:
        bad = z.testzip()
        if bad: raise ValueError(f'IPA CRC failed: {bad}')
        names = z.namelist(); root = 'Payload/TOTK.app/'
        verify_runtime_text(z)
        if len(names) != len(set(names)) or any(n.startswith('/') or '..' in n.split('/') for n in names):
            raise ValueError('unsafe or duplicate IPA entry')
        if any(n.endswith('/romfs.bin') or '/shader-seed/' in n for n in names):
            raise ValueError('external resources are inside IPA')
        info = plistlib.loads(z.read(root+'Info.plist'))
        if (info.get('CFBundleExecutable') != 'TOTK' or not info.get('UIFileSharingEnabled') or
                info.get('MinimumOSVersion') != '26.0'):
            raise ValueError('IPA identity or file-sharing settings are invalid')
        entry = z.getinfo(root+'TOTK')
        if entry.external_attr >> 16 & 0o777 != 0o755: raise ValueError('executable permissions are invalid')
        binary = z.read(root+'TOTK')
        if shader_chain().encode('utf-8') + b'\0' not in binary:
            raise ValueError('IPA shader chain does not match the current runtime')
        sections, segments, platforms, signed = layout(binary)
        required = {(f'__TOTK{n}W', '__img') for n in ('main', 'subsdk0', 'sdk')} | {
            ('__TOTKX', f'__{n}{part}') for n in ('main', 'subsdk0', 'sdk') for part in ('x0', 'x1')}
        if platforms != [2] or signed or segments.get('__TOTKX') != (5, 5) or not required.issubset(sections):
            raise ValueError('IPA executable is not the expected unsigned iOS binary')
        if any(segments.get(f'__TOTK{n}W') != (3, 3) for n in ('main', 'subsdk0', 'sdk')):
            raise ValueError('game data segment permissions are invalid')
        data = root+'GameData/'
        config = dict(line.split() for line in z.read(data+'game-data/romfs-config.txt').decode().splitlines())
        expected = VERSIONS['v143']['romfs']
        if (config.get('ROMFS_IMAGE_SHA256') != expected['sha256'] or config.get('ROMFS_IMAGE_SIZE') != str(expected['size']) or
                config.get('ROMFS_INDEX_SHA256') != hashlib.sha256(z.read(data+'romfs/runtime-index.bin')).hexdigest()):
            raise ValueError('IPA RomFS configuration or index differs')
        fonts = dict(line.split() for line in z.read(data+'game-data/shared-fonts.txt').decode().splitlines())
        for i in range(6):
            name = fonts[f'FONT{i}_FILE']
            if Path(name).name != name: raise ValueError('unsafe font name')
            content = z.read(data+'shared-fonts/'+name)
            if len(content) != int(fonts[f'FONT{i}_FILE_BYTES']) or hashlib.sha256(content).hexdigest() != fonts[f'FONT{i}_SHA256']:
                raise ValueError(f'IPA font differs: {name}')
        if not z.read(data+'game-data/runtime-tables.bin'): raise ValueError('empty runtime tables')
        return {'entries': len(names), 'bundle_id': info['CFBundleIdentifier'], 'executable_sha256': hashlib.sha256(binary).hexdigest()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ipa', type=Path, required=True); p.add_argument('--game-data', type=Path, required=True)
    p.add_argument('--report', type=Path)
    a = p.parse_args(); folder = a.game_data.resolve()
    ipa = verify_ipa(a.ipa.resolve())
    expected = VERSIONS['v143']['romfs']; image = folder/'romfs.bin'
    if (image.stat().st_size != expected['size'] or sha(image) != expected['sha256'] or
            (folder/'romfs.sha256').read_text(encoding='ascii').strip() != expected['sha256']):
        raise ValueError('external RomFS or its marker differs')
    shaders = verify_pack(folder, folder/'shader-seed.txt')
    report = {'status': 'pass', 'scope': 'artifact integrity and resource separation; no device execution',
              'ipa': ipa, 'romfs_bytes': expected['size'], 'romfs_sha256': expected['sha256'], 'shaders': shaders}
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
