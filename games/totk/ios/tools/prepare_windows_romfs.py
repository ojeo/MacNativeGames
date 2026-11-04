#!/usr/bin/env python3
"""Validate and index a raw RomFS extracted by the Windows LibHac tool."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'games/totk/scripts'))
from build_app import VERSIONS  # noqa: E402
from extract_romfs import index_romfs  # noqa: E402


def prepare(folder, version):
    image = folder / 'romfs.bin'
    expected = VERSIONS[version]['romfs']
    if image.stat().st_size != expected['size']:
        raise ValueError('RomFS size does not match the supported game version')
    with image.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != expected['sha256']:
        raise ValueError('RomFS SHA-256 does not match the supported game version')
    files = index_romfs(image)
    report = dict(status='pass', romfs_size=expected['size'], romfs_sha256=digest, files=files,
                  integrity='Exact supported RomFS SHA-256')
    # Never publish a partial index if parsing or writing fails.
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=folder, prefix='index-', suffix='.tmp', delete=False) as f:
        temporary = Path(f.name)
        try:
            json.dump(report, f, indent=2)
            f.write('\n')
        except BaseException:
            f.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, folder / 'index.json')
    finally:
        temporary.unlink(missing_ok=True)
    print(f'validated {version} RomFS: {len(files)} files, SHA-256 {digest}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--version', required=True, choices=('v0', 'v112', 'v121', 'v143'))
    args = parser.parse_args()
    prepare(args.folder.resolve(), args.version)


if __name__ == '__main__':
    main()
