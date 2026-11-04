import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_windows_romfs', ROOT / 'games/totk/ios/tools/prepare_windows_romfs.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class WindowsRomfsTest(unittest.TestCase):
    def test_only_matching_image_gets_an_index(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            image = folder / 'romfs.bin'
            data = b'fixture image'
            image.write_bytes(data)
            versions = {'v143': {'romfs': {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}}}
            with patch.object(module, 'VERSIONS', versions), patch.object(module, 'index_romfs', return_value={'file': [0, 1]}) as index:
                module.prepare(folder, 'v143')
                self.assertEqual(json.loads((folder / 'index.json').read_text())['files'], {'file': [0, 1]})
                previous = (folder / 'index.json').read_bytes()
                image.write_bytes(b'X' * len(data))
                with self.assertRaisesRegex(ValueError, 'SHA-256'):
                    module.prepare(folder, 'v143')
                self.assertEqual((folder / 'index.json').read_bytes(), previous)
                self.assertEqual(index.call_count, 1)


if __name__ == '__main__':
    unittest.main()
