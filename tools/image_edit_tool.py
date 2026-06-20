"""
Image editing for El Fager.

Resize, crop, convert format, compress, and rotate image files.
Uses Pillow (already installed for screen capture).
"""

import os
from pathlib import Path


def _out(original: str, suffix: str, output: str) -> str:
    """Derive output path: use given output or insert suffix before extension."""
    if output:
        return output
    p = Path(original)
    return str(p.parent / f"{p.stem}{suffix}{p.suffix}")


def resize_image(path: str, width: int, height: int = None, output: str = None) -> str:
    """Resize an image. If height is omitted, maintains aspect ratio."""
    try:
        from PIL import Image
        if not os.path.exists(path):
            return f"[resize_image failed: file not found: {path}]"
        img = Image.open(path)
        orig_w, orig_h = img.size
        if height is None:
            height = int(orig_h * width / orig_w)
        img = img.resize((width, height), Image.LANCZOS)
        out = _out(path, f"_{width}x{height}", output)
        img.save(out)
        size_kb = os.path.getsize(out) // 1024
        return f"Resized: {orig_w}x{orig_h} -> {width}x{height} -> {out} ({size_kb} KB)."
    except Exception as e:
        return f"[resize_image failed: {e}]"


def crop_image(path: str, left: int, top: int, right: int, bottom: int, output: str = None) -> str:
    """Crop image to a pixel box (left, top, right, bottom)."""
    try:
        from PIL import Image
        if not os.path.exists(path):
            return f"[crop_image failed: file not found: {path}]"
        img = Image.open(path)
        cropped = img.crop((left, top, right, bottom))
        out = _out(path, "_cropped", output)
        cropped.save(out)
        size_kb = os.path.getsize(out) // 1024
        return f"Cropped to {right - left}x{bottom - top} -> {out} ({size_kb} KB)."
    except Exception as e:
        return f"[crop_image failed: {e}]"


def convert_image(path: str, output_path: str) -> str:
    """Convert image format. Target format is inferred from output_path extension."""
    try:
        from PIL import Image
        if not os.path.exists(path):
            return f"[convert_image failed: file not found: {path}]"
        img = Image.open(path)
        if output_path.lower().endswith((".jpg", ".jpeg")) and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(output_path)
        size_kb = os.path.getsize(output_path) // 1024
        src_fmt = Path(path).suffix.upper()
        dst_fmt = Path(output_path).suffix.upper()
        return f"Converted {src_fmt} -> {dst_fmt}: {output_path} ({size_kb} KB)."
    except Exception as e:
        return f"[convert_image failed: {e}]"


def compress_image(path: str, quality: int = 75, output: str = None) -> str:
    """Reduce image file size. For JPEG/WebP: quality 1-95 (default 75). For PNG: optimizes losslessly."""
    try:
        from PIL import Image
        if not os.path.exists(path):
            return f"[compress_image failed: file not found: {path}]"
        quality = max(1, min(95, quality))
        original_size = os.path.getsize(path)
        img = Image.open(path)
        ext = Path(path).suffix.lower()
        out = _out(path, f"_q{quality}", output)
        out_ext = Path(out).suffix.lower()
        if out_ext in (".jpg", ".jpeg", ".webp"):
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(out, quality=quality, optimize=True)
        elif out_ext == ".png":
            # PNG is lossless — use compress_level (0-9). Map quality 95->0, quality 1->9.
            compress_level = max(0, min(9, round((95 - quality) / 10.5)))
            img.save(out, compress_level=compress_level, optimize=True)
        else:
            img.save(out, optimize=True)
        new_size = os.path.getsize(out)
        savings = (1 - new_size / original_size) * 100 if original_size else 0
        return (
            f"Compressed: {original_size // 1024} KB -> {new_size // 1024} KB "
            f"({savings:.0f}% smaller, quality={quality}) -> {out}"
        )
    except Exception as e:
        return f"[compress_image failed: {e}]"


def rotate_image(path: str, degrees: int, output: str = None) -> str:
    """Rotate image by degrees (positive = counter-clockwise). Common: 90, 180, 270."""
    try:
        from PIL import Image
        if not os.path.exists(path):
            return f"[rotate_image failed: file not found: {path}]"
        img = Image.open(path)
        rotated = img.rotate(degrees, expand=True)
        out = _out(path, f"_rot{degrees}", output)
        rotated.save(out)
        size_kb = os.path.getsize(out) // 1024
        return f"Rotated {degrees}deg -> {out} ({size_kb} KB, size {rotated.size[0]}x{rotated.size[1]})."
    except Exception as e:
        return f"[rotate_image failed: {e}]"
