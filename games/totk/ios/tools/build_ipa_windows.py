#!/usr/bin/env python3
"""Build a v143 unsigned iOS IPA and external GameData on Windows.

The SDK, Apple Windows Metal tools and the Windows LLVM toolchain must already
be installed. Game-derived files and tool sources stay under --work.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

TOOLS = Path(__file__).resolve().parent
GAME = TOOLS.parents[1]
ROOT = GAME.parents[1]
sys.path.insert(0, str(ROOT))
from build_app import SPIRV_CROSS, VERSIONS, font_report  # noqa: E402
from build_windows_opus import OPUS_REVISION  # noqa: E402
from build_windows_vpx import REVISION as VPX_REVISION  # noqa: E402


def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def device_seed_for(source, default):
    """Reuse a matching device seed, or preserve it and create a seed for changed inputs."""
    source_manifest = json.loads((source/'seed-manifest.json').read_text(encoding='utf-8'))
    fields = ('schema', 'chain', 'version', 'game', 'source_romfs_sha256', 'files')
    if not isinstance(source_manifest.get('files'), dict) or not source_manifest['files']:
        raise ValueError(f'{source}: invalid source shader manifest')

    def matches(path):
        try:
            old = json.loads((path/'seed-manifest.json').read_text(encoding='utf-8'))
            if any(old.get(k) != source_manifest.get(k) for k in fields if k != 'files'):
                return False
            old_files = old['files']
            source_files = source_manifest['files']
            permitted = set(source_files) | {name.removesuffix('.metal')+'.metallib'
                                             for name in source_files if name.endswith('_b.metal')}
            return (isinstance(old_files, dict) and
                    all(old_files.get(k) == v for k, v in source_files.items()) and
                    set(old_files).issubset(permitted))
        except (OSError, ValueError, KeyError, TypeError):
            return False

    if default.is_dir() and matches(default):
        return default
    if not default.exists():
        target = default
    else:
        identity = {k: source_manifest.get(k) for k in fields}
        token = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]
        target = default.with_name(default.name+'-'+token)
        if target.is_dir() and matches(target):
            return target
        if target.exists():
            raise ValueError(f'{target}: existing shader seed differs; inspect it before retrying')
    partial = target.with_name(target.name+'.partial')
    if partial.exists():
        raise ValueError(f'{partial}: incomplete shader seed; inspect it before retrying')
    shutil.copytree(source, partial)
    os.replace(partial, target)
    return target


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'update', 'keys', 'firmware', 'sdk', 'toolchain', 'metal', 'dotnet', 'cmake', 'ninja', 'bash', 'make', 'work', 'out'):
        p.add_argument('--' + name, required=True, type=Path)
    p.add_argument('--jobs', type=int, default=4)
    a = p.parse_args()
    if os.name != 'nt': p.error('this builder requires Windows')
    if sys.version_info < (3, 14): p.error('Python 3.14 or newer is required')
    if a.jobs < 1: p.error('--jobs must be positive')
    base, update, keys, firmware, sdk, tc, metal, dotnet, cmake, ninja, bash, make, work, out = (
        x.resolve() for x in (a.base, a.update, a.keys, a.firmware, a.sdk, a.toolchain, a.metal, a.dotnet,
                             a.cmake, a.ninja, a.bash, a.make, a.work, a.out))
    if out.suffix.lower() != '.ipa': p.error('--out must end in .ipa')
    for path in (base, update, keys, metal, metal.with_name('metallib.exe'), dotnet, cmake, ninja, bash, make,
                 tc/'clang.exe', tc/'x86_64-w64-mingw32-clang++.exe', tc/'lld.exe', sdk/'SDKSettings.json'):
        if not path.is_file(): raise ValueError(f'required file missing: {path}')
    if not firmware.is_dir(): raise ValueError(f'firmware directory missing: {firmware}')
    import capstone, cryptography, lz4.block, PIL  # noqa: F401
    work.mkdir(parents=True, exist_ok=True)
    tmp = work / 'tmp'; tmp.mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONUTF8='1', DOTNET_ROOT=str(dotnet.parent), DOTNET_CLI_HOME=str(work/'dotnet-home'),
               NUGET_PACKAGES=str(work/'nuget'), DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_NOLOGO='1',
               TEMP=str(tmp), TMP=str(tmp), TMPDIR=str(tmp))
    env['PATH'] = str(dotnet.parent) + os.pathsep + env.get('PATH', '')
    py = Path(sys.executable)

    def run(label, command, extra=None):
        print(f'\n== {label} ==', flush=True)
        subprocess.run([str(x) for x in command], check=True, env=env | (extra or {}))

    def tool(script, *args, extra=None): run(script, [py, TOOLS/script, *args], extra)
    def checkout(name, url, revision):
        path = work / 'sources' / name
        if (path/'.git').exists():
            got = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True, env=env).strip()
            dirty = subprocess.check_output(['git', '-C', str(path), 'status', '--porcelain'], text=True, env=env).strip()
            if got != revision or dirty: raise ValueError(f'{path}: wrong revision or local changes')
            return path
        if path.exists(): raise ValueError(f'{path} exists but is not a Git checkout')
        path.mkdir(parents=True)
        run('initialise ' + name, ['git', '-C', path, 'init', '-q'])
        run('fetch ' + name, ['git', '-C', path, 'fetch', '-q', '--depth', '1', url, revision])
        run('checkout ' + name, ['git', '-C', path, 'checkout', '-q', '--detach', 'FETCH_HEAD'])
        return path

    raw = work/'raw-v143'; image = raw/'romfs.bin'
    if not image.exists():
        if raw.exists() and any(raw.iterdir()): raise ValueError(f'incomplete extraction at {raw}; inspect it before retrying')
        src = work/'nx-extract-src'
        src.mkdir(parents=True, exist_ok=True)
        for name in ('Program.cs', 'nx_extract.csproj'): shutil.copy2(TOOLS/'nx_extract'/name, src/name)
        run('build extractor', [dotnet, 'publish', src/'nx_extract.csproj', '-c', 'Release', '-o', work/'nx-extract'])
        run('extract and merge game', [work/'nx-extract/nx_extract.exe', keys, base, update, raw, '--romfs-raw'])
    tool('prepare_windows_romfs.py', raw, '--version', 'v143')
    exefs = raw/'ExeFS'
    for name in ('main', 'rtld', 'sdk', 'subsdk0'):
        if sha(exefs/name) != VERSIONS['v143']['exefs_sha256'][name]: raise ValueError(f'unsupported ExeFS: {name}')
    rewritten = work/'rewritten/v143'; rewritten.mkdir(parents=True, exist_ok=True)
    for name in ('sdk', 'subsdk0', 'main'):
        image_out = rewritten/f'{name}.patched.bin'
        expected = VERSIONS['v143']['rewritten_sha256'][image_out.name]
        if image_out.is_file() and sha(image_out) == expected: continue
        run('rewrite ' + name, [py, GAME/'third_party/d2r/patch_nso.py', exefs/name, rewritten, name],
            {'DM_RULESET': 'native', 'DM_PRIVATE_GATES': '0'})
        if sha(image_out) != expected: raise ValueError(f'{name}: rewritten hash mismatch')
    fonts = work/'shared-fonts'
    if not fonts.exists():
        run('extract shared fonts', [py, GAME/'scripts/extract_shared_fonts.py', '--keys', keys, '--firmware', firmware, '--output', fonts])
    font_report(fonts)
    tree = work/'runtime-tree'
    tool('windows_prepare_runtime.py', '--exefs', exefs, '--rewritten', rewritten, '--fonts', fonts, '--romfs', raw, '--tree', tree)
    exported = work/'export-v143'
    tool('windows_export.py', '--rewritten', rewritten, '--out', exported, '--clang', tc/'x86_64-w64-mingw32-clang.exe')
    run('generate embedded sections', [py, TOOLS/'gen_embed.py', rewritten, exported/'embed.S', '--text-dir', exported, 'main', 'subsdk0', 'sdk'])
    run('assemble embedded sections', [tc/'clang.exe', '-target', 'arm64-apple-ios26.0', '-isysroot', sdk,
                                       '-c', exported/'embed.S', '-o', exported/'embed.o'])
    opus_src = checkout('opus', 'https://github.com/xiph/opus.git', OPUS_REVISION)
    vpx_src = checkout('libvpx', 'https://github.com/webmproject/libvpx.git', VPX_REVISION)
    tool('build_windows_opus.py', '--source', opus_src, '--build', work/'opus', '--sdk', sdk, '--toolchain', tc,
         '--cmake', cmake, '--ninja', ninja, '--jobs', a.jobs)
    tool('build_windows_vpx.py', '--source', vpx_src, '--build', work/'vpx', '--sdk', sdk, '--toolchain', tc,
         '--bash', bash, '--make', make, '--jobs', a.jobs)
    objects = work/'ios-objects'
    tool('windows_compile.py', '--clang', tc/'clang.exe', '--sdk', sdk, '--generated', exported,
         '--opus-include', opus_src/'include', '--vpx-include', vpx_src, '--out', objects, '--jobs', a.jobs)
    linked = work/'linked/TOTK'
    tool('windows_link.py', '--lld', tc/'lld.exe', '--sdk', sdk, '--objects', objects, '--embed', exported/'embed.o',
         '--opus', work/'opus/libopus.a', '--vpx', work/'vpx/libvpx.a', '--out', linked)
    cross_src = checkout('spirv-cross', SPIRV_CROSS[0], SPIRV_CROSS[1])
    translator = work/'translator'
    tool('build_windows_translator.py', '--out', translator, '--dotnet', dotnet,
         '--cxx', tc/'x86_64-w64-mingw32-clang++.exe', '--spirv-source', cross_src)
    source_seed = work/'shader-seed/v143'
    run('translate shaders', [py, GAME/'scripts/prepare_shader_seed.py', '--romfs', raw, '--output', source_seed,
                               '--translator', translator/'totk_xlate.exe', '--spirv-cross', translator/'spirv-cross.exe',
                               '--version', 'v143', '--modules', rewritten], {'TOTK_XLATE_SPIRV_CROSS': 'process'})
    device_seed = device_seed_for(source_seed, work/'shader-seed/v143-ios')
    tool('compile_seed.py', device_seed, 'iphoneos', '--metal', metal, '--metallib', metal.with_name('metallib.exe'),
         '--cache-dir', work/'shader-seed/v143-ios.ios-metallibs')
    external = out.with_name(out.stem + '-GameData')
    tool('windows_prepare_resources.py', '--romfs', raw, '--source-seed', source_seed, '--device-seed', device_seed, '--out', external)
    # Publish the IPA only after its external resources have been prepared or verified.
    tool('windows_pack_ipa.py', '--executable', linked, '--tree', tree, '--romfs', raw, '--icon', raw/'icon.jpg', '--out', out)
    tool('verify_windows_output.py', '--ipa', out, '--game-data', external, '--report', work/'verification.json')
    print(f'IPA: {out}\nExternal GameData: {external}\nUnsigned: sideload with a tool that retains the requested entitlements.')


if __name__ == '__main__':
    main()
