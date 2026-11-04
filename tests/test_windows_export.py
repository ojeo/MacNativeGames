import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('windows_export', ROOT / 'games/totk/ios/tools/windows_export.py')
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


class WindowsExportTest(unittest.TestCase):
    def test_export_rejects_changed_images_and_layouts(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            hashes = {}
            for module, values in export.LAYOUT.items():
                image = folder / f'{module}.patched.bin'
                image.write_bytes(module.encode())
                hashes[image.name] = hashlib.sha256(image.read_bytes()).hexdigest()
                keys = ('TEXT_END', 'RO_OFF', 'DATA_OFF', 'PATCH_OFF')
                (folder / f'{module}.fixups.tsv').write_text(''.join(f'# {k}\t{v:#x}\n' for k, v in zip(keys, values)))
            with patch.object(export, 'VERSIONS', {'v143': {'rewritten_sha256': hashes}}):
                export.validate_images(folder)
                image = folder / 'main.patched.bin'
                image.write_bytes(b'wrong')
                with self.assertRaisesRegex(ValueError, 'unsupported rewritten image'):
                    export.validate_images(folder)
                image.write_bytes(b'main')
                (folder / 'sdk.fixups.tsv').write_text('# TEXT_END\t0\n')
                with self.assertRaisesRegex(ValueError, 'missing rewrite layout'):
                    export.validate_images(folder)


if __name__ == '__main__':
    unittest.main()
