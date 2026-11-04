import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'games/totk/ios/tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('build_ipa_windows', TOOLS / 'build_ipa_windows.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class DeviceSeedSelection(unittest.TestCase):
    def test_changed_source_gets_a_new_seed_without_replacing_the_old_one(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'source'; source.mkdir()
            manifest = {'schema': 1, 'chain': 'v9', 'version': 'v143', 'game': 'totk',
                        'source_romfs_sha256': 'rom', 'files': {'one_b.metal': 'first'}}
            (source/'seed-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            (source/'one_b.metal').write_text('first', encoding='utf-8')
            default = root/'v143-ios'
            self.assertEqual(builder.device_seed_for(source, default), default)
            old = json.loads((default/'seed-manifest.json').read_text(encoding='utf-8'))
            old['files']['one_b.metallib'] = 'compiled'
            (default/'seed-manifest.json').write_text(json.dumps(old), encoding='utf-8')
            self.assertEqual(builder.device_seed_for(source, default), default)

            manifest['files']['one_b.metal'] = 'second'
            (source/'seed-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            (source/'one_b.metal').write_text('second', encoding='utf-8')
            next_seed = builder.device_seed_for(source, default)
            self.assertNotEqual(next_seed, default)
            self.assertEqual((default/'one_b.metal').read_text(), 'first')
            self.assertEqual((next_seed/'one_b.metal').read_text(), 'second')
            self.assertEqual(builder.device_seed_for(source, default), next_seed)

    def test_incomplete_staging_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'source'; source.mkdir()
            (source/'seed-manifest.json').write_text(json.dumps({'files': {'one_b.metal': 'hash'}}))
            partial = root/'v143-ios.partial'; partial.mkdir()
            (partial/'keep').write_text('existing data')
            with self.assertRaisesRegex(ValueError, 'incomplete shader seed'):
                builder.device_seed_for(source, root/'v143-ios')
            self.assertEqual((partial/'keep').read_text(), 'existing data')


if __name__ == '__main__':
    unittest.main()
