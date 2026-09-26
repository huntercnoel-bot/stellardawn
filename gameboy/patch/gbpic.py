"""Gen 1 Pokemon picture compression.

Images are lists of rows of shade values 0-3 (w*8 wide, h*8 tall). The encoder
always writes the second plane-order variant (primary bit 1), which is what
every retail pic in Yellow uses, and picks the smallest of the three modes.
"""


class _Bits:
    def __init__(self, data=b''):
        self.data, self.pos, self.out = data, 0, []

    def read(self, n=1):
        v = 0
        for _ in range(n):
            v = (v << 1) | ((self.data[self.pos >> 3] >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v

    def write(self, v, n=1):
        for i in range(n - 1, -1, -1):
            self.out.append((v >> i) & 1)

    def bytes(self):
        bits = self.out + [0] * (-len(self.out) % 8)
        return bytes(int(''.join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8))


def _pairs(plane):
    h, w = len(plane), len(plane[0])
    return [(plane[y][c * 2] << 1) | plane[y][c * 2 + 1] for c in range(w // 2) for y in range(h)]


def _unpairs(pairs, w, h):
    plane = [[0] * w for _ in range(h)]
    for i, p in enumerate(pairs):
        c, y = divmod(i, h)
        plane[y][c * 2], plane[y][c * 2 + 1] = p >> 1, p & 1
    return plane


def _write_plane(bw, plane):
    pairs = _pairs(plane)
    i, n = 0, len(pairs)
    bw.write(0 if pairs[0] == 0 else 1)
    while i < n:
        if pairs[i] == 0:
            j = i
            while j < n and pairs[j] == 0:
                j += 1
            count = j - i
            k = 0
            while count >= (1 << (k + 2)) - 1:
                k += 1
            bw.write((1 << (k + 1)) - 2, k + 1)  # k ones then a zero
            bw.write(count - ((1 << (k + 1)) - 1), k + 1)
            i = j
        else:
            while i < n and pairs[i] != 0:
                bw.write(pairs[i], 2)
                i += 1
            if i < n:
                bw.write(0, 2)


def _read_plane(br, w, h):
    total = w * h * 32
    pairs, rle = [], br.read() == 0
    while len(pairs) < total:
        if rle:
            k = 0
            while br.read():
                k += 1
            pairs += [0] * (br.read(k + 1) + (1 << (k + 1)) - 1)
        else:
            while len(pairs) < total:
                p = br.read(2)
                if p == 0:
                    break
                pairs.append(p)
        rle = not rle
    return _unpairs(pairs[:total], w * 8, h * 8)


def _delta_enc(plane):
    return [[row[x] ^ (row[x - 1] if x else 0) for x in range(len(row))] for row in plane]


def _delta_dec(plane):
    out = []
    for row in plane:
        s, r = 0, []
        for v in row:
            s ^= v
            r.append(s)
        out.append(r)
    return out


def _xor(a, b):
    return [[x ^ y for x, y in zip(ra, rb)] for ra, rb in zip(a, b)]


def compress(img, w, h):
    lo = [[v & 1 for v in row] for row in img]
    hi = [[v >> 1 for v in row] for row in img]
    best = None
    for mode in (1, 2, 3):
        first = _delta_enc(hi)
        second = {1: _delta_enc(lo), 2: _xor(lo, hi), 3: _delta_enc(_xor(lo, hi))}[mode]
        bw = _Bits()
        bw.write(w, 4)
        bw.write(h, 4)
        bw.write(1)
        _write_plane(bw, first)
        bw.write({1: 0, 2: 0b10, 3: 0b11}[mode], 1 if mode == 1 else 2)
        _write_plane(bw, second)
        data = bw.bytes()
        if best is None or len(data) < len(best):
            best = data
    return best


def decompress(data):
    br = _Bits(data)
    w, h = br.read(4), br.read(4)
    primary = br.read()
    p1 = _read_plane(br, w, h)
    mode = 1 if br.read() == 0 else (2 if br.read() == 0 else 3)
    p2 = _read_plane(br, w, h)
    b, c = (p1, p2) if primary == 0 else (p2, p1)
    if mode == 1:
        b, c = _delta_dec(b), _delta_dec(c)
    elif mode == 2:
        c = _delta_dec(c)
        b = _xor(b, c)
    else:
        c = _delta_dec(c)
        b = _xor(_delta_dec(b), c)
    img = [[b[y][x] | (c[y][x] << 1) for x in range(w * 8)] for y in range(h * 8)]
    return img, w, h
