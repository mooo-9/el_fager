"""The El Fager app icon: the dawn.

El Fager means "the dawn", and ui/overlay.py already describes its header as
"a state-hue gradient line with a 5px sun straddling it". This is that mark:
an Ember sun setting into a lit horizon, on the void tile.

Every size is drawn with its own proportions rather than downsampled from one
master. The horizon is the whole idea and it is one pixel tall at 16px, so the
small sizes give it more weight, pull the glow back so it does not wash the
line out, and grow the sun to hold the tile. Downsampling a single 256px
master loses the line entirely — which is the failure this file exists to
avoid.

Run this, then write_ico.py, to regenerate data/el_fager.ico.
"""
import math
import os
from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.dirname(os.path.abspath(__file__))
SS = 4                                    # supersample

VOID     = (2, 4, 10)
PANEL    = (10, 20, 38)
EMBER    = (240, 153, 80)
EMBER_HI = (255, 190, 126)
GOLD     = (255, 218, 150)

# size -> sun radius, horizon thickness, horizon half-span, glow, dim below
# All fractions of the tile. Note the horizon thickens and the glow falls as
# the tile shrinks: at 16px a soft glow simply eats the line.
TUNING = {
    256: (0.245, 0.030, 0.42, 1.00, 110),
    128: (0.250, 0.034, 0.42, 0.95, 110),
    64:  (0.258, 0.042, 0.41, 0.78, 100),
    48:  (0.265, 0.050, 0.41, 0.62,  95),
    32:  (0.278, 0.064, 0.42, 0.46,  85),
    24:  (0.288, 0.085, 0.43, 0.34,  75),
    16:  (0.302, 0.112, 0.44, 0.22,  62),
}


def render(size: int) -> Image.Image:
    sun_f, th_f, span_f, glow_k, dim = TUNING[size]
    W = size * SS
    cx, cy = W // 2, int(W * 0.505)
    R = int(W * sun_f)

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

    # ── the light the sun throws ───────────────────────────────────────────
    halo = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    hr = int(R * 1.45)
    ImageDraw.Draw(halo).ellipse([cx - hr, cy - hr, cx + hr, cy + hr],
                                 fill=(*EMBER, int(150 * glow_k)))
    blur_f = 0.055 if size >= 48 else 0.032
    img = Image.alpha_composite(img, halo.filter(
        ImageFilter.GaussianBlur(W * blur_f)))

    # ── the sun, lit by surface normal ─────────────────────────────────────
    ball = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    px = ball.load()
    lx, ly = -0.40, -0.42                  # light from the upper left
    for yy in range(max(0, cy - R - 1), min(W, cy + R + 2)):
        for xx in range(max(0, cx - R - 1), min(W, cx + R + 2)):
            dx, dy = (xx - cx) / R, (yy - cy) / R
            dist = math.hypot(dx, dy)
            if dist > 1.0:
                continue
            nz = math.sqrt(max(0.0, 1 - dist * dist))
            lam = min(1.0, max(0.0, -dx * lx - dy * ly + nz * 0.86))
            floor = 0.36 if size >= 48 else 0.46
            k = floor + (1 - floor) * lam ** 1.15
            col = tuple(int(EMBER[c] + (GOLD[c] - EMBER[c]) * lam ** 2.2)
                        for c in range(3))
            edge = 1.0 if dist < 0.985 else (1 - dist) / 0.015
            px[xx, yy] = (*tuple(int(c * k) for c in col),
                          int(255 * max(0.0, min(1.0, edge))))

    hy = cy + int(R * 0.34)
    thick = max(int(W * th_f), SS)

    # Below the line the sun dims rather than vanishing, so it reads as
    # sinking into the horizon instead of being cropped by it.
    below = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(below).rectangle([0, hy + thick, W, W], fill=(*VOID, dim))
    ball = Image.alpha_composite(ball, below)
    img = Image.alpha_composite(img, ball)

    # ── the horizon ────────────────────────────────────────────────────────
    span = int(W * span_f)
    line = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    lnd = ImageDraw.Draw(line)
    for i in range(span * 2):
        t = i / (span * 2)
        a = int(240 * (1 - abs(t - 0.5) * 2) ** 0.5)
        lnd.rectangle([cx - span + i, hy, cx - span + i + 1, hy + thick],
                      fill=(*EMBER_HI, a))
    # A short spill of light along the line, which is what sells it as a
    # horizon rather than a rule drawn across a circle.
    spill = line.filter(ImageFilter.GaussianBlur(W * 0.012))
    img = Image.alpha_composite(img, spill)
    img = Image.alpha_composite(img, line)

    img = Image.composite(img, Image.new("RGBA", (W, W), (0, 0, 0, 0)), mask)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    frames = {s: render(s) for s in sorted(TUNING, reverse=True)}
    for s, im in frames.items():
        im.save(os.path.join(OUT, f"dawn_{s}.png"))
    print("  rendered:", ", ".join(str(s) for s in sorted(frames, reverse=True)))

    sheet = Image.new("RGB", (900, 640), (30, 34, 42))
    d = ImageDraw.Draw(sheet)
    x = 30
    for s in (256, 64, 48, 32, 24, 16):
        sheet.paste(frames[s], (x, 40 + (256 - s) // 2), frames[s])
        d.text((x, 40 + 256 + 14), f"{s}px", fill=(200, 212, 224))
        x += s + 26
    d.text((30, 348), "16 / 24 / 32 magnified 6x — the horizon has to survive here",
           fill=(150, 165, 180))
    bx = 30
    for s in (16, 24, 32):
        big = frames[s].resize((s * 6, s * 6), Image.NEAREST)
        sheet.paste(big, (bx, 372), big)
        bx += s * 6 + 20
    sheet.save(os.path.join(OUT, "dawn_sizes.png"))
    print("  contact sheet -> dawn_sizes.png")
