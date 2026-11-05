"""Execute the exported ARM64 cheat veneers against small synthetic game states.

Set TOTK_CHEAT_EXPORTED to a local windows_export.py output. These tests exercise instruction behavior, not the
identity of in-game objects or gameplay. Install Unicorn outside the repository to run them.
"""
import os
from itertools import product
from pathlib import Path
import struct
import unittest

try:
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X8, UC_ARM64_REG_X9,
                                     UC_ARM64_REG_X19, UC_ARM64_REG_X24, UC_ARM64_REG_SP,
                                     UC_ARM64_REG_NZCV, UC_ARM64_REG_S0, UC_ARM64_REG_S2,
                                     UC_ARM64_REG_S8)
except ImportError:
    Uc = None

EXPORT = os.environ.get('TOTK_CHEAT_EXPORTED')
BASE = 0x10000000
PAGE = BASE + 0x44f4000
STACK = 0x30000000
OBJECT = 0x31000000


@unittest.skipUnless(Uc and EXPORT, 'requires Unicorn and TOTK_CHEAT_EXPORTED')
class CheatProbeInstructions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(EXPORT)
        cls.text = (root / 'main.x0.bin').read_bytes()
        cls.patches = (root / 'main.x1.bin').read_bytes()

    def machine(self, mask):
        u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        u.mem_map(BASE, 0x4500000)
        u.mem_write(BASE, self.text)
        u.mem_write(BASE + 0x3af0000, self.patches)
        u.mem_write(PAGE + 0x80, struct.pack('<I', mask))
        u.mem_map(STACK, 0x10000)
        u.mem_map(OBJECT, 0x10000)
        u.reg_write(UC_ARM64_REG_SP, STACK + 0x8000)
        u.reg_write(UC_ARM64_REG_X8, 0x12345678)
        u.reg_write(UC_ARM64_REG_X9, 0x87654321)
        u.reg_write(UC_ARM64_REG_NZCV, 0xa0000000)
        return u

    def execute(self, u, site, ends):
        targets = {BASE + i for i in ends}
        from unicorn import UC_HOOK_CODE
        reached = []
        def stop(uc, address, size, user):
            if address in targets:
                reached.append(address - BASE)
                uc.emu_stop()
        u.hook_add(UC_HOOK_CODE, stop)
        u.emu_start(BASE + site, BASE + 0x4500000, count=100)
        self.assertEqual(len(reached), 1)
        self.assertEqual(u.reg_read(UC_ARM64_REG_SP), STACK + 0x8000)
        self.assertEqual(u.reg_read(UC_ARM64_REG_X9), 0x87654321)
        self.assertEqual(u.reg_read(UC_ARM64_REG_NZCV), 0xa0000000)
        return reached[0]

    def test_health_flag_and_zero_maximum(self):
        for mask, maximum in product(range(8), (0, 17)):
            expected = maximum if mask & 1 and maximum else 3
            with self.subTest(mask=mask, maximum=maximum):
                u = self.machine(mask)
                u.reg_write(UC_ARM64_REG_X0, OBJECT)
                u.mem_write(OBJECT, struct.pack('<Q', 0x12345000))
                u.mem_write(OBJECT + 8, struct.pack('<I', 3))
                u.mem_write(OBJECT + 0x18, struct.pack('<I', maximum))
                self.assertEqual(self.execute(u, 0x4407d0, [0x4407d4]), 0x4407d4)
                self.assertEqual(struct.unpack('<I', u.mem_read(OBJECT + 8, 4))[0], expected)
                self.assertEqual(u.reg_read(UC_ARM64_REG_X8), 0x12345000)

    def test_stamina_uses_original_fmadd_when_off(self):
        bits = lambda x: struct.unpack('<I', struct.pack('<f', x))[0]
        for mask in range(8):
            result = 10.0 if mask & 4 else 14.0
            with self.subTest(mask=mask):
                u = self.machine(mask)
                for reg, value in ((UC_ARM64_REG_S0, 2.0), (UC_ARM64_REG_S2, 10.0), (UC_ARM64_REG_S8, 2.0)):
                    u.reg_write(reg, bits(value))
                self.execute(u, 0x31d398, [0x31d39c])
                self.assertEqual(u.reg_read(UC_ARM64_REG_S0), bits(result))
                self.assertEqual(u.reg_read(UC_ARM64_REG_X8), 0x12345678)

    def test_battery_preserves_original_branch_when_off(self):
        for mask, w24 in product(range(8), (0, 1)):
            changed = bool(mask & 2)
            target = 0x782280 if changed else (0x782558 if w24 else 0x782278)
            with self.subTest(mask=mask, w24=w24):
                u = self.machine(mask)
                u.reg_write(UC_ARM64_REG_X19, OBJECT)
                u.reg_write(UC_ARM64_REG_X24, w24)
                u.reg_write(UC_ARM64_REG_S2, 0x3f000000)
                u.reg_write(UC_ARM64_REG_S8, 0x3f800000)
                u.mem_write(OBJECT + 0x44, struct.pack('<I', 0x3f800000))
                self.assertEqual(self.execute(u, 0x782274, [0x782278, 0x782558, 0x782280]), target)
                self.assertEqual(struct.unpack('<I', u.mem_read(OBJECT + 0x44, 4))[0], 0x3f000000 if changed else 0x3f800000)
                self.assertEqual(u.reg_read(UC_ARM64_REG_X8), 0x12345678)


if __name__ == '__main__':
    unittest.main()
