#!/usr/bin/env python3
"""Link and validate the unsigned v143 iOS Mach-O using Windows-hosted LLD."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile


def layout(data):
    if len(data) < 32 or struct.unpack_from('<II', data) != (0xfeedfacf, 0x100000c):
        raise ValueError('expected ARM64 Mach-O')
    count, size = struct.unpack_from('<II', data, 16)
    if size > len(data)-32: raise ValueError('invalid Mach-O load command size')
    pos, sections, segments, platforms, signed = 32, {}, {}, [], False
    for _ in range(count):
        if pos + 8 > 32 + size: raise ValueError('truncated Mach-O command')
        cmd, length = struct.unpack_from('<II', data, pos)
        if length < 8 or pos + length > 32 + size: raise ValueError('invalid Mach-O command')
        if cmd == 0x19:
            if length < 72: raise ValueError('invalid Mach-O segment')
            name = data[pos+8:pos+24].split(b'\0')[0].decode('ascii')
            maximum, initial, nsects = struct.unpack_from('<III', data, pos+56)
            if 72 + 80*nsects > length: raise ValueError('invalid Mach-O section table')
            segments[name] = (maximum, initial)
            for i in range(nsects):
                off = pos+72+80*i
                section = data[off:off+16].split(b'\0')[0].decode('ascii')
                segment = data[off+16:off+32].split(b'\0')[0].decode('ascii')
                _, length_bytes, file_offset = struct.unpack_from('<QQI', data, off+32)
                flags = struct.unpack_from('<I', data, off+64)[0]
                if flags & 0xff not in (1, 0xc, 0x12) and file_offset + length_bytes > len(data):
                    raise ValueError('Mach-O section outside file')
                sections[(segment, section)] = (file_offset, length_bytes)
        elif cmd == 0x32: platforms.append(struct.unpack_from('<I', data, pos+8)[0])
        elif cmd == 0x1d: signed = True
        pos += length
    return sections, segments, platforms, signed


def checked_weak_imports(data, names):
    """Check that the two optional Mac-only hooks really are weak references in each object."""
    count = struct.unpack_from('<I', data, 16)[0]
    pos, found = 32, set()
    for _ in range(count):
        cmd, size = struct.unpack_from('<II', data, pos)
        if cmd == 2:  # LC_SYMTAB and nlist_64
            symoff, nsyms, stroff, strsize = struct.unpack_from('<IIII', data, pos+8)
            if symoff + nsyms*16 > len(data) or stroff + strsize > len(data): raise ValueError('invalid symbol table')
            for i in range(nsyms):
                string_index, kind, _, desc, value = struct.unpack_from('<IBBHQ', data, symoff + i*16)
                if not string_index or string_index >= strsize or kind & 0x0e or value: continue
                start = stroff + string_index; end = data.find(b'\0', start, stroff + strsize)
                if end < 0: raise ValueError('unterminated symbol name')
                name = data[start:end].decode('utf-8')
                if name in names:
                    if not desc & 0x40: raise ValueError(f'optional import is no longer weak: {name}')
                    found.add(name)
        pos += size
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('lld', 'sdk', 'objects', 'embed', 'opus', 'vpx', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    lld, sdk, objects, embed, opus, vpx, out = (p.resolve() for p in
        (args.lld, args.sdk, args.objects, args.embed, args.opus, args.vpx, args.out))
    inventory = json.loads((objects / 'inventory.json').read_text(encoding='utf-8'))
    if not inventory: raise ValueError('empty source inventory')
    inputs = []
    optional = {'_runtime_camera_distance_set', '_runtime_vr_find_head'}
    weak = set()
    for entry in inventory:
        path = Path(entry['object'])
        if entry['exit_code'] or path.parent != objects / 'objects': raise ValueError('invalid object inventory')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']: raise ValueError(f'object changed: {path}')
        layout(data)
        weak.update(checked_weak_imports(data, optional))
        inputs.append(path)
    if weak != optional: raise ValueError('expected weak-import evidence is missing')
    embed_data = embed.read_bytes()
    sections, _, _, _ = layout(embed_data)
    expected = {(f'__TOTK{name}W', '__img') for name in ('main', 'subsdk0', 'sdk')} | \
               {('__TOTKX', f'__{name}{part}') for name in ('main', 'subsdk0', 'sdk') for part in ('x0', 'x1')}
    if not expected.issubset(sections): raise ValueError('embed object lacks game sections')
    sdk_version = json.loads((sdk / 'SDKSettings.json').read_text(encoding='utf-8'))['Version']
    out.parent.mkdir(parents=True, exist_ok=True)
    frameworks = ('UIKit', 'Metal', 'MetalFX', 'Foundation', 'QuartzCore', 'ImageIO', 'CoreGraphics', 'CoreText',
                  'UniformTypeIdentifiers', 'CoreFoundation', 'AudioToolbox', 'GameController', 'CoreHaptics',
                  'CoreMotion', 'AVFAudio', 'Security')
    with tempfile.TemporaryDirectory(prefix='ios-link-', dir=out.parent) as tmp:
        tmp = Path(tmp); executable = tmp / 'TOTK'
        command = ['-arch', 'arm64', '-platform_version', 'ios', '26.0', str(sdk_version), '--error-limit=0',
                   '-syslibroot', str(sdk), '-F', str(sdk / 'System/Library/Frameworks'),
                   '-F', str(sdk / 'System/Library/SubFrameworks'), '-L', str(sdk / 'usr/lib'),
                   '-e', '_main', '-no_adhoc_codesign',
                   '-U', '_runtime_camera_distance_set', '-U', '_runtime_vr_find_head', '-o', str(executable)]
        for name in ('main', 'subsdk0', 'sdk'): command += ['-segprot', f'__TOTK{name}W', 'rw', 'rw']
        command += ['-segprot', '__TOTKX', 'r-x', 'r-x', *map(str, inputs), str(embed), str(opus), str(vpx),
                    '-lSystem', '-lobjc']
        for framework in frameworks: command += ['-framework', framework]
        rsp = tmp / 'link.rsp'
        rsp.write_text('\n'.join('"'+s.replace('\\', '/').replace('"', '\\"')+'"' for s in command)+'\n', encoding='utf-8')
        result = subprocess.run([str(lld), '-flavor', 'darwin', '@'+str(rsp)], capture_output=True, text=True, encoding='utf-8', errors='replace')
        (out.parent / 'link.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode: raise RuntimeError(f'link failed; see {out.parent / "link.log"}')
        data = executable.read_bytes()
        if struct.unpack_from('<I', data, 12)[0] != 2: raise ValueError('link output is not an executable')
        actual, segments, platforms, signed = layout(data)
        if platforms != [2] or signed: raise ValueError('link output is not unsigned iOS')
        for segment in ('__TOTKX', '__TOTKmainW', '__TOTKsubsdk0W', '__TOTKsdkW'):
            expected_permissions = (5, 5) if segment == '__TOTKX' else (3, 3)
            if segments.get(segment) != expected_permissions: raise ValueError(f'incorrect segment permissions: {segment}')
        for key in expected:
            source_offset, length = sections[key]
            if key not in actual: raise ValueError(f'embedded section missing: {key}')
            offset, got = actual[key]
            if length != got or embed_data[source_offset:source_offset+length] != data[offset:offset+got]:
                raise ValueError(f'embedded section changed: {key}')
        os.replace(executable, out)
    print(f'unsigned iOS executable verified: {out}')


if __name__ == '__main__':
    main()
