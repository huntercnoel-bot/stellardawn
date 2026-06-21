# Generates shaded top-down ship sprite PNGs (transparent background) for Stellar Trader.
# Drawn entirely in code (no copyrighted art). Output -> Desktop/ships/<name>.png
from PIL import Image, ImageDraw, ImageFilter
import os

OUT = r"C:\Users\Hunter\Desktop\ships"
os.makedirs(OUT, exist_ok=True)
SZ = 256

def hx(h):
    h = h.lstrip('#'); return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
def light(c, t): return tuple(int(v + (255 - v) * t) for v in c)
def dark(c, t):  return tuple(int(v * (1 - t)) for v in c)

SHIPS = {
 "shuttle": dict(base="#36e0ff", acc="#cdfaff", wpn="#ff8a3c",
   hull=[[15,0],[5,-4],[-2,-8],[-9,-7],[-11,-3],[-8,0],[-11,3],[-9,7],[-2,8],[5,4]],
   lines=[[[12,0],[-7,0]],[[5,-4],[-1,-3]],[[5,4],[-1,3]]],
   cockpit=[6,0,2.2], engines=[[-10,-3],[-10,3]], weapons=[[15,0]]),
 "hauler": dict(base="#2fd6c8", acc="#d6fff7", wpn="#ff8a3c",
   hull=[[14,0],[10,-6],[7,-13],[-12,-13],[-15,-6],[-13,0],[-15,6],[-12,13],[7,13],[10,6]],
   lines=[[[7,-13],[7,13]],[[-1,-13],[-1,13]],[[-8,-13],[-8,13]],[[-12,0],[7,0]]],
   cockpit=[9,0,2.4], engines=[[-14,-6],[-14,0],[-14,6]], weapons=[[10,-6],[10,6]]),
 "clipper": dict(base="#49c2ff", acc="#eafaff", wpn="#ff7a3c",
   hull=[[24,0],[8,-3],[-2,-5],[-10,-13],[-7,-4],[-13,-2],[-12,0],[-13,2],[-7,4],[-10,13],[-2,5],[8,3]],
   lines=[[[19,0],[-9,0]],[[8,-3],[-2,-3]],[[8,3],[-2,3]]],
   cockpit=[10,0,2], engines=[[-11,-2],[-11,2]], weapons=[[24,0],[-2,-5],[-2,5]]),
 "frigate": dict(base="#6f86ff", acc="#e2e8ff", wpn="#ff5a32",
   hull=[[22,-3],[12,-7],[6,-5],[-2,-12],[-13,-14],[-15,-7],[-10,0],[-15,7],[-13,14],[-2,12],[6,5],[12,7],[22,3],[15,2],[8,0],[15,-2]],
   lines=[[[15,-2],[6,-3]],[[15,2],[6,3]],[[-2,0],[-12,0]]],
   cockpit=[3,0,2.4], engines=[[-14,-7],[-14,7]], weapons=[[22,-3],[22,3],[-2,-12],[-2,12]]),
 "dreadnought": dict(base="#9b6bff", acc="#f0e6ff", wpn="#ff3344",
   hull=[[28,0],[16,-3],[20,-6],[12,-8],[8,-7],[2,-9],[-4,-22],[-10,-10],[-16,-16],[-18,-8],[-13,0],[-18,8],[-16,16],[-10,10],[-4,22],[2,9],[8,7],[12,8],[20,6],[16,3]],
   lines=[[[20,-6],[10,-4]],[[20,6],[10,4]],[[24,0],[-12,0]],[[8,-7],[8,7]]],
   cockpit=[12,0,3.2], engines=[[-16,-9],[-14,0],[-16,9]], weapons=[[28,0],[20,-6],[20,6],[-4,-22],[-4,22]]),
 "pirate": dict(base="#ff4455", acc="#ffd24a", wpn="#ffd24a",
   hull=[[16,0],[5,-3],[1,-10],[-3,-6],[-5,-12],[-9,-5],[-7,0],[-9,5],[-5,12],[-3,6],[1,10],[5,3]],
   lines=[[[12,0],[-6,0]]],
   cockpit=[4,0,2], engines=[[-8,-3],[-8,3]], weapons=[[16,0]]),
}

def build(spec):
    base, acc, wpn = hx(spec["base"]), hx(spec["acc"]), hx(spec["wpn"])
    # rotate ship art (nose +x) so it points UP, then fit/centre in the canvas
    raw = [(py, -px) for (px, py) in spec["hull"]]
    xs = [p[0] for p in raw]; ys = [p[1] for p in raw]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    s = (SZ - 56) / max(maxx - minx, maxy - miny)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    def T(px, py):
        rx, ry = py, -px
        return ((rx - cx) * s + SZ / 2, (ry - cy) * s + SZ / 2)
    poly = [T(px, py) for (px, py) in spec["hull"]]

    img = Image.new("RGBA", (SZ, SZ), (0, 0, 0, 0))

    # soft outer glow
    glow = Image.new("RGBA", (SZ, SZ), (0, 0, 0, 0))
    ImageDraw.Draw(glow).polygon(poly, fill=base + (170,))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(10)))

    # top-lit metallic gradient, masked to the hull
    grad = Image.new("RGBA", (SZ, SZ), (0, 0, 0, 0)); g = grad.load()
    top, mid, bot = light(base, 0.55), base, dark(base, 0.6)
    yy = [p[1] for p in poly]; y0, y1 = min(yy), max(yy)
    for y in range(SZ):
        t = min(1, max(0, (y - y0) / max(1, (y1 - y0))))
        if t < 0.42:
            tt = t / 0.42; col = tuple(int(top[i] + (mid[i] - top[i]) * tt) for i in range(3))
        else:
            tt = (t - 0.42) / 0.58; col = tuple(int(mid[i] + (bot[i] - mid[i]) * tt) for i in range(3))
        for x in range(SZ): g[x, y] = col + (255,)
    mask = Image.new("L", (SZ, SZ), 0); ImageDraw.Draw(mask).polygon(poly, fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    d.line(poly + [poly[0]], fill=light(base, 0.5) + (255,), width=3, joint="curve")  # rim light
    for seg in spec.get("lines", []):                                                  # panel seams
        d.line([T(*seg[0]), T(*seg[1])], fill=(0, 0, 0, 110), width=2)

    cxp = T(spec["cockpit"][0], spec["cockpit"][1]); cr = spec["cockpit"][2] * s * 1.1  # cockpit
    cg = Image.new("RGBA", (SZ, SZ), (0, 0, 0, 0))
    ImageDraw.Draw(cg).ellipse([cxp[0]-cr, cxp[1]-cr, cxp[0]+cr, cxp[1]+cr], fill=acc + (255,))
    img = Image.alpha_composite(img, cg.filter(ImageFilter.GaussianBlur(3)))

    eg = Image.new("RGBA", (SZ, SZ), (0, 0, 0, 0)); ed = ImageDraw.Draw(eg)             # engine glow
    for e in spec.get("engines", []):
        ep = T(e[0], e[1]); rr = 3.4
        ed.ellipse([ep[0]-rr, ep[1]-rr, ep[0]+rr, ep[1]+rr], fill=(150, 210, 255, 255))
    img = Image.alpha_composite(img, eg.filter(ImageFilter.GaussianBlur(2)))

    d = ImageDraw.Draw(img)
    for w in spec.get("weapons", []):                                                   # weapon ports
        wp = T(w[0], w[1]); rr = 2.6
        d.ellipse([wp[0]-rr, wp[1]-rr, wp[0]+rr, wp[1]+rr], fill=wpn + (255,))
    return img

for name, spec in SHIPS.items():
    build(spec).save(os.path.join(OUT, name + ".png"))
    print("wrote", name + ".png")
print("done ->", OUT)
