"""Assemble a multi-size .ico that keeps each size's own artwork.

PIL's ICO writer resamples a single image to every size, which would discard
the per-size tuning entirely — the whole point of drawing 16px differently
from 256px. The container is simple enough to write directly: a 6-byte
header, a 16-byte directory entry per image, then PNG payloads (supported by
Windows Vista onward for every size, not only 256).
"""
import os, struct, sys
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ICON = os.path.join(os.path.dirname(os.path.dirname(HERE)), "data", "el_fager.ico")
REPO = r"C:\claude proj\el_fager"
SIZES = [256, 128, 64, 48, 32, 24, 16]

frames = []
for s in SIZES:
    path = os.path.join(HERE, f"sphere_{s}.png")
    if not os.path.exists(path):
        sys.exit(f"missing {path} — run build_icon.py first")
    im = Image.open(path).convert("RGBA")
    assert im.size == (s, s), f"{path} is {im.size}, expected {(s, s)}"
    buf = os.path.join(HERE, f"_ico_{s}.png")
    im.save(buf, format="PNG", optimize=True)
    with open(buf, "rb") as f:
        frames.append((s, f.read()))
    os.unlink(buf)

out = os.path.join(HERE, "el_fager.ico")
offset = 6 + 16 * len(frames)
with open(out, "wb") as f:
    f.write(struct.pack("<HHH", 0, 1, len(frames)))          # ICONDIR
    for s, data in frames:
        dim = 0 if s >= 256 else s                            # 0 means 256
        f.write(struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                            len(data), offset))
        offset += len(data)
    for _s, data in frames:
        f.write(data)

print(f"  wrote {out}  ({os.path.getsize(out):,} bytes, {len(frames)} sizes)")

# Read it back with a different library than wrote it, as a real check.
check = Image.open(out)
print(f"  verified sizes: {sorted(check.info['sizes'])}")
for s in SIZES:
    check.size = (s, s)
    px = check.convert("RGBA").load()
    assert px[s // 2, s // 2][3] > 0, f"{s}px frame is empty at its centre"
print("  every frame has content")
