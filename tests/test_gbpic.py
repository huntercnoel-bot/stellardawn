"""Run with: python3 -m unittest discover tests"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gameboy" / "patch"))
import build_patch  # noqa: E402
from gbpic import compress, decompress  # noqa: E402


def random_image(w, h, seed, density=1.0):
    rng = random.Random(seed)
    return [[rng.randint(0, 3) if rng.random() < density else 0 for _ in range(w * 8)] for _ in range(h * 8)]


class PicTest(unittest.TestCase):
    def test_round_trip_noise_and_sparse(self):
        for size in (4, 5, 6, 7):
            for density in (1.0, 0.3, 0.02):
                img = random_image(size, size, size * 100 + int(density * 10), density)
                data = compress(img, size, size)
                self.assertEqual(decompress(data), (img, size, size))

    def test_blank_image_is_tiny(self):
        img = [[0] * 56 for _ in range(56)]
        data = compress(img, 7, 7)
        self.assertLess(len(data), 12)
        self.assertEqual(decompress(data)[0], img)

    def test_missingno_sprites_round_trip(self):
        img = build_patch.missingno_image(7, 7, 0x1F1F, blank={(x, y) for x in range(4) for y in range(3)})
        self.assertEqual(decompress(compress(img, 7, 7))[0], img)
        self.assertTrue(all(v == 0 for row in img[:24] for v in row[:32]))


class PatchToolsTest(unittest.TestCase):
    def test_ips_round_trip(self):
        rng = random.Random(1)
        orig = bytes(rng.randrange(256) for _ in range(5000))
        new = bytearray(orig)
        for o in (0, 17, 18, 2000, 4999):
            new[o] ^= 0xFF
        new[3000:3100] = b'\x42' * 100
        ips = build_patch.make_ips(orig, bytes(new))
        self.assertEqual(ips[:5], b'PATCH')
        self.assertEqual(build_patch.apply_ips(orig, ips), bytes(new))

    def test_asm_relative_jumps(self):
        code = build_patch.asm(['fe1f', ('jrz', 'end'), '00', '00', ('label', 'end'), 'c9'], 0x4000)
        self.assertEqual(code.hex(), 'fe1f28020000c9')
        back = build_patch.asm([('label', 'top'), '00', ('jr', 'top')], 0x4000)
        self.assertEqual(back.hex(), '0018fd')

    def test_overworld_sheet_size(self):
        self.assertEqual(len(build_patch.overworld_sheet()), 24 * 16)


if __name__ == "__main__":
    unittest.main()
