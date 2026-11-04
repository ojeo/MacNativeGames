import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_windows_translator', ROOT/'games/totk/ios/tools/build_windows_translator.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class TranslatorCacheIdentity(unittest.TestCase):
    def test_source_and_paths_change_identity_but_build_outputs_do_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'src').mkdir(); (root/'obj').mkdir()
            (root/'src/a.cs').write_text('first', encoding='utf-8')
            original = tool.source_hash(root, ('obj',))
            (root/'obj/output.dll').write_bytes(b'generated')
            self.assertEqual(tool.source_hash(root, ('obj',)), original)
            (root/'src/a.cs').write_text('second', encoding='utf-8')
            self.assertNotEqual(tool.source_hash(root, ('obj',)), original)
            (root/'src/a.cs').rename(root/'src/b.cs')
            renamed = tool.source_hash(root, ('obj',))
            (root/'src/b.cs').rename(root/'src/c.cs')
            self.assertNotEqual(tool.source_hash(root, ('obj',)), renamed)


if __name__ == '__main__':
    unittest.main()
