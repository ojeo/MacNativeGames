"""Exercise the production MSL texture-read detector without a GPU."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NVN = ROOT / 'games/totk/third_party/d2r_gfx/gfx/nvn'


class MslFetch(unittest.TestCase):
    def test_integer_reads_are_identified_by_binding(self):
        compiler = os.environ.get('MNG_TEST_CC') or shutil.which('cc') or shutil.which('clang')
        if not compiler:
            self.skipTest('a C compiler is required')
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory) / ('msl-fetch.exe' if os.name == 'nt' else 'msl-fetch')
            build = subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(NVN),
                                    str(ROOT/'tests/test_msl_fetch.c'), '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('detection passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
