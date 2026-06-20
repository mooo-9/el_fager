"""
AI image generation — Phase 6D.

Uses OpenAI DALL-E 3. Saves PNG to data/generated_images/ and opens it.
Setup: add OPENAI_API_KEY to .env (platform.openai.com/api-keys).

Metadata index: data/generated_images/index.json
Each entry: filename, prompt, revised_prompt, size, quality, style, created_at, favorite
"""

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
load_dotenv()

_OUTPUT_DIR = Path("data/generated_images")
_INDEX_FILE = _OUTPUT_DIR / "index.json"

_NOT_SET_UP = (
    "[Image generation not set up — add OPENAI_API_KEY to .env. "
    "Get a key at platform.openai.com/api-keys.]"
)

# Size word aliases so Mo can say "landscape" instead of "1792x1024"
_SIZE_ALIASES: dict[str, str] = {
    "square":    "1024x1024",
    "landscape": "1792x1024",
    "wide":      "1792x1024",
    "panoramic": "1792x1024",
    "portrait":  "1024x1792",
    "tall":      "1024x1792",
    "vertical":  "1024x1792",
}
_VALID_SIZES   = {"1024x1024", "1792x1024", "1024x1792"}
_VALID_QUALITY = {"standard", "hd"}
_VALID_STYLE   = {"vivid", "natural"}


# ── Metadata index helpers ────────────────────────────────────────────────────

def _load_index() -> list[dict]:
    try:
        if _INDEX_FILE.exists():
            return json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
        return []
    except Exception:
        return []


def _save_index(entries: list[dict]) -> None:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _INDEX_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _prompt_slug(prompt: str, max_len: int = 35) -> str:
    words = re.sub(r"[^\w\s]", "", prompt.lower()).split()[:6]
    return ("_".join(words) or "image")[:max_len]


def _api_key() -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or key.startswith("sk-xxx") or key in ("sk-...", ""):
        return ""
    return key


def _resolve_entry(index_or_filename: str, index: list[dict]):
    """Return (entry_dict | None, list_index | -1) for a 1-based index or filename."""
    s = str(index_or_filename).strip()
    if s.isdigit():
        i = int(s) - 1
        if 0 <= i < len(index):
            return index[i], i
        return None, -1
    for i, e in enumerate(index):
        if e.get("filename") == s:
            return e, i
    return None, -1


def _resolve_path(filename: str):
    path = _OUTPUT_DIR / filename
    if path.exists():
        return path
    matches = list(_OUTPUT_DIR.glob(f"{Path(filename).stem}*"))
    return matches[0] if matches else None


def _embed_png_metadata(path: Path, prompt: str, revised_prompt: str,
                        quality: str, style: str, size: str) -> None:
    """Embed generation params into PNG text chunks — fails silently."""
    try:
        from PIL import Image, PngImagePlugin
        img = Image.open(path)
        meta = PngImagePlugin.PngInfo()
        meta.add_text("prompt", prompt)
        if revised_prompt:
            meta.add_text("revised_prompt", revised_prompt)
        meta.add_text("quality", quality)
        meta.add_text("style", style)
        meta.add_text("size", size)
        img.save(path, pnginfo=meta)
    except Exception:
        pass


# ── Public functions ──────────────────────────────────────────────────────────

def generate_image(
    prompt: str,
    size: str = "1024x1024",
    quality: str = "standard",
    style: str = "vivid",
) -> str:
    """
    Generate an image with DALL-E 3 and open it.

    size    — "1024x1024" / "square" | "1792x1024" / "landscape" / "wide" | "1024x1792" / "portrait" / "tall"
    quality — "standard" (faster, cheaper) | "hd" (sharper detail, 2x cost)
    style   — "vivid" (dramatic, cinematic) | "natural" (realistic, subtle)
    """
    api_key = _api_key()
    if not api_key:
        return _NOT_SET_UP

    size = _SIZE_ALIASES.get(size.lower(), size)
    if size    not in _VALID_SIZES:   size    = "1024x1024"
    if quality not in _VALID_QUALITY: quality = "standard"
    if style   not in _VALID_STYLE:   style   = "vivid"

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            quality=quality,
            style=style,
            n=1,
        )

        image_url      = response.data[0].url
        revised_prompt = getattr(response.data[0], "revised_prompt", None) or prompt

        # Download with up to 3 retries
        last_exc = None
        img_bytes = b""
        for attempt in range(3):
            try:
                img_resp = httpx.get(image_url, timeout=30)
                img_resp.raise_for_status()
                img_bytes = img_resp.content
                break
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(1 * (attempt + 1))
        else:
            raise last_exc

        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        slug     = _prompt_slug(prompt)
        filename = f"{slug}_{int(time.time())}.png"
        path     = _OUTPUT_DIR / filename
        path.write_bytes(img_bytes)

        # Embed generation parameters into the PNG file itself
        _embed_png_metadata(path, prompt, revised_prompt, quality, style, size)

        # Save to metadata index (newest first)
        entry = {
            "filename":       filename,
            "prompt":         prompt,
            "revised_prompt": revised_prompt if revised_prompt != prompt else "",
            "size":           size,
            "quality":        quality,
            "style":          style,
            "created_at":     datetime.now().strftime("%Y-%m-%d %H:%M"),
            "favorite":       False,
        }
        index = _load_index()
        index.insert(0, entry)
        _save_index(index)

        # Open with default viewer
        try:
            os.startfile(str(path))
        except Exception:
            pass

        # TTS-friendly — no file path in response
        quality_label = " (HD)" if quality == "hd" else ""
        result = f"Image generated{quality_label} and opened."
        if revised_prompt and revised_prompt != prompt:
            short = revised_prompt[:120] + ("..." if len(revised_prompt) > 120 else "")
            result += f"\nDALL-E refined the prompt: {short}"
        return result

    except Exception as e:
        err = str(e)
        if "content_policy" in err.lower() or "safety" in err.lower():
            return "[Image blocked by content policy — try a different prompt.]"
        if "billing" in err.lower() or "quota" in err.lower():
            return "[OpenAI quota exceeded — check your billing at platform.openai.com.]"
        if "rate_limit" in err.lower():
            return "[OpenAI rate limit hit — wait a moment and try again.]"
        return f"[Image generation error: {e}]"


def generate_variation(
    index_or_filename: str,
    changes: str,
    size: str = None,
    quality: str = None,
    style: str = None,
) -> str:
    """
    Generate a variation of a previous image by modifying its prompt.
    index_or_filename — index (1 = most recent) or filename from list_generated_images
    changes — what to change, e.g. "but at night", "in anime style", "with snow"
    size/quality/style — inherit from source image unless specified
    """
    api_key = _api_key()
    if not api_key:
        return _NOT_SET_UP

    index = _load_index()
    entry, _ = _resolve_entry(index_or_filename, index)
    if entry is None:
        total = len(index)
        return (
            f"Image '{index_or_filename}' not found "
            f"({'no images yet' if total == 0 else f'{total} image(s) available'})."
        )

    # The DALL-E revised prompt is richer — use it as the base
    base_prompt = entry.get("revised_prompt") or entry.get("prompt", "")
    if not base_prompt:
        return "No prompt stored for that image."

    new_prompt = f"{base_prompt}, {changes}"
    return generate_image(
        new_prompt,
        size    or entry.get("size",    "1024x1024"),
        quality or entry.get("quality", "standard"),
        style   or entry.get("style",   "vivid"),
    )


def list_generated_images(n: int = 10) -> str:
    """List the most recently generated images with their prompts."""
    index = _load_index()
    total = len(index)

    if not index and _OUTPUT_DIR.exists():
        loose = sorted(
            list(_OUTPUT_DIR.glob("*.png")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not loose:
            return "No generated images yet. Say 'generate an image of...' to create one."
        lines = [f"Last {min(n, len(loose))} generated images (no metadata):\n"]
        for i, img in enumerate(loose[:n], 1):
            mtime   = datetime.fromtimestamp(img.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            size_kb = img.stat().st_size // 1024
            lines.append(f"{i}. {img.name} ({size_kb} KB) — {mtime}")
        return "\n".join(lines)

    if not index:
        return "No generated images yet. Say 'generate an image of...' to create one."

    shown  = min(n, total)
    header = (
        f"Last {shown} of {total} image(s):\n"
        if total > shown else
        f"{total} generated image(s):\n"
    )
    lines = [header]
    for i, entry in enumerate(index[:n], 1):
        prompt  = entry.get("prompt", "")[:70]
        created = entry.get("created_at", "")
        quality = entry.get("quality", "standard")
        size    = entry.get("size", "")
        fav     = " [fav]" if entry.get("favorite") else ""
        q_label = " HD" if quality == "hd" else ""
        s_label = {
            "1024x1024": "square", "1792x1024": "landscape", "1024x1792": "portrait"
        }.get(size, size)
        lines.append(f"{i}.{fav} \"{prompt}\" — {s_label}{q_label}, {created}")
    return "\n".join(lines)


def open_image(index_or_filename: str) -> str:
    """
    Open a previously generated image.
    Pass an index (1 = most recent) from list_generated_images, or a filename.
    """
    index = _load_index()
    entry, _ = _resolve_entry(index_or_filename, index)

    if entry is None and not str(index_or_filename).strip().isdigit():
        filename = str(index_or_filename).strip()
        prompt   = ""
    elif entry is None:
        total = len(index)
        if total == 0:
            return "No images in the index yet — generate one first."
        return f"Index {index_or_filename} out of range — there are {total} image(s)."
    else:
        filename = entry["filename"]
        prompt   = entry.get("prompt", "")[:60]

    path = _resolve_path(filename)
    if path is None:
        return f"Image file not found: {filename}"

    try:
        os.startfile(str(path))
        label = f'"{prompt}"' if prompt else filename
        return f"Opened: {label}"
    except Exception as e:
        return f"[Could not open image: {e}]"


def delete_image(index_or_filename: str) -> str:
    """
    Delete a generated image and remove it from the index.
    Pass an index (1 = most recent) or a filename.
    """
    index = _load_index()
    entry, list_idx = _resolve_entry(index_or_filename, index)

    if entry is None and not str(index_or_filename).strip().isdigit():
        filename = str(index_or_filename).strip()
        prompt   = ""
        before   = len(index)
        index    = [e for e in index if e.get("filename") != filename]
        if len(index) == before:
            prompt = "(not in index)"
    elif entry is None:
        total = len(index)
        if total == 0:
            return "No images in the index."
        return f"Index {index_or_filename} out of range — there are {total} image(s)."
    else:
        filename = entry["filename"]
        prompt   = entry.get("prompt", "")[:60]
        index.pop(list_idx)

    path = _OUTPUT_DIR / filename
    try:
        if path.exists():
            path.unlink()
    except Exception as e:
        return f"[Could not delete file: {e}]"

    _save_index(index)
    label = f'"{prompt}"' if prompt and prompt != "(not in index)" else filename
    return f"Deleted: {label}"


def clear_all_images() -> str:
    """Delete ALL generated images and reset the index. Irreversible."""
    if not _OUTPUT_DIR.exists():
        return "No images to delete."
    deleted = 0
    for img in _OUTPUT_DIR.glob("*.png"):
        try:
            img.unlink()
            deleted += 1
        except Exception:
            pass
    _save_index([])
    return f"Deleted {deleted} image(s) and cleared the index."


def search_images(query: str) -> str:
    """Search generated images by keyword in their prompt text."""
    index = _load_index()
    if not index:
        return "No generated images yet."

    query_lower = query.lower().strip()
    matches = []
    for i, entry in enumerate(index, 1):
        haystack = (
            entry.get("prompt", "") + " " + entry.get("revised_prompt", "")
        ).lower()
        if query_lower in haystack:
            matches.append((i, entry))

    if not matches:
        return f"No images found matching '{query}'."

    lines = [f"Images matching '{query}' ({len(matches)} found):\n"]
    for global_idx, entry in matches:
        prompt  = entry.get("prompt", "")[:70]
        created = entry.get("created_at", "")
        quality = entry.get("quality", "standard")
        fav     = " [fav]" if entry.get("favorite") else ""
        q_label = " HD" if quality == "hd" else ""
        lines.append(f"  #{global_idx}{fav} \"{prompt}\"{q_label}, {created}")

    return "\n".join(lines)


def get_image_info(index_or_filename: str) -> str:
    """Get full metadata for a specific generated image."""
    index = _load_index()
    entry, _ = _resolve_entry(index_or_filename, index)
    if entry is None:
        total = len(index)
        return (
            f"Image '{index_or_filename}' not found "
            f"({'no images yet' if total == 0 else f'{total} available'})."
        )

    filename = entry["filename"]
    path     = _resolve_path(filename)
    size_map = {
        "1024x1024": "Square (1024x1024)",
        "1792x1024": "Landscape (1792x1024)",
        "1024x1792": "Portrait (1024x1792)",
    }
    size_label = size_map.get(entry.get("size", ""), entry.get("size", "unknown"))
    prompt     = entry.get("prompt", "(unknown)")
    revised    = entry.get("revised_prompt", "")

    lines = [
        f"Image #{index_or_filename}: {filename}",
        f"Prompt: {prompt}",
    ]
    if revised and revised != prompt:
        trimmed = revised[:200] + ("..." if len(revised) > 200 else "")
        lines.append(f"DALL-E refined: {trimmed}")
    lines += [
        f"Size: {size_label}",
        f"Quality: {entry.get('quality', 'standard')}",
        f"Style: {entry.get('style', 'vivid')}",
        f"Created: {entry.get('created_at', 'unknown')}",
    ]
    if path and path.exists():
        kb = path.stat().st_size // 1024
        lines.append(f"File size: {kb} KB")
    if entry.get("favorite"):
        lines.append("Marked as favorite")

    return "\n".join(lines)


def favorite_image(index_or_filename: str) -> str:
    """Toggle the favorite flag on a generated image."""
    index = _load_index()
    entry, list_idx = _resolve_entry(index_or_filename, index)
    if entry is None:
        total = len(index)
        return (
            f"Image '{index_or_filename}' not found "
            f"({'no images yet' if total == 0 else f'{total} available'})."
        )

    entry["favorite"] = not entry.get("favorite", False)
    _save_index(index)

    prompt = entry.get("prompt", "")[:60]
    action = "Added to favorites" if entry["favorite"] else "Removed from favorites"
    return f'{action}: "{prompt}"'


def list_favorite_images() -> str:
    """List images marked as favorites."""
    index = _load_index()
    favs = [(i + 1, e) for i, e in enumerate(index) if e.get("favorite")]

    if not favs:
        return "No favorite images yet. Say 'favorite image 1' to mark one."

    lines = [f"Favorite images ({len(favs)}):\n"]
    for global_idx, entry in favs:
        prompt  = entry.get("prompt", "")[:70]
        created = entry.get("created_at", "")
        q_label = " HD" if entry.get("quality") == "hd" else ""
        lines.append(f"  #{global_idx} \"{prompt}\"{q_label}, {created}")

    return "\n".join(lines)


def set_as_wallpaper(index_or_filename: str) -> str:
    """Set a generated image as the Windows desktop wallpaper."""
    index = _load_index()
    entry, _ = _resolve_entry(index_or_filename, index)

    if entry is None and not str(index_or_filename).strip().isdigit():
        filename = str(index_or_filename).strip()
        prompt   = ""
    elif entry is None:
        total = len(index)
        return (
            f"Image '{index_or_filename}' not found "
            f"({'no images yet' if total == 0 else f'{total} available'})."
        )
    else:
        filename = entry["filename"]
        prompt   = entry.get("prompt", "")[:60]

    path = _resolve_path(filename)
    if path is None:
        return f"Image file not found: {filename}"

    abs_path = str(path.absolute())
    try:
        import ctypes
        # SPI_SETDESKWALLPAPER=0x0014, SPIF_UPDATEINIFILE|SPIF_SENDCHANGE=0x0003
        result = ctypes.windll.user32.SystemParametersInfoW(0x0014, 0, abs_path, 0x0003)
        if result:
            label = f'"{prompt}"' if prompt else filename
            return f"Wallpaper set to: {label}"
        return "[Failed to set wallpaper — try running El Fager as administrator.]"
    except Exception as e:
        return f"[Wallpaper error: {e}]"


def copy_image_path(index_or_filename: str) -> str:
    """Copy the absolute file path of a generated image to the clipboard."""
    index = _load_index()
    entry, _ = _resolve_entry(index_or_filename, index)

    if entry is None and not str(index_or_filename).strip().isdigit():
        filename = str(index_or_filename).strip()
        prompt   = ""
    elif entry is None:
        total = len(index)
        return (
            f"Image '{index_or_filename}' not found "
            f"({'no images yet' if total == 0 else f'{total} available'})."
        )
    else:
        filename = entry["filename"]
        prompt   = entry.get("prompt", "")[:40]

    path = _resolve_path(filename)
    if path is None:
        return f"Image file not found: {filename}"

    abs_path = str(path.absolute())
    try:
        import pyperclip
        pyperclip.copy(abs_path)
    except Exception:
        try:
            import subprocess
            subprocess.run("clip", input=abs_path.encode("utf-16le"), check=True)
        except Exception as e:
            return f"[Clipboard error: {e}]"

    label = f'"{prompt}"' if prompt else filename
    return f"Copied path for {label} to clipboard."
