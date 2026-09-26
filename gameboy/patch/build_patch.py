#!/usr/bin/env python3
"""Build the MissingNo. starter patch for Pokemon Yellow (US/Europe).

Usage: build_patch.py YELLOW.gbc OUT.ips [OUT_PATCHED.gbc]

The ROM itself is never stored in this repository. This script reads your own
copy, checks it is the expected release, applies the changes below, and writes
an IPS patch that holds only the new bytes.

What the patch does
  * Oak gives you MISSINGNO. (species $1F) at level 99 instead of Pikachu.
  * MISSINGNO. gets a real base-stat header (Yellow's accidental one is garbage
    and would overflow the sprite buffer): 255 in every stat, Bird/Normal,
    Hyper Beam / Psychic / Blizzard / Earthquake, every TM and HM.
  * New glitchy front and back battle sprites, loaded from the empty bank $3B.
  * The starter rolls perfect DVs and has all PP Ups applied.
  * Yellow's "starter Pikachu" checks now look for MISSINGNO., so it walks
    behind you, and Pikachu's overworld sprite is replaced with a glitch block.
"""
import hashlib
import random
import struct
import sys

from gbpic import compress, decompress

YELLOW_SHA1 = 'cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1'

MISSINGNO = 0x1F
LEVEL = 99
FREE_BANK = 0x3B  # completely unused in Yellow

# Move ids (Gen 1)
HYPER_BEAM, PSYCHIC, BLIZZARD, EARTHQUAKE = 0x3F, 0x5E, 0x3B, 0x59
MAX_PP = [8, 16, 8, 16]  # base PP with 3 PP Ups
BIRD, NORMAL = 0x06, 0x00


def off(bank, addr):
    """File offset of bank:addr."""
    return addr if bank == 0 else bank * 0x4000 + (addr - 0x4000)


def asm(items, origin):
    """Tiny assembler: items are hex strings, ('jr'|'jrz'|'jrnz'|'jrc', label), ('label', name)."""
    ops = {'jr': 0x18, 'jrz': 0x28, 'jrnz': 0x20, 'jrc': 0x38}
    labels, pc = {}, origin
    for it in items:
        if isinstance(it, tuple) and it[0] == 'label':
            labels[it[1]] = pc
        else:
            pc += 2 if isinstance(it, tuple) else len(bytes.fromhex(it))
    out, pc = bytearray(), origin
    for it in items:
        if isinstance(it, tuple):
            if it[0] == 'label':
                continue
            rel = labels[it[1]] - (pc + 2)
            assert -128 <= rel <= 127
            out += bytes([ops[it[0]], rel & 0xFF])
            pc += 2
        else:
            b = bytes.fromhex(it)
            out += b
            pc += len(b)
    return bytes(out)


# ---------------------------------------------------------------- graphics

def noise_tile(rng, style):
    """8x8 tile of shade values 0-3 in one of several glitch styles."""
    t = [[0] * 8 for _ in range(8)]
    a, b = rng.randint(1, 3), rng.randint(0, 3)
    for y in range(8):
        for x in range(8):
            if style == 0:
                v = rng.randint(0, 3)
            elif style == 1:
                v = a if (y + rng.randint(0, 1)) % 2 else b
            elif style == 2:
                v = a if (x // 2 + y) % 3 == 0 else b
            elif style == 3:
                v = a if x in (0, 3, 4, 7) else b
            elif style == 4:
                v = 3 if (x ^ y) & 4 else a
            else:
                v = a
            t[y][x] = v
    return t


def missingno_image(tw, th, seed, blank):
    """Build a tw x th tile glitch image; tiles in `blank` stay empty (the backwards-L)."""
    rng = random.Random(seed)
    img = [[0] * (tw * 8) for _ in range(th * 8)]
    for ty in range(th):
        for tx in range(tw):
            if (tx, ty) in blank:
                continue
            tile = noise_tile(rng, rng.choice([0, 0, 1, 2, 3, 4, 5]))
            for y in range(8):
                for x in range(8):
                    img[ty * 8 + y][tx * 8 + x] = tile[y][x]
    return img


def overworld_frame(seed, bob):
    """16x16 overworld glitch block (colour 0 is transparent)."""
    rng = random.Random(seed)
    img = [[0] * 16 for _ in range(16)]
    for y in range(16):
        for x in range(16):
            if x < 7 and y < 6:  # backwards-L notch
                continue
            if y == 15 or x == 15 or y == 6 and x < 7 or x == 7 and y < 6 or y == 0 and x >= 7 or x == 0 and y >= 6:
                v = 3
            else:
                v = rng.choice([1, 1, 2, 2, 3])
            img[y][x] = v
    if bob:
        img = [[0] * 16] + img[:-1]
    return img


def tiles_2bpp(img, x0, y0):
    out = bytearray()
    for y in range(8):
        lo = hi = 0
        for x in range(8):
            v = img[y0 + y][x0 + x]
            lo = (lo << 1) | (v & 1)
            hi = (hi << 1) | (v >> 1)
        out += bytes([lo, hi])
    return out


def overworld_sheet():
    """24 tiles: still down/up/left, then walking down/up/left; each frame TL TR BL BR."""
    out = bytearray()
    for walk in (0, 1):
        for facing in range(3):
            fr = overworld_frame(0x5EED + facing * 7 + walk * 101, walk)
            for (x0, y0) in ((0, 0), (8, 0), (0, 8), (8, 8)):
                out += tiles_2bpp(fr, x0, y0)
    return bytes(out)


# ---------------------------------------------------------------- build

class Rom:
    def __init__(self, data):
        self.d = bytearray(data)

    def expect(self, o, hexbytes):
        want = bytes.fromhex(hexbytes)
        got = bytes(self.d[o:o + len(want)])
        assert got == want, f'unexpected bytes at {o:#x}: {got.hex()} != {want.hex()}'

    def put(self, o, data, free=False):
        if free:
            assert all(b == 0 for b in self.d[o:o + len(data)]), f'space at {o:#x} is not free'
        self.d[o:o + len(data)] = data


def build(rom_bytes):
    if hashlib.sha1(rom_bytes).hexdigest() != YELLOW_SHA1:
        raise SystemExit('This is not the Pokemon Yellow (US/Europe) ROM this patch was made for.')
    r = Rom(rom_bytes)

    # --- battle sprites in the free bank
    front_img = missingno_image(7, 7, 0x1F1F, blank={(x, y) for x in range(4) for y in range(3)})
    back_img = missingno_image(4, 4, 0xB4C, blank={(0, 0), (1, 0)})
    front = compress(front_img, 7, 7)
    back = compress(back_img, 4, 4)
    assert decompress(front)[0] == front_img and decompress(back)[0] == back_img
    front_addr = 0x4000
    back_addr = front_addr + len(front)
    r.put(off(FREE_BANK, front_addr), front, free=True)
    r.put(off(FREE_BANK, back_addr), back, free=True)

    # --- UncompressMonSprite bank select (00:1413): add MISSINGNO -> FREE_BANK
    r.expect(0x1413, 'fa90cf47feb63e0b281e78fe1f3e09381778fe4a3e0a381078fe743e0b380978fe993e0c38023e0dc3f823')
    sel = asm(['fa90cf',
               '06%02x' % FREE_BANK, 'fe%02x' % MISSINGNO, ('jrz', 'got'),
               '060b', 'feb6', ('jrz', 'got'),
               '0609', 'fe1f', ('jrc', 'got'),
               '04', 'fe4a', ('jrc', 'got'),
               '04', 'fe74', ('jrc', 'got'),
               '04', 'fe99', ('jrc', 'got'),
               '04',
               ('label', 'got'), '78', 'c3f823'], 0x1413)
    assert len(sel) <= 43
    r.put(0x1413, sel.ljust(43, b'\x00'))

    # --- GetMonHeader (00:1362): Pokedex #0 (every MISSINGNO.) uses our header in bank $0E
    r.expect(0x1362, 'fa1dd13d011c0021de43cd743a')
    hook_addr, hdr_addr = 0x7C00, 0x7C14
    hook = asm(['fa1dd1', 'a7', ('jrz', 'miss'),
                '3d', '011c00', '21de43', 'c3743a',
                ('label', 'miss'), '21%02x%02x' % (hdr_addr & 0xFF, hdr_addr >> 8), 'c9'], hook_addr)
    assert hook_addr + len(hook) <= hdr_addr
    header = bytes([0x00, 255, 255, 255, 255, 255, BIRD, NORMAL, 3, 255, 0x77,
                    front_addr & 0xFF, front_addr >> 8, back_addr & 0xFF, back_addr >> 8,
                    HYPER_BEAM, PSYCHIC, BLIZZARD, EARTHQUAKE, 0,
                    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x7F, 0])
    assert len(header) == 28
    r.put(off(0x0E, hook_addr), hook, free=True)
    r.put(off(0x0E, hdr_addr), header, free=True)
    r.put(0x1362, bytes.fromhex('cd%02x%02x' % (hook_addr & 0xFF, hook_addr >> 8)) + b'\x00' * 10)

    # --- LoadFrontSpriteByMonIndex (00:1161): skip the "Rhydon trap" that refuses to
    # draw Pokedex #0, so the summary screen and Pokedex show our front sprite.
    r.expect(0x115F, 'a7e12804fe983806')
    r.put(0x1161, b'\x00\x00')

    # --- AddPartyMon (03:7228): perfect DVs when the new mon is MISSINGNO.
    r.expect(off(3, 0x7228), 'cd6d3e47cd6d3e')
    dv_addr = 0x7B00
    dv = asm(['fa90cf', 'fe%02x' % MISSINGNO, ('jrnz', 'rand'), '3eff', '47', 'c9',
              ('label', 'rand'), 'cd6d3e', '47', 'c36d3e'], dv_addr)
    r.put(off(3, dv_addr), dv, free=True)
    r.put(off(3, 0x7228), bytes.fromhex('cd%02x%02x' % (dv_addr & 0xFF, dv_addr >> 8)) + b'\x00' * 4)

    # --- Oak's lab (07:4B40): give MISSINGNO. at level 99, then max its PP
    r.expect(off(7, 0x4B40), '3e54ea16d7')
    r.expect(off(7, 0x4B60), '3e05ea26d13e54ea1dd1ea90cfcd1c39')
    r.put(off(7, 0x4B41), bytes([MISSINGNO]))
    r.put(off(7, 0x4B61), bytes([LEVEL]))
    r.put(off(7, 0x4B66), bytes([MISSINGNO]))
    pp_addr = 0x6700
    pp = asm(['cd1c39', '2187d1'] +
             ['3e%02x22' % (0xC0 | p) for p in MAX_PP[:3]] +
             ['3e%02x77' % (0xC0 | MAX_PP[3]), 'c9'], pp_addr)
    r.put(off(7, pp_addr), pp, free=True)
    r.put(off(7, 0x4B6D), bytes.fromhex('cd%02x%02x' % (pp_addr & 0xFF, pp_addr >> 8)))

    # --- follow-me: Yellow's starter-Pikachu checks now look for MISSINGNO.
    r.expect(off(0x3F, 0x4DC8), 'fe55')     # IsStarterPikachuInOurParty (species + 1)
    r.put(off(0x3F, 0x4DC9), bytes([MISSINGNO + 1]))
    r.expect(off(0x3F, 0x4E28), 'fe54')     # IsThisPartymonStarterPikachu
    r.put(off(0x3F, 0x4E29), bytes([MISSINGNO]))
    r.expect(off(0x3F, 0x50E3), 'fe54')     # starter's status check
    r.put(off(0x3F, 0x50E4), bytes([MISSINGNO]))

    # --- overworld sprite $3D (the walking Pikachu) becomes a glitch block
    sheet = overworld_sheet()
    assert len(sheet) == 24 * 16
    r.put(off(0x3F, 0x67EF), sheet)

    # --- talking to the follower: Pikachu's emotion pictures become MISSINGNO.
    # Table at 3F:6572: 4-byte entries (count, bank, pointer). Count $FF means a
    # compressed 5x5 portrait; otherwise it is that many raw animation tiles.
    portrait_img = missingno_image(5, 5, 0x9A9A, blank={(0, 0), (1, 0), (0, 1)})
    portrait = compress(portrait_img, 5, 5)
    rng = random.Random(0x4E5)
    glitch = bytearray()
    for _ in range(25):
        img = noise_tile(rng, rng.choice([0, 1, 2, 3, 4]))
        glitch += tiles_2bpp(img, 0, 0)
    portrait_addr = back_addr + len(back)
    glitch_addr = portrait_addr + len(portrait)
    r.put(off(FREE_BANK, portrait_addr), portrait, free=True)
    r.put(off(FREE_BANK, glitch_addr), bytes(glitch), free=True)
    table = off(0x3F, 0x6572)
    r.expect(table, '01390000ff390040')
    entries = 0
    for i in range(1, 62):
        e = table + i * 4
        count, bank = r.d[e], r.d[e + 1]
        assert bank in (0x39, 0x3C) and (count == 0xFF or count <= 25), (i, count, bank)
        a = portrait_addr if count == 0xFF else glitch_addr
        r.put(e + 1, bytes([FREE_BANK, a & 0xFF, a >> 8]))
        entries += 1
    assert glitch_addr + len(glitch) <= 0x8000

    # --- fix the global checksum (cosmetic; hardware does not check it)
    s = (sum(r.d) - r.d[0x14E] - r.d[0x14F]) & 0xFFFF
    r.d[0x14E], r.d[0x14F] = s >> 8, s & 0xFF
    return bytes(r.d), front_img, back_img


def make_ips(orig, new):
    out = bytearray(b'PATCH')
    i, n = 0, len(orig)
    while i < n:
        if orig[i] == new[i]:
            i += 1
            continue
        j = i
        while j < n and j - i < 0xFFFF and (orig[j] != new[j] or (j + 1 < n and orig[j + 1] != new[j + 1])):
            j += 1
        assert i != 0x454F46  # "EOF"
        out += struct.pack('>I', i)[1:] + struct.pack('>H', j - i) + new[i:j]
        i = j
    out += b'EOF'
    return bytes(out)


def apply_ips(orig, patch):
    d = bytearray(orig)
    assert patch[:5] == b'PATCH'
    p = 5
    while patch[p:p + 3] != b'EOF':
        o = int.from_bytes(patch[p:p + 3], 'big')
        size = int.from_bytes(patch[p + 3:p + 5], 'big')
        p += 5
        if size == 0:
            rle = int.from_bytes(patch[p:p + 2], 'big')
            d[o:o + rle] = bytes([patch[p + 2]]) * rle
            p += 3
        else:
            d[o:o + size] = patch[p:p + size]
            p += size
    return bytes(d)


if __name__ == '__main__':
    src = open(sys.argv[1], 'rb').read()
    patched, _, _ = build(src)
    ips = make_ips(src, patched)
    assert apply_ips(src, ips) == patched
    open(sys.argv[2], 'wb').write(ips)
    if len(sys.argv) > 3:
        open(sys.argv[3], 'wb').write(patched)
    print(f'wrote {sys.argv[2]} ({len(ips)} bytes)')
