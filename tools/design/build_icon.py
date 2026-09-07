"""The El Fager app icon: the Cockpit's Ember sphere.

Each size is drawn at its own dot count and dot weight rather than
downsampling one master. A dot lattice is exactly the kind of artwork that
turns to mush when scaled — at 16px a 900-dot sphere is a brown smudge — so
the small sizes trade dots for silhouette on purpose, and keep the sphere
reading as a sphere.
"""
import math, os
from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.dirname(os.path.abspath(__file__))
SS = 4                                   # supersample

VOID     = (2, 4, 10)
PANEL    = (10, 20, 38)
EMBER    = (240, 153, 80)
EMBER_HI = (255, 190, 126)
GOLD     = (255, 218, 150)

# size -> (dot count, dot weight, glow strength, sphere radius as % of tile)
# Sparse, not dense. What makes the Cockpit's sphere read is bright points
# with void between them; crowd them and they fuse into a waffle.
TUNING = {
    256: (520, 1.00, 1.00, 0.285),
    128: (380, 1.05, 0.95, 0.285),
    64:  (190, 1.25, 0.85, 0.295),
    48:  (120, 1.45, 0.80, 0.300),
    32:  (0,   0.00, 0.70, 0.310),       # 0 dots: lit sphere instead
    24:  (0,   0.00, 0.62, 0.320),
    16:  (0,   0.00, 0.55, 0.330),
}


def render(size: int) -> Image.Image:
    n_dots, weight, glow_k, r_frac = TUNING[size]
    W = size * SS
    cx = cy = W // 2
    R = int(W * r_frac)

    # ── tile ───────────────────────────────────────────────────────────────
    tile = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    radius = int(W * 0.22)
    ImageDraw.Draw(tile).rounded_rectangle([0, 0, W - 1, W - 1], radius=radius,
                                           fill=(*VOID, 255))
    lift = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lift)
    for i in range(W // 2):
        ld.line([(0, i), (W, i)], fill=(*PANEL, int(30 * (1 - i / (W / 2)))))
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, W - 1], radius=radius,
                                           fill=255)
    img = Image.composite(Image.alpha_composite(tile, lift), tile, mask)

    # ── glow ───────────────────────────────────────────────────────────────
    halo = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse([cx - R, cy - R, cx + R, cy + R],
                                 fill=(*EMBER, int(150 * glow_k)))
    img = Image.alpha_composite(img, halo.filter(
        ImageFilter.GaussianBlur(W * 0.055)))

    body = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)

    # ── the lit sphere, at every size ──────────────────────────────────────
    # Lit from the upper left, as the Cockpit's near face is. This is the body
    # at all sizes; the lattice below is texture laid over it, never the ball
    # itself. A lattice fine enough to read as the Cockpit's would be a third
    # of a pixel here, and forcing it larger only produces a golf ball.
    # Lighting comes from a gradient, not from offsetting the shells. Offset
    # shells left a crescent of tile visible between the body and the rim, so
    # the ball looked loose inside a ring.
    ball = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    px = ball.load()
    lx, ly = -0.40, -0.42                 # light from the upper left
    for yy in range(cy - R - 1, cy + R + 2):
        for xx in range(cx - R - 1, cx + R + 2):
            dx, dy = (xx - cx) / R, (yy - cy) / R
            dist = math.hypot(dx, dy)
            if dist > 1.0:
                continue
            # Surface normal of a sphere, dotted with the light direction.
            nz = math.sqrt(max(0.0, 1 - dist * dist))
            lam = max(0.0, (-dx * lx - dy * ly + nz * 0.86))
            lam = min(1.0, lam)
            k = 0.34 + 0.66 * lam ** 1.15
            col = tuple(int(EMBER[c] + (GOLD[c] - EMBER[c]) * lam ** 2.2)
                        for c in range(3))
            edge = 1.0 if dist < 0.985 else (1 - dist) / 0.015
            px[xx, yy] = (*tuple(int(c * k) for c in col),
                          int(255 * max(0.0, min(1.0, edge))))
    body = Image.alpha_composite(body, ball)
    bd = ImageDraw.Draw(body)
    bd.ellipse([cx - R, cy - R, cx + R, cy + R], outline=(*GOLD, 200),
               width=max(int(R * 0.055), SS))

    if n_dots:
        # ── the lattice, as surface texture ────────────────────────────────
        golden = math.pi * (3 - math.sqrt(5))
        tilt = -0.32
        st, ct = math.sin(tilt), math.cos(tilt)
        clip = R * 0.90          # stop short of the rim: dots crowd the
                                 # silhouette and fray it into a dandelion
        for i in range(n_dots):
            y = 1 - (i / (n_dots - 1)) * 2
            rr = math.sqrt(max(0.0, 1 - y * y))
            th = golden * i
            x3, z3 = math.cos(th) * rr, math.sin(th) * rr
            yr = y * ct - z3 * st
            zz = y * st + z3 * ct
            if zz > 0.15:
                continue          # the far face is behind the lit body now
            p = 2.6 / (2.6 + zz)
            sx, sy = cx + x3 * R * p, cy + yr * R * p
            if math.hypot(sx - cx, sy - cy) > clip:
                continue
            dep = (zz + 1) / 2
            a = int(255 * (0.80 - dep * 0.55))
            rad = R * 0.020 * weight * (1.25 - dep * 0.5)
            bd.ellipse([sx - rad, sy - rad, sx + rad, sy + rad],
                       fill=(*GOLD, max(0, min(255, a))))

    img = Image.alpha_composite(img, body)
    img = Image.composite(img, Image.new("RGBA", (W, W), (0, 0, 0, 0)), mask)
    return img.resize((size, size), Image.LANCZOS)


frames = {s: render(s) for s in sorted(TUNING, reverse=True)}
for s, im in frames.items():
    im.save(os.path.join(OUT, f"sphere_{s}.png"))
print("  rendered:", ", ".join(str(s) for s in sorted(frames, reverse=True)))

# contact sheet at true pixel sizes, plus a 4x blow-up of the tiny ones
sheet = Image.new("RGB", (860, 620), (30, 34, 42))
d = ImageDraw.Draw(sheet)
x = 30
for s in (256, 64, 48, 32, 24, 16):
    im = frames[s]
    sheet.paste(im, (x, 40 + (256 - s) // 2), im)
    d.text((x, 40 + 256 + 14), f"{s}px", fill=(200, 212, 224))
    x += s + 26
d.text((30, 348), "16 / 24 / 32 magnified 6x — what you see on the taskbar",
       fill=(150, 165, 180))
bx = 30
for s in (16, 24, 32):
    big = frames[s].resize((s * 6, s * 6), Image.NEAREST)
    sheet.paste(big, (bx, 368), big)
    bx += s * 6 + 20
sheet.save(os.path.join(OUT, "sphere_sizes.png"))
print("  contact sheet -> sphere_sizes.png")
