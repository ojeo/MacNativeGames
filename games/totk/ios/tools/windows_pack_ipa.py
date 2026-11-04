#!/usr/bin/env python3
"""Package a Windows-linked v143 executable as an unsigned IPA with external game data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import tempfile
import zipfile

from PIL import Image
import settings_strings
from windows_link import layout

ROOT = Path(__file__).resolve().parents[4]
GAME = ROOT / 'games/totk'


def info(name, bundle):
    return dict(CFBundleExecutable='TOTK', CFBundleIdentifier=bundle, CFBundleName=name,
                CFBundleDisplayName=name, CFBundlePackageType='APPL', CFBundleVersion='1',
                CFBundleShortVersionString='1.0', CFBundleSupportedPlatforms=['iPhoneOS'],
                MinimumOSVersion='26.0', LSRequiresIPhoneOS=True, UIDeviceFamily=[1, 2],
                UILaunchScreen={}, UIFileSharingEnabled=True, LSSupportsOpeningDocumentsInPlace=True,
                UIRequiresFullScreen=True, UISupportedInterfaceOrientations=['UIInterfaceOrientationLandscapeLeft',
                                                                            'UIInterfaceOrientationLandscapeRight'],
                UIStatusBarHidden=True, UIViewControllerBasedStatusBarAppearance=False,
                UIApplicationSupportsIndirectInputEvents=True, GCSupportsControllerUserInteraction=True,
                NSMotionUsageDescription='Tilt the iPhone to aim while you play with the on-screen controls.',
                GCSupportedGameControllers=[dict(ProfileName='ExtendedGamepad')], CADisableMinimumFrameDurationOnPhone=True,
                UIApplicationSceneManifest=dict(UIApplicationSupportsMultipleScenes=False,
                    UISceneConfigurations=dict(UIWindowSceneSessionRoleApplication=[dict(
                        UISceneConfigurationName='Default', UISceneDelegateClassName='TOTKSceneDelegate')])),
                CFBundleIcons=dict(CFBundlePrimaryIcon=dict(CFBundleIconFiles=['AppIcon120', 'AppIcon180'])),
                **{'CFBundleIcons~ipad': dict(CFBundlePrimaryIcon=dict(CFBundleIconFiles=['AppIcon152', 'AppIcon167']))})


def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def is_runtime_metadata_path(path):
    """Generated line-oriented metadata consumed by the native runtime, relative to GameData."""
    parts = path.parts
    return ((len(parts) == 2 and parts[0] == 'game-data' and path.name.endswith('.txt')) or
            (len(parts) == 2 and parts[0] == 'romfs-patches' and path.name == 'manifest.tsv') or
            (len(parts) == 3 and parts[0] == 'romfs-patches-out' and path.name == 'manifest.tsv'))


def normalize_runtime_metadata(data):
    """Normalize only generated text in the staged app, leaving game files and the work tree untouched."""
    for path in data.rglob('*'):
        if not path.is_file() or not is_runtime_metadata_path(path.relative_to(data)): continue
        raw = path.read_bytes(); normalized = raw.replace(b'\r\n', b'\n')
        if b'\r' in normalized: raise ValueError(f'invalid carriage return in runtime metadata: {path}')
        if normalized != raw: path.write_bytes(normalized)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('executable', 'tree', 'romfs', 'icon', 'out'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--app-name', default='Tears of the Kingdom')
    parser.add_argument('--bundle-id', default='org.macnativegames.totk')
    args = parser.parse_args()
    executable, tree, romfs, icon, out = (p.resolve() for p in
        (args.executable, args.tree, args.romfs, args.icon, args.out))
    if out.suffix.lower() != '.ipa': parser.error('--out must end in .ipa')
    binary = executable.read_bytes()
    sections, segments, platforms, signed = layout(binary)
    if platforms != [2] or signed or segments.get('__TOTKX') != (5, 5): raise ValueError('expected an unsigned linked iOS executable')
    required = {(f'__TOTK{name}W', '__img') for name in ('main', 'subsdk0', 'sdk')} | \
               {('__TOTKX', f'__{name}{part}') for name in ('main', 'subsdk0', 'sdk') for part in ('x0', 'x1')}
    if not required.issubset(sections) or any(segments.get(f'__TOTK{name}W') != (3, 3) for name in ('main', 'subsdk0', 'sdk')):
        raise ValueError('executable game sections or permissions are missing')
    game_data = tree / 'build/game-data/v143'
    for name in ('runtime-tables.bin', 'romfs-config.txt', 'shared-fonts.txt', 'rewriter.txt'):
        if not (game_data / name).is_file(): raise ValueError(f'missing runtime data: {name}')
    config = dict(line.split() for line in (game_data / 'romfs-config.txt').read_text().splitlines())
    manifest = json.loads((romfs / 'index.json').read_text(encoding='utf-8'))
    if (config.get('ROMFS_IMAGE_SHA256') != manifest.get('romfs_sha256') or
            config.get('ROMFS_IMAGE_SIZE') != str(manifest.get('romfs_size')) or
            config.get('ROMFS_INDEX_SHA256') != sha(romfs / 'runtime-index.bin')):
        raise ValueError('runtime RomFS config and index differ')
    font_config = dict(line.split() for line in (game_data / 'shared-fonts.txt').read_text(encoding='utf-8').splitlines())
    font_folder = tree / 'extracted/firmware/shared-fonts'
    for i in range(6):
        name = font_config.get(f'FONT{i}_FILE', '')
        if not name or Path(name).name != name or name in ('.', '..'): raise ValueError(f'invalid shared font name: {i}')
        font = font_folder / name
        if (str(font.stat().st_size) != font_config.get(f'FONT{i}_FILE_BYTES') or
                sha(font) != font_config.get(f'FONT{i}_SHA256')):
            raise ValueError(f'shared font differs from runtime config: {name}')
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ios-pack-', dir=out.parent) as tmp:
        tmp = Path(tmp); app = tmp / 'Payload/TOTK.app'; app.mkdir(parents=True)
        shutil.copyfile(executable, app / 'TOTK')
        (app / 'Info.plist').write_bytes(plistlib.dumps(info(args.app_name, args.bundle_id)))
        settings = app / 'Settings.bundle'
        shutil.copytree(GAME / 'ios/Settings.bundle', settings)
        settings_strings.localize(settings)
        with Image.open(icon) as im:
            image = im.convert('RGB')
            for size in (120, 152, 167, 180):
                image.resize((size, size), Image.Resampling.LANCZOS).save(app / f'AppIcon{size}.png')
        data = app / 'GameData'; data.mkdir()
        shutil.copytree(game_data, data / 'game-data')
        (data / 'romfs').mkdir()
        for name in ('index.json', 'runtime-index.bin'): shutil.copyfile(romfs / name, data / 'romfs' / name)
        for name in ('romfs-patches', 'romfs-patches-out'):
            source = tree / 'extracted/v143' / name
            if not source.is_dir(): raise ValueError(f'missing resource folder: {source}')
            shutil.copytree(source, data / name)
        shutil.copytree(font_folder, data / 'shared-fonts')
        normalize_runtime_metadata(data)
        archive = tmp / 'output.ipa'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as z:
            for path in sorted(app.rglob('*')):
                if not path.is_file(): continue
                entry = zipfile.ZipInfo.from_file(path, path.relative_to(tmp).as_posix())
                entry.create_system = 3
                entry.external_attr = (0o100755 if path == app / 'TOTK' else 0o100644) << 16
                with path.open('rb') as source, z.open(entry, 'w', force_zip64=True) as dest:
                    shutil.copyfileobj(source, dest, length=4 << 20)
        with zipfile.ZipFile(archive) as z:
            names = set(z.namelist())
            if any(n.endswith('/romfs.bin') or '/shader-seed/' in n for n in names): raise ValueError('external data entered IPA')
            if z.getinfo('Payload/TOTK.app/TOTK').external_attr >> 16 & 0o777 != 0o755:
                raise ValueError('IPA executable permissions are incorrect')
            if hashlib.sha256(z.read('Payload/TOTK.app/TOTK')).hexdigest() != hashlib.sha256(binary).hexdigest():
                raise ValueError('IPA executable differs from link output')
        os.replace(archive, out)
    entitlement_out = out.with_name(out.stem + '.entitlements.plist')
    shutil.copyfile(GAME / 'ios/Sources/TOTK.entitlements', entitlement_out)
    print(f'unsigned IPA: {out}; requested entitlements: {entitlement_out}')


if __name__ == '__main__':
    main()
