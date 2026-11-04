import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('compile_seed', ROOT / 'games/totk/ios/tools/compile_seed.py')
compile_seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compile_seed)


class CompileSeedTest(unittest.TestCase):
    def test_direct_tools_compile_and_reuse_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            seed = Path(directory) / 'seed'
            seed.mkdir()
            names = ['one_b.metal', 'two_b.metal']
            for name in names:
                (seed / name).write_bytes(b'identical shader')
            (seed / 'seed-manifest.json').write_text(json.dumps({'chain': 'test', 'files': dict.fromkeys(names, 'hash')}))
            calls = []

            def run(command, **kwargs):
                calls.append(command)
                if '--version' in command:
                    return type('Result', (), {'stdout': 'test compiler'})()
                Path(command[command.index('-o') + 1]).write_bytes(b'compiled')

            args = [str(seed), 'iphoneos', '--metal', 'metal.exe', '--metallib', 'metallib.exe']
            with patch.object(compile_seed.subprocess, 'run', side_effect=run):
                compile_seed.main(args)
                before = len(calls)
                compile_seed.main(args)
            self.assertEqual(len(calls), before + 1)  # version check only
            self.assertTrue(any(c[:3] == ['metal.exe', '-target', 'air64-apple-ios26.0'] for c in calls))
            manifest = json.loads((seed / 'seed-manifest.json').read_text())
            self.assertEqual(manifest['ios_metallibs'], 2)
            self.assertTrue(all((seed / name.replace('.metal', '.metallib')).is_file() for name in names))

    def test_commands_require_both_tools_and_preserve_xcrun(self):
        self.assertEqual(compile_seed.compiler_commands('iphoneos')[0], ['xcrun', '-sdk', 'iphoneos', 'metal'])
        with self.assertRaises(ValueError):
            compile_seed.compiler_commands('iphoneos', 'metal.exe')
        with self.assertRaises(ValueError):
            compile_seed.compiler_commands('xros', 'metal.exe', 'metallib.exe')

    def test_distinct_seeds_can_reuse_a_shared_metallib_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); cache = root/'shared-cache'; calls = []
            def run(command, **kwargs):
                calls.append(command)
                if '--version' in command:
                    return type('Result', (), {'stdout': 'test compiler'})()
                Path(command[command.index('-o') + 1]).write_bytes(b'compiled')
            for name in ('seed-a', 'seed-b'):
                seed = root/name; seed.mkdir()
                (seed/'one_b.metal').write_bytes(b'identical shader')
                (seed/'seed-manifest.json').write_text(json.dumps({'chain': 'test', 'files': {'one_b.metal': 'hash'}}))
                args = [str(seed), 'iphoneos', '--metal', 'metal.exe', '--metallib', 'metallib.exe', '--cache-dir', str(cache)]
                with patch.object(compile_seed.subprocess, 'run', side_effect=run):
                    compile_seed.main(args)
            self.assertEqual(sum('-c' in command for command in calls), 1)
            self.assertTrue((root/'seed-b/one_b.metallib').is_file())


if __name__ == '__main__':
    unittest.main()
