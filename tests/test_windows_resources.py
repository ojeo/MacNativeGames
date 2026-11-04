import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'games/totk/ios/tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('windows_prepare_resources', TOOLS / 'windows_prepare_resources.py')
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)
spec = importlib.util.spec_from_file_location('verify_windows_output', TOOLS / 'verify_windows_output.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
spec = importlib.util.spec_from_file_location('windows_pack_ipa', TOOLS / 'windows_pack_ipa.py')
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)


class WindowsResourcesTest(unittest.TestCase):
    def test_packaged_runtime_metadata_uses_lf_without_touching_game_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); data = root/'GameData'
            config = data/'game-data/romfs-config.txt'; config.parent.mkdir(parents=True)
            overlay = data/'romfs-patches-out/2560x1440/manifest.tsv'; overlay.parent.mkdir(parents=True)
            binary = data/'romfs-patches-out/2560x1440/game.bin'
            config.write_bytes(b'SIZE 12\r\nHASH abc\r\n')
            overlay.write_bytes(b'# manifest\r\nasset\t12\r\n')
            binary.write_bytes(b'game\r\nbytes')
            packaging.normalize_runtime_metadata(data)
            self.assertEqual(config.read_bytes(), b'SIZE 12\nHASH abc\n')
            self.assertEqual(overlay.read_bytes(), b'# manifest\nasset\t12\n')
            self.assertEqual(binary.read_bytes(), b'game\r\nbytes')
            archive = root/'test.ipa'
            with zipfile.ZipFile(archive, 'w') as z:
                for path in (config, overlay, binary):
                    z.write(path, 'Payload/TOTK.app/GameData/' + path.relative_to(data).as_posix())
            with zipfile.ZipFile(archive) as z:
                verifier.verify_runtime_text(z)
            with zipfile.ZipFile(archive, 'a') as z:
                z.writestr('Payload/TOTK.app/GameData/game-data/legacy.txt', b'BAD 12\r\n')
            with zipfile.ZipFile(archive) as z:
                with self.assertRaisesRegex(ValueError, 'non-LF runtime metadata'):
                    verifier.verify_runtime_text(z)
            config.write_bytes(b'bad\rvalue\n')
            with self.assertRaisesRegex(ValueError, 'invalid carriage return'):
                packaging.normalize_runtime_metadata(data)

    def test_pack_verification_crosses_parts_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); seed = root/'seed'; seed.mkdir()
            (seed/'first').write_bytes(b'abc' * 30)
            (seed/'second').write_bytes(b'xyz' * 20)
            names = ['first', 'second']; parts = []
            resources.write_pack(seed, names, root, 'test', 23, parts.append)
            hashes = {name: hashlib.sha256((seed/name).read_bytes()).hexdigest() for name in names}
            self.assertGreater(len(parts), 2)
            resources.verify_pack(parts, seed, names, hashes)
            data = bytearray(parts[2].read_bytes()); data[0] ^= 1; parts[2].write_bytes(data)
            with self.assertRaises(ValueError): resources.verify_pack(parts, seed, names, hashes)

    def test_complete_resources_can_be_unpacked_and_incomplete_seed_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); romfs = root/'romfs'; source = root/'source'; seed = root/'seed'; out = root/'GameData'
            for p in (romfs, source, seed): p.mkdir()
            image = b'game data'; (romfs/'romfs.bin').write_bytes(image)
            image_sha = hashlib.sha256(image).hexdigest()
            metal = b'metal source'; lib = b'metallib'
            shader_name = 'a'*64 + '-' + 'b'*12 + '_b'
            source_files = {shader_name+'.metal': hashlib.sha256(metal).hexdigest()}
            base = dict(schema=1, shaders=1, version='v143', chain='chain', source_romfs_sha256=image_sha, files=source_files)
            (source/'seed-manifest.json').write_text(json.dumps(base), encoding='utf-8')
            (seed/(shader_name+'.metal')).write_bytes(metal); (seed/(shader_name+'.metallib')).write_bytes(lib)
            device = dict(base, files={**source_files, shader_name+'.metallib': hashlib.sha256(lib).hexdigest()},
                          ios_metallibs=0, ios_metal_flags=' '.join(resources.METAL_FLAGS))
            manifest = seed/'seed-manifest.json'; manifest.write_text(json.dumps(device), encoding='utf-8')
            argv = ['tool', '--romfs', str(romfs), '--source-seed', str(source), '--device-seed', str(seed), '--out', str(out)]
            def resolve(command, **kwargs):
                for path in command[-2:]: Path(path).write_text('# list\n', encoding='utf-8')
            with patch.object(resources, 'VERSIONS', {'v143': {'romfs': {'size': len(image), 'sha256': image_sha}}}), \
                 patch.object(resources, 'shader_chain', return_value='chain'), patch.object(sys, 'argv', argv), \
                 patch.object(resources.subprocess, 'run', side_effect=resolve):
                with self.assertRaisesRegex(ValueError, 'incomplete'): resources.main()
                self.assertFalse(out.exists())
                device['ios_metallibs'] = 1; manifest.write_text(json.dumps(device), encoding='utf-8')
                (seed/(shader_name+'.metal')).write_bytes(b'corrupt source')
                with self.assertRaisesRegex(ValueError, 'missing or changed'): resources.main()
                self.assertFalse(out.exists())
                (seed/(shader_name+'.metal')).write_bytes(metal)
                (seed/'abandoned.air').write_bytes(b'not a seed file')
                resources.main()
                # A repeat build must verify and reuse the matching files without replacing the folder.
                resources.main()
                marker_path = out/'shader-seed.txt'
                correct_marker = marker_path.read_bytes()
                legacy_marker = correct_marker.replace(b'\n', b'\r\n')
                marker_path.write_bytes(legacy_marker)
                with self.assertRaisesRegex(ValueError, 'shader marker'):
                    resources.main()
                self.assertEqual(marker_path.read_bytes(), legacy_marker)  # preserve an existing output
                marker_path.write_bytes(correct_marker)
            self.assertEqual((out/'romfs.bin').read_bytes(), image)
            marker = (out/'shader-seed.txt').read_bytes()
            self.assertNotIn(b'\r', marker, 'iOS must read the marker exactly as the Windows builder writes it')
            folder_bytes, fingerprint_bytes, end = marker.split(b'\n')
            self.assertEqual(end, b'')
            folder, fingerprint = folder_bytes.decode('ascii'), fingerprint_bytes.decode('ascii')
            self.assertEqual(len(fingerprint), 64)
            self.assertEqual((out/'romfs.sha256').read_bytes(), image_sha.encode('ascii') + b'\n')
            stream = io.BytesIO((out/f'{folder}.pack.000').read_bytes())
            self.assertEqual(stream.read(9), b'TOTKPACK1')
            unpacked = {}
            while length := struct.unpack('<H', stream.read(2))[0]:
                name = stream.read(length).decode()
                size = struct.unpack('<Q', stream.read(8))[0]
                unpacked[name] = stream.read(size)
            self.assertEqual(unpacked[shader_name+'.metallib'], lib)
            self.assertNotIn('abandoned.air', unpacked)
            self.assertEqual(unpacked['fingerprint.txt'].decode().strip(), fingerprint)
            with patch.object(verifier, 'VERSIONS', {'v143': {'romfs': {'sha256': image_sha}}}), \
                 patch.object(verifier, 'shader_chain', return_value='chain'):
                self.assertEqual(verifier.verify_pack(out, out/'shader-seed.txt')['metallibs'], 1)
                (out/'shader-seed.txt').write_bytes(marker.replace(b'\n', b'\r\n'))
                with self.assertRaisesRegex(ValueError, 'LF line endings'):
                    verifier.verify_pack(out, out/'shader-seed.txt')
                (out/'shader-seed.txt').write_bytes(marker)
                part = out/f'{folder}.pack.000'
                damaged = bytearray(part.read_bytes()); damaged[-3] ^= 1; part.write_bytes(damaged)
                with self.assertRaises(ValueError): verifier.verify_pack(out, out/'shader-seed.txt')


if __name__ == '__main__':
    unittest.main()
