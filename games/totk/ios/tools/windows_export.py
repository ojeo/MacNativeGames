#!/usr/bin/env python3
"""Export v143 iOS code sections with the production patcher on Windows.

Inputs must match the repository's verified rewrites. The generated sections
are game content and must remain in the game's work folder.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
GAME = ROOT / 'games/totk'
sys.path.insert(0, str(ROOT))
from build_app import VERSIONS  # noqa: E402

# Layout from the verified 1.4.3 rewrites. Do not carry these offsets to another build.
LAYOUT = {
    'main': (0x2bb9c00, 0x2bba000, 0x3569000, 0x3af0000),
    'sdk': (0x663700, 0x664000, 0xb30000, 0xc60000),
    'subsdk0': (0x356d00, 0x357000, 0x522000, 0x670000),
}


def validate_images(rewritten):
    expected = VERSIONS['v143']['rewritten_sha256']
    for name, layout in LAYOUT.items():
        path = rewritten / f'{name}.patched.bin'
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != expected[path.name]: raise ValueError(f'{name}: unsupported rewritten image')
        fields = {}
        for line in (rewritten / f'{name}.fixups.tsv').read_text(encoding='utf-8').splitlines():
            if not line.startswith('# '): continue
            parts = line[2:].split()
            if len(parts) == 2:
                if parts[0] in fields: raise ValueError(f'{name}: duplicate rewrite layout field {parts[0]}')
                fields[parts[0]] = parts[1]
        try: actual = tuple(int(fields[k], 16) for k in ('TEXT_END', 'RO_OFF', 'DATA_OFF', 'PATCH_OFF'))
        except (KeyError, ValueError) as e: raise ValueError(f'{name}: missing rewrite layout') from e
        if actual != layout: raise ValueError(f'{name}: rewrite layout does not match v143')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rewritten', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--clang', type=Path, required=True, help='Windows x86-64 clang (LLVM-MinGW)')
    args = parser.parse_args()
    rewritten, out, clang = args.rewritten.resolve(), args.out.resolve(), args.clang.resolve()
    validate_images(rewritten)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='export-', dir=out) as tmp:
        tmp = Path(tmp)
        # Windows Git may check out the zeldaVR symlink as a text file. Materialize the source tree in the work folder.
        shutil.copytree(GAME / 'runtime', tmp / 'runtime')
        (tmp / 'zeldaVR/runtime').mkdir(parents=True)
        shutil.copyfile(ROOT / 'zeldaVR/runtime/vr_camera.h', tmp / 'zeldaVR/runtime/vr_camera.h')
        (tmp / 'runtime/TargetConditionals.h').write_text('#define TARGET_OS_IPHONE 0\n', encoding='ascii')
        exe = tmp / 'export.exe'
        subprocess.run([str(clang), '-O2', '-static', '-municode', '-DTOTK_OFFLINE_EXPORT',
                        '-DTOTK_GAME_V143=1', '-Dsigjmp_buf=jmp_buf', '-I', str(tmp / 'runtime'),
                        str(tmp / 'runtime/game_patches_v143.c'), str(GAME / 'ios/tools/windows_export.c'),
                        '-o', str(exe)], check=True)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith('TOTK_')}
        env.update(TOTK_EXPORT_IOS='1', TOTK_RENDER_RES='1280x720')
        name = 'main'
        subprocess.run([str(exe), str(rewritten / f'{name}.patched.bin'), str(tmp / f'{name}.x0.bin'),
                        str(tmp / f'{name}.x1.bin'), *(hex(x) for x in LAYOUT[name])], check=True, env=env)
        # Compile the same production patcher in its iOS verification mode and replay the exported words through it.
        (tmp / 'runtime/TargetConditionals.h').write_text('#define TARGET_OS_IPHONE 1\n', encoding='ascii')
        verifier = tmp / 'verify.exe'
        subprocess.run([str(clang), '-O2', '-static', '-municode', '-DTOTK_VERIFY_IOS', '-DTOTK_GAME_V143=1',
                        '-Dsigjmp_buf=jmp_buf', '-I', str(tmp / 'runtime'),
                        str(tmp / 'runtime/game_patches_v143.c'), str(GAME / 'ios/tools/windows_export.c'),
                        '-o', str(verifier)], check=True)
        verify_env = {k: v for k, v in env.items() if k != 'TOTK_EXPORT_IOS'}
        verify_cmd = [str(verifier), str(rewritten / f'{name}.patched.bin'), str(tmp / f'{name}.x0.bin'),
                      str(tmp / f'{name}.x1.bin'), *(hex(x) for x in LAYOUT[name])]
        checked = subprocess.run(verify_cmd, check=True, env=verify_env, capture_output=True)
        if b'cheat probes installed: mask 0x7' not in checked.stderr:
            raise ValueError('iOS cheat veneer verification did not accept all three probes')
        # A negative control proves the verifier is actually checking the exported code rather than just launching.
        x0 = tmp / f'{name}.x0.bin'
        with x0.open('r+b') as f:
            f.seek(0x2db204); original = f.read(1); f.seek(0x2db204); f.write(bytes([original[0] ^ 1]))
        try:
            negative = subprocess.run(verify_cmd, env=verify_env, capture_output=True)
            if negative.returncode == 0 or b'embedded FPS patch mismatch' not in negative.stderr:
                raise ValueError('iOS patch verification did not reject a corrupted controller instruction')
        finally:
            with x0.open('r+b') as f: f.seek(0x2db204); f.write(original)
        # An absent probe leaves the original instruction and does not disable the other probes.
        x1 = tmp / 'main.x1.bin'
        for offset, original_word, expected_mask in ((0x4407d0, 0xf9400008, b'0x6'),
                                                       (0x782274, 0x35001738, b'0x5'),
                                                       (0x31d398, 0x1f080800, b'0x3')):
            with x0.open('r+b') as f:
                f.seek(offset); original = f.read(4); f.seek(offset); f.write(original_word.to_bytes(4, 'little'))
            try:
                negative = subprocess.run(verify_cmd, env=verify_env, capture_output=True)
                if negative.returncode or b'cheat probes installed: mask ' + expected_mask not in negative.stderr:
                    raise ValueError('iOS cheat verifier did not isolate the absent probe')
            finally:
                with x0.open('r+b') as f: f.seek(offset); f.write(original)
        # A live branch into damaged signed code cannot be repaired on iOS; stop before guest execution.
        offset = ((rewritten / 'main.patched.bin').stat().st_size + 15 & ~15) + 1024 - LAYOUT['main'][3]
        with x1.open('r+b') as f:
            f.seek(offset); original = f.read(1); f.seek(offset); f.write(bytes([original[0] ^ 1]))
        try:
            negative = subprocess.run(verify_cmd, env=verify_env, capture_output=True)
            if negative.returncode == 0 or b'embedded cheat probe mismatch' not in negative.stderr:
                raise ValueError('iOS cheat verifier did not reject a damaged live veneer')
        finally:
            with x1.open('r+b') as f: f.seek(offset); f.write(original)
        for name in ('sdk', 'subsdk0'):
            image = (rewritten / f'{name}.patched.bin').read_bytes()
            text, _, _, patch = LAYOUT[name]
            up = lambda n: (n + 0x3fff) & ~0x3fff
            if up(text) > patch or patch > len(image): raise ValueError(f'{name}: invalid section boundaries')
            (tmp / f'{name}.x0.bin').write_bytes(image[:up(text)].ljust(up(text), b'\0'))
            (tmp / f'{name}.x1.bin').write_bytes(image[patch:].ljust(up(len(image))-patch, b'\0'))
        for name in LAYOUT:
            for part in ('x0', 'x1'):
                os.replace(tmp / f'{name}.{part}.bin', out / f'{name}.{part}.bin')
    print(f'verified v143 executable sections: {out}')


if __name__ == '__main__':
    main()
