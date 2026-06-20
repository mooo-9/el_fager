# El Fager — Final JARVIS Gaps Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the 6 remaining gaps between El Fager and a fully capable JARVIS — file system control, archive handling, image editing, unit conversion, local git operations, and developer utilities — adding ~36 tools to reach ~344 total.

**Architecture:** Each gap becomes one new tool file in `tools/` following the established pattern (pure functions, `-> str` return, try/except wrapping, lazy imports). Each task ends with wiring the new file into `core/brain.py`: TOOLS list entry, `_TOOL_GROUP_NAMES`, `_GROUP_TRIGGERS`, `_dispatch_tool` elif blocks, and a SYSTEM_PROMPT line.

**Tech Stack:** Python stdlib (os, shutil, zipfile, hashlib, uuid, subprocess, pathlib) · Pillow (installed) · python-docx (installed) · openpyxl (installed) · qrcode[pil] (install in Task 6) · git CLI (v2.53 installed)

## Global Constraints

- All tool functions return `str` — never raise
- Errors returned as `[tool_name failed: reason]`
- Heavy imports inside the function body only (lazy import pattern)
- Destructive operations (delete, overwrite) must state clearly what they did in the return string
- brain.py dispatch uses `elif name == "tool_name":` — never bare `if`
- Working directory: `C:\claude proj\el_fager`

---

## Task 1 — File System Operations (`tools/file_ops_tool.py`)

**What El Fager can currently do:** search files, open files, read file content.  
**What's missing:** create folders, rename, copy, move, delete files/folders, list folder contents.

**Files:**
- Create: `tools/file_ops_tool.py`
- Modify: `core/brain.py` — TOOLS list, `_TOOL_GROUP_NAMES["files"]` (extend existing), `_GROUP_TRIGGERS["files"]` (extend existing), `_dispatch_tool`, SYSTEM_PROMPT

**Functions to implement:**

| Function | Signature | What it does |
|---|---|---|
| `create_folder` | `(path: str) -> str` | Create directory (and parents). Returns path created. |
| `rename_file` | `(path: str, new_name: str) -> str` | Rename file/folder in-place. new_name is just the filename, not a full path. |
| `copy_file` | `(src: str, dst: str) -> str` | Copy file to destination path. If dst is a folder, copies inside it. |
| `move_file` | `(src: str, dst: str) -> str` | Move/rename file or folder. |
| `delete_file` | `(path: str) -> str` | Delete file. Returns what was deleted and size. |
| `list_folder` | `(path: str, show_hidden: bool = False) -> str` | List contents with size, type (file/dir), modification date. |

**`tools/file_ops_tool.py` — complete implementation:**

```python
"""
File system operations for El Fager.

Create folders, rename, copy, move, delete files and folders, list directory contents.
Uses stdlib only — os, shutil, pathlib.
"""

import os
import shutil
from pathlib import Path
from datetime import datetime


def create_folder(path: str) -> str:
    """Create a directory (and all parents). Safe to call if it already exists."""
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return f"Folder created: {path}"
    except Exception as e:
        return f"[create_folder failed: {e}]"


def rename_file(path: str, new_name: str) -> str:
    """Rename a file or folder. new_name is the new filename only (not a full path)."""
    try:
        p = Path(path)
        if not p.exists():
            return f"[rename_file failed: path not found: {path}]"
        new_path = p.parent / new_name
        if new_path.exists():
            return f"[rename_file failed: '{new_name}' already exists in {p.parent}]"
        p.rename(new_path)
        return f"Renamed: '{p.name}' → '{new_name}' in {p.parent}"
    except Exception as e:
        return f"[rename_file failed: {e}]"


def copy_file(src: str, dst: str) -> str:
    """Copy a file to a destination path. If dst is a folder, copies inside it."""
    try:
        s = Path(src)
        d = Path(dst)
        if not s.exists():
            return f"[copy_file failed: source not found: {src}]"
        if s.is_dir():
            shutil.copytree(str(s), str(d))
            return f"Folder copied: {src} → {dst}"
        else:
            result = shutil.copy2(str(s), str(d))
            size_kb = Path(result).stat().st_size // 1024
            return f"File copied: {src} → {result} ({size_kb} KB)"
    except Exception as e:
        return f"[copy_file failed: {e}]"


def move_file(src: str, dst: str) -> str:
    """Move or rename a file or folder to a new path."""
    try:
        if not Path(src).exists():
            return f"[move_file failed: source not found: {src}]"
        result = shutil.move(src, dst)
        return f"Moved: {src} → {result}"
    except Exception as e:
        return f"[move_file failed: {e}]"


def delete_file(path: str) -> str:
    """Delete a file. For folders, use with caution — deletes recursively."""
    try:
        p = Path(path)
        if not p.exists():
            return f"[delete_file failed: path not found: {path}]"
        if p.is_dir():
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            file_count = sum(1 for _ in p.rglob("*") if _.is_file())
            shutil.rmtree(str(p))
            return f"Folder deleted: {path} ({file_count} files, {size // 1024} KB total)."
        else:
            size_kb = p.stat().st_size // 1024
            p.unlink()
            return f"File deleted: {path} ({size_kb} KB)."
    except Exception as e:
        return f"[delete_file failed: {e}]"


def list_folder(path: str, show_hidden: bool = False) -> str:
    """List folder contents with size, type, and modification date."""
    try:
        p = Path(path)
        if not p.exists():
            return f"[list_folder failed: path not found: {path}]"
        if not p.is_dir():
            return f"[list_folder failed: not a directory: {path}]"

        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        if not show_hidden:
            entries = [e for e in entries if not e.name.startswith(".")]

        if not entries:
            return f"{path} is empty."

        lines = [f"{path} ({len(entries)} items):"]
        for e in entries[:50]:
            try:
                stat = e.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                if e.is_dir():
                    lines.append(f"  [DIR]  {e.name}  {mtime}")
                else:
                    size = stat.st_size
                    size_str = f"{size // 1024} KB" if size >= 1024 else f"{size} B"
                    lines.append(f"  {e.suffix or 'FILE':6}  {e.name}  {size_str}  {mtime}")
            except Exception:
                lines.append(f"  ?  {e.name}")

        if len(list(p.iterdir())) > 50:
            lines.append(f"  ... and more (showing first 50)")
        return "\n".join(lines)
    except Exception as e:
        return f"[list_folder failed: {e}]"
```

**brain.py — TOOLS list entries** (insert before `# ── Bond Tools ──` comment or at end of TOOLS list, before the closing `]`):

```python
    # ── File Operations ───────────────────────────────────────────────────────
    {
        "name": "create_folder",
        "description": "Create a new folder (and all parent folders). Safe to call if it already exists.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Full path to create, e.g. 'C:\\Users\\Mo\\Projects\\MyProject'"}},
            "required": ["path"]
        }
    },
    {
        "name": "rename_file",
        "description": "Rename a file or folder in place. new_name is just the filename, not a full path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Full current path of the file or folder"},
                "new_name": {"type": "string", "description": "New filename only (e.g. 'report_v2.pdf')"}
            },
            "required": ["path", "new_name"]
        }
    },
    {
        "name": "copy_file",
        "description": "Copy a file to a new path. If destination is a folder, copies inside it. Also copies entire folders with copy_file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "src": {"type": "string"},
                "dst": {"type": "string", "description": "Destination file path or folder path"}
            },
            "required": ["src", "dst"]
        }
    },
    {
        "name": "move_file",
        "description": "Move (or rename to a different path) a file or folder.",
        "input_schema": {
            "type": "object",
            "properties": {
                "src": {"type": "string"},
                "dst": {"type": "string", "description": "Destination path"}
            },
            "required": ["src", "dst"]
        }
    },
    {
        "name": "delete_file",
        "description": "Delete a file permanently. For folders, deletes recursively. ALWAYS confirm with Mo before calling this — it cannot be undone.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]
        }
    },
    {
        "name": "list_folder",
        "description": "List contents of a folder with file types, sizes, and modification dates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "show_hidden": {"type": "boolean", "description": "Include hidden files. Default false."}
            },
            "required": ["path"]
        }
    },
```

**brain.py — extend `_TOOL_GROUP_NAMES["files"]`** (add to existing frozenset):

```python
    "files": frozenset({
        "file_search", "open_file", "read_file_content", "open_app", "run_command",
        # NEW:
        "create_folder", "rename_file", "copy_file", "move_file", "delete_file", "list_folder",
    }),
```

**brain.py — extend `_GROUP_TRIGGERS["files"]`** (add to existing list):

```python
    "files": ["open file", "read file", "find file", "search file", "open app",
              "open application", "run command", "folder", "directory", ".exe",
              # NEW:
              "create folder", "make folder", "rename", "copy file", "move file",
              "delete file", "list folder", "what's in", "انشئ مجلد", "احذف"],
```

**brain.py — dispatch blocks** (add before `else: return f"Unknown tool: {name}"`):

```python
            # ── File operations ───────────────────────────────────────────────
            elif name == "create_folder":
                from tools.file_ops_tool import create_folder
                return create_folder(tool_input["path"])
            elif name == "rename_file":
                from tools.file_ops_tool import rename_file
                return rename_file(tool_input["path"], tool_input["new_name"])
            elif name == "copy_file":
                from tools.file_ops_tool import copy_file
                return copy_file(tool_input["src"], tool_input["dst"])
            elif name == "move_file":
                from tools.file_ops_tool import move_file
                return move_file(tool_input["src"], tool_input["dst"])
            elif name == "delete_file":
                from tools.file_ops_tool import delete_file
                return delete_file(tool_input["path"])
            elif name == "list_folder":
                from tools.file_ops_tool import list_folder
                return list_folder(tool_input["path"], tool_input.get("show_hidden", False))
```

**brain.py — SYSTEM_PROMPT line** (add near the file tools section):

```
File system: create_folder, rename_file, copy_file, move_file, delete_file, list_folder.
"create a folder for X" → create_folder. "rename this file" → rename_file. "copy X to Y" → copy_file. "what's in this folder?" → list_folder.
IMPORTANT: Always confirm with Mo before calling delete_file — it permanently removes the file with no recycle bin.
```

**Verification:**
```python
python -c "from tools.file_ops_tool import create_folder, list_folder; print(create_folder('data/test_dir')); print(list_folder('data')); import shutil; shutil.rmtree('data/test_dir')"
```

---

## Task 2 — Archive Tools (`tools/archive_tool.py`)

**Files:**
- Create: `tools/archive_tool.py`
- Modify: `core/brain.py`

**Functions:**

| Function | Signature | What it does |
|---|---|---|
| `zip_files` | `(paths: list, output_path: str) -> str` | Create .zip from list of files/folders |
| `unzip_archive` | `(zip_path: str, output_dir: str = None) -> str` | Extract .zip to directory (auto-named if omitted) |
| `list_archive` | `(zip_path: str) -> str` | List contents of a .zip without extracting |
| `add_to_archive` | `(zip_path: str, paths: list) -> str` | Add files to existing .zip |

**`tools/archive_tool.py` — complete implementation:**

```python
"""
Archive (zip) tools for El Fager.

Create, extract, inspect, and update .zip files.
Uses stdlib zipfile only — no external dependencies.
"""

import os
import zipfile
from pathlib import Path
from datetime import datetime


def zip_files(paths: list, output_path: str) -> str:
    """Create a .zip archive from a list of file/folder paths."""
    try:
        if not output_path.endswith(".zip"):
            output_path += ".zip"

        parent = os.path.dirname(output_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        added = 0
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in paths:
                p = Path(path)
                if not p.exists():
                    return f"[zip_files failed: path not found: {path}]"
                if p.is_dir():
                    for f in p.rglob("*"):
                        if f.is_file():
                            zf.write(f, f.relative_to(p.parent))
                            added += 1
                else:
                    zf.write(p, p.name)
                    added += 1

        size_kb = os.path.getsize(output_path) // 1024
        return f"Created: {output_path} ({added} files, {size_kb} KB)."
    except Exception as e:
        return f"[zip_files failed: {e}]"


def unzip_archive(zip_path: str, output_dir: str = None) -> str:
    """Extract a .zip archive to a directory."""
    try:
        if not os.path.exists(zip_path):
            return f"[unzip_archive failed: file not found: {zip_path}]"

        if output_dir is None:
            base = os.path.splitext(zip_path)[0]
            output_dir = base

        os.makedirs(output_dir, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            zf.extractall(output_dir)

        return f"Extracted {len(names)} files → {output_dir}"
    except zipfile.BadZipFile:
        return f"[unzip_archive failed: '{zip_path}' is not a valid .zip file]"
    except Exception as e:
        return f"[unzip_archive failed: {e}]"


def list_archive(zip_path: str) -> str:
    """List the contents of a .zip file without extracting."""
    try:
        if not os.path.exists(zip_path):
            return f"[list_archive failed: file not found: {zip_path}]"

        with zipfile.ZipFile(zip_path, "r") as zf:
            infos = zf.infolist()

        if not infos:
            return f"{zip_path} is empty."

        total_size = sum(i.file_size for i in infos)
        lines = [f"{zip_path} — {len(infos)} files, {total_size // 1024} KB uncompressed:"]
        for info in infos[:30]:
            size_kb = info.file_size // 1024
            date = datetime(*info.date_time).strftime("%Y-%m-%d")
            lines.append(f"  {info.filename}  ({size_kb} KB, {date})")
        if len(infos) > 30:
            lines.append(f"  ... and {len(infos) - 30} more")
        return "\n".join(lines)
    except zipfile.BadZipFile:
        return f"[list_archive failed: '{zip_path}' is not a valid .zip file]"
    except Exception as e:
        return f"[list_archive failed: {e}]"


def add_to_archive(zip_path: str, paths: list) -> str:
    """Add files to an existing .zip, or create it if it doesn't exist."""
    try:
        mode = "a" if os.path.exists(zip_path) else "w"
        added = 0
        with zipfile.ZipFile(zip_path, mode, zipfile.ZIP_DEFLATED) as zf:
            for path in paths:
                p = Path(path)
                if not p.exists():
                    return f"[add_to_archive failed: path not found: {path}]"
                if p.is_dir():
                    for f in p.rglob("*"):
                        if f.is_file():
                            zf.write(f, f.relative_to(p.parent))
                            added += 1
                else:
                    zf.write(p, p.name)
                    added += 1

        size_kb = os.path.getsize(zip_path) // 1024
        action = "Updated" if mode == "a" else "Created"
        return f"{action}: {zip_path} (+{added} files, now {size_kb} KB)."
    except Exception as e:
        return f"[add_to_archive failed: {e}]"
```

**brain.py — TOOLS list entries:**

```python
    # ── Archive Tools ─────────────────────────────────────────────────────────
    {
        "name": "zip_files",
        "description": "Create a .zip archive from a list of files and/or folders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "description": "List of file/folder paths to include"},
                "output_path": {"type": "string", "description": "Output .zip path, e.g. 'data/archive.zip'"}
            },
            "required": ["paths", "output_path"]
        }
    },
    {
        "name": "unzip_archive",
        "description": "Extract a .zip archive to a folder. If no output_dir given, extracts to a folder named after the zip.",
        "input_schema": {
            "type": "object",
            "properties": {
                "zip_path": {"type": "string"},
                "output_dir": {"type": "string", "description": "Optional destination folder. Auto-named from zip if omitted."}
            },
            "required": ["zip_path"]
        }
    },
    {
        "name": "list_archive",
        "description": "List the contents of a .zip file without extracting it.",
        "input_schema": {
            "type": "object",
            "properties": {"zip_path": {"type": "string"}},
            "required": ["zip_path"]
        }
    },
    {
        "name": "add_to_archive",
        "description": "Add files or folders to an existing .zip, or create the zip if it doesn't exist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "zip_path": {"type": "string"},
                "paths": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["zip_path", "paths"]
        }
    },
```

**brain.py — new group in `_TOOL_GROUP_NAMES`:**

```python
    "archive": frozenset({
        "zip_files", "unzip_archive", "list_archive", "add_to_archive",
    }),
```

**brain.py — new triggers in `_GROUP_TRIGGERS`:**

```python
    "archive": ["zip", "unzip", "archive", "compress files", "extract", ".zip",
                "pack files", "bundle files", "اضغط الملفات", "استخرج"],
```

**brain.py — dispatch blocks:**

```python
            # ── Archive ───────────────────────────────────────────────────────
            elif name == "zip_files":
                from tools.archive_tool import zip_files
                return zip_files(tool_input["paths"], tool_input["output_path"])
            elif name == "unzip_archive":
                from tools.archive_tool import unzip_archive
                return unzip_archive(tool_input["zip_path"], tool_input.get("output_dir"))
            elif name == "list_archive":
                from tools.archive_tool import list_archive
                return list_archive(tool_input["zip_path"])
            elif name == "add_to_archive":
                from tools.archive_tool import add_to_archive
                return add_to_archive(tool_input["zip_path"], tool_input["paths"])
```

**brain.py — SYSTEM_PROMPT line:**

```
Archive tools: zip_files, unzip_archive, list_archive, add_to_archive.
"zip these files" → zip_files(paths, output). "extract this zip" → unzip_archive. "what's in this zip?" → list_archive.
```

**Verification:**
```python
python -c "
from tools.archive_tool import zip_files, list_archive, unzip_archive
import os, shutil
print(zip_files(['README.md'], 'data/test.zip'))
print(list_archive('data/test.zip'))
print(unzip_archive('data/test.zip', 'data/test_extract'))
shutil.rmtree('data/test_extract', ignore_errors=True)
os.unlink('data/test.zip')
"
```

---

## Task 3 — Image Editing (`tools/image_edit_tool.py`)

**Files:**
- Create: `tools/image_edit_tool.py`
- Modify: `core/brain.py`
- Dependencies: Pillow (already installed)

**Functions:**

| Function | Signature | What it does |
|---|---|---|
| `resize_image` | `(path: str, width: int, height: int = None, output: str = None) -> str` | Resize keeping aspect ratio if height omitted |
| `crop_image` | `(path: str, left: int, top: int, right: int, bottom: int, output: str = None) -> str` | Crop to pixel box |
| `convert_image` | `(path: str, output_path: str) -> str` | Convert between formats (PNG→JPG, WebP→PNG, etc.) |
| `compress_image` | `(path: str, quality: int = 75, output: str = None) -> str` | Reduce JPEG/WebP file size |
| `rotate_image` | `(path: str, degrees: int, output: str = None) -> str` | Rotate 90/180/270 or arbitrary angle |

**`tools/image_edit_tool.py` — complete implementation:**

```python
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
        return f"Resized: {orig_w}x{orig_h} → {width}x{height} → {out} ({size_kb} KB)."
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
        return f"Cropped to {right - left}x{bottom - top} → {out} ({size_kb} KB)."
    except Exception as e:
        return f"[crop_image failed: {e}]"


def convert_image(path: str, output_path: str) -> str:
    """Convert image format. Target format is inferred from output_path extension."""
    try:
        from PIL import Image
        if not os.path.exists(path):
            return f"[convert_image failed: file not found: {path}]"
        img = Image.open(path)
        # JPEG requires RGB
        if output_path.lower().endswith((".jpg", ".jpeg")) and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(output_path)
        size_kb = os.path.getsize(output_path) // 1024
        src_fmt = Path(path).suffix.upper()
        dst_fmt = Path(output_path).suffix.upper()
        return f"Converted {src_fmt} → {dst_fmt}: {output_path} ({size_kb} KB)."
    except Exception as e:
        return f"[convert_image failed: {e}]"


def compress_image(path: str, quality: int = 75, output: str = None) -> str:
    """Reduce JPEG/WebP image size by lowering quality. quality 1-95 (default 75)."""
    try:
        from PIL import Image
        if not os.path.exists(path):
            return f"[compress_image failed: file not found: {path}]"
        original_size = os.path.getsize(path)
        img = Image.open(path)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        out = _out(path, f"_q{quality}", output)
        img.save(out, quality=quality, optimize=True)
        new_size = os.path.getsize(out)
        savings = (1 - new_size / original_size) * 100 if original_size else 0
        return (
            f"Compressed: {original_size // 1024} KB → {new_size // 1024} KB "
            f"({savings:.0f}% smaller, quality={quality}) → {out}"
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
        return f"Rotated {degrees}° → {out} ({size_kb} KB, size {rotated.size[0]}x{rotated.size[1]})."
    except Exception as e:
        return f"[rotate_image failed: {e}]"
```

**brain.py — TOOLS list entries:**

```python
    # ── Image Editing ─────────────────────────────────────────────────────────
    {
        "name": "resize_image",
        "description": "Resize an existing image file. If height is omitted, aspect ratio is preserved.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the image file"},
                "width": {"type": "integer"},
                "height": {"type": "integer", "description": "Optional. If omitted, auto-calculated to maintain aspect ratio."},
                "output": {"type": "string", "description": "Output path. Auto-named if omitted."}
            },
            "required": ["path", "width"]
        }
    },
    {
        "name": "crop_image",
        "description": "Crop an image to a rectangular region defined by pixel coordinates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "left": {"type": "integer"}, "top": {"type": "integer"},
                "right": {"type": "integer"}, "bottom": {"type": "integer"},
                "output": {"type": "string"}
            },
            "required": ["path", "left", "top", "right", "bottom"]
        }
    },
    {
        "name": "convert_image",
        "description": "Convert an image between formats (PNG, JPEG, WebP, BMP, TIFF). Target format is inferred from the output file extension.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Source image file"},
                "output_path": {"type": "string", "description": "Destination path with new extension, e.g. 'photo.jpg'"}
            },
            "required": ["path", "output_path"]
        }
    },
    {
        "name": "compress_image",
        "description": "Reduce a JPEG or WebP image's file size by lowering quality. quality 1-95, default 75 (~40-60% size reduction).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "quality": {"type": "integer", "description": "JPEG quality 1-95. Default 75."},
                "output": {"type": "string", "description": "Output path. Auto-named if omitted."}
            },
            "required": ["path"]
        }
    },
    {
        "name": "rotate_image",
        "description": "Rotate an image. Positive degrees = counter-clockwise. Common: 90, 180, 270.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "degrees": {"type": "integer", "description": "Rotation angle. 90=90° CCW, 270=90° CW, 180=upside down."},
                "output": {"type": "string"}
            },
            "required": ["path", "degrees"]
        }
    },
```

**brain.py — new group:**

```python
    "image_edit": frozenset({
        "resize_image", "crop_image", "convert_image", "compress_image", "rotate_image",
    }),
```

**brain.py — triggers:**

```python
    "image_edit": ["resize image", "crop image", "compress image", "convert image",
                   "rotate image", "make image smaller", "image to jpg", "image to png",
                   "flip image", "shrink image", "اعدل الصورة", "قص الصورة"],
```

**brain.py — dispatch:**

```python
            # ── Image editing ─────────────────────────────────────────────────
            elif name == "resize_image":
                from tools.image_edit_tool import resize_image
                return resize_image(tool_input["path"], tool_input["width"], tool_input.get("height"), tool_input.get("output"))
            elif name == "crop_image":
                from tools.image_edit_tool import crop_image
                return crop_image(tool_input["path"], tool_input["left"], tool_input["top"], tool_input["right"], tool_input["bottom"], tool_input.get("output"))
            elif name == "convert_image":
                from tools.image_edit_tool import convert_image
                return convert_image(tool_input["path"], tool_input["output_path"])
            elif name == "compress_image":
                from tools.image_edit_tool import compress_image
                return compress_image(tool_input["path"], tool_input.get("quality", 75), tool_input.get("output"))
            elif name == "rotate_image":
                from tools.image_edit_tool import rotate_image
                return rotate_image(tool_input["path"], tool_input["degrees"], tool_input.get("output"))
```

**brain.py — SYSTEM_PROMPT:**

```
Image editing (existing files): resize_image, crop_image, convert_image, compress_image, rotate_image.
Note: image_tool.py tools (generate_image, etc.) are for DALL-E generation. These tools are for editing *existing* image files on disk.
"resize this image to 800px" → resize_image. "convert to JPG" → convert_image. "compress for email" → compress_image(quality=60).
```

**Verification:**
```python
python -c "
import os
from tools.image_edit_tool import resize_image, compress_image
# Test with a generated image if one exists
imgs = [f for f in os.listdir('data/generated_images') if f.endswith('.png')]
if imgs:
    path = f'data/generated_images/{imgs[0]}'
    print(resize_image(path, 100, output='data/test_resized.png'))
    print(compress_image('data/test_resized.png', quality=60, output='data/test_compressed.jpg'))
    os.unlink('data/test_resized.png')
    os.unlink('data/test_compressed.jpg')
else:
    print('No test images available — create one with generate_image first')
"
```

---

## Task 4 — Unit Conversion (`tools/unit_tool.py`)

**Files:**
- Create: `tools/unit_tool.py`
- Modify: `core/brain.py`
- Dependencies: none (pure Python)

**Functions:**

| Function | Signature | What it does |
|---|---|---|
| `convert_units` | `(value: float, from_unit: str, to_unit: str) -> str` | Convert between units across all categories |
| `list_unit_categories` | `() -> str` | Show all supported categories and units |

**`tools/unit_tool.py` — complete implementation:**

```python
"""
Unit conversion for El Fager.

Convert between temperature, weight, distance, volume, speed, area, data size, time.
Pure Python — no external dependencies.
"""

_CONVERSIONS = {
    # All values convert TO the base unit (SI or common standard)
    # Temperature is handled separately (non-multiplicative)

    # Length — base: meter
    "mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0,
    "inch": 0.0254, "in": 0.0254, "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
    "yd": 0.9144, "yard": 0.9144, "mi": 1609.344, "mile": 1609.344, "miles": 1609.344,
    "nm": 1852.0, "nautical mile": 1852.0,

    # Weight/Mass — base: kilogram
    "mg": 0.000001, "g": 0.001, "kg": 1.0, "tonne": 1000.0, "t": 1000.0,
    "oz": 0.028349523, "lb": 0.45359237, "lbs": 0.45359237, "pound": 0.45359237,
    "stone": 6.35029, "ton": 907.185, "short ton": 907.185,

    # Volume — base: liter
    "ml": 0.001, "cl": 0.01, "dl": 0.1, "l": 1.0, "liter": 1.0, "litre": 1.0,
    "m3": 1000.0, "gallon": 3.78541, "gal": 3.78541, "quart": 0.946353,
    "pint": 0.473176, "cup": 0.236588, "fl oz": 0.029574, "tbsp": 0.014787, "tsp": 0.004929,

    # Speed — base: m/s
    "m/s": 1.0, "km/h": 0.27778, "kph": 0.27778, "mph": 0.44704,
    "knot": 0.514444, "ft/s": 0.3048,

    # Area — base: m²
    "mm2": 0.000001, "cm2": 0.0001, "m2": 1.0, "km2": 1000000.0,
    "in2": 0.00064516, "ft2": 0.092903, "yd2": 0.836127,
    "acre": 4046.86, "hectare": 10000.0, "ha": 10000.0, "mi2": 2589988.0,

    # Data — base: byte
    "b": 0.125, "bit": 0.125, "byte": 1.0, "B": 1.0,
    "kb": 1000.0, "mb": 1000000.0, "gb": 1e9, "tb": 1e12, "pb": 1e15,
    "kib": 1024.0, "mib": 1048576.0, "gib": 1073741824.0, "tib": 1099511627776.0,

    # Time — base: second
    "ms": 0.001, "s": 1.0, "sec": 1.0, "second": 1.0,
    "min": 60.0, "minute": 60.0, "hr": 3600.0, "hour": 3600.0,
    "day": 86400.0, "week": 604800.0, "month": 2592000.0, "year": 31536000.0,

    # Pressure — base: Pascal
    "pa": 1.0, "kpa": 1000.0, "mpa": 1000000.0,
    "bar": 100000.0, "psi": 6894.76, "atm": 101325.0, "mmhg": 133.322, "torr": 133.322,
}

# Temperature — special case (not multiplicative)
_TEMP_UNITS = {"c", "celsius", "f", "fahrenheit", "k", "kelvin"}


def _to_celsius(value: float, unit: str) -> float:
    u = unit.lower()
    if u in ("c", "celsius"):
        return value
    elif u in ("f", "fahrenheit"):
        return (value - 32) * 5 / 9
    elif u in ("k", "kelvin"):
        return value - 273.15
    raise ValueError(f"Unknown temperature unit: {unit}")


def _from_celsius(value: float, unit: str) -> float:
    u = unit.lower()
    if u in ("c", "celsius"):
        return value
    elif u in ("f", "fahrenheit"):
        return value * 9 / 5 + 32
    elif u in ("k", "kelvin"):
        return value + 273.15
    raise ValueError(f"Unknown temperature unit: {unit}")


def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    """Convert value from one unit to another across any supported category."""
    try:
        fu = from_unit.lower().strip()
        tu = to_unit.lower().strip()

        # Temperature (special path)
        if fu in _TEMP_UNITS or tu in _TEMP_UNITS:
            celsius = _to_celsius(value, fu)
            result = _from_celsius(celsius, tu)
            return f"{value} {from_unit} = {result:.4g} {to_unit}"

        # Multiplicative units
        if fu not in _CONVERSIONS:
            return f"[convert_units failed: unknown unit '{from_unit}'. Call list_unit_categories to see supported units.]"
        if tu not in _CONVERSIONS:
            return f"[convert_units failed: unknown unit '{to_unit}'. Call list_unit_categories to see supported units.]"

        # Check same category heuristic: converting to base and back must make sense
        base_value = value * _CONVERSIONS[fu]
        result = base_value / _CONVERSIONS[tu]
        return f"{value} {from_unit} = {result:.6g} {to_unit}"
    except Exception as e:
        return f"[convert_units failed: {e}]"


def list_unit_categories() -> str:
    """List all supported unit categories and example units."""
    return """\
Supported unit categories:

Temperature:  C/Celsius, F/Fahrenheit, K/Kelvin
Length:       mm, cm, m, km, in/inch, ft/foot, yd/yard, mi/mile, nm (nautical mile)
Weight/Mass:  mg, g, kg, tonne, oz, lb/lbs, stone, ton
Volume:       ml, cl, l/liter, m3, gallon/gal, quart, pint, cup, fl oz, tbsp, tsp
Speed:        m/s, km/h/kph, mph, knot, ft/s
Area:         mm2, cm2, m2, km2, in2, ft2, yd2, acre, hectare/ha, mi2
Data:         bit/b, byte/B, kb, mb, gb, tb, pb, kib, mib, gib, tib
Time:         ms, s/sec, min, hr/hour, day, week, month, year
Pressure:     pa, kpa, mpa, bar, psi, atm, mmhg/torr

Usage: convert_units(value=100, from_unit="km", to_unit="miles")"""
```

**brain.py — TOOLS list:**

```python
    # ── Unit Conversion ───────────────────────────────────────────────────────
    {
        "name": "convert_units",
        "description": "Convert between units: temperature (C/F/K), length (m/km/mi/ft), weight (kg/lb/oz), volume (l/gal/ml), speed (km/h/mph), area, data size (GB/MB), time, pressure. More comprehensive than convert_currency.",
        "input_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "from_unit": {"type": "string", "description": "Source unit, e.g. 'km', 'F', 'lb', 'GB'"},
                "to_unit": {"type": "string", "description": "Target unit, e.g. 'miles', 'C', 'kg', 'MB'"}
            },
            "required": ["value", "from_unit", "to_unit"]
        }
    },
    {
        "name": "list_unit_categories",
        "description": "Show all unit categories and unit names supported by convert_units.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
```

**brain.py — group + triggers:**

```python
    "units": frozenset({"convert_units", "list_unit_categories"}),
```

```python
    "units": ["convert", "how many", "how much is", "degrees", "celsius", "fahrenheit",
              "kilometers to miles", "kg to lbs", "lbs to kg", "meters to feet",
              "temperature", "inches", "gallons", "megabytes", "gigabytes",
              "تحويل", "درجة حرارة"],
```

**brain.py — dispatch:**

```python
            # ── Unit conversion ───────────────────────────────────────────────
            elif name == "convert_units":
                from tools.unit_tool import convert_units
                return convert_units(tool_input["value"], tool_input["from_unit"], tool_input["to_unit"])
            elif name == "list_unit_categories":
                from tools.unit_tool import list_unit_categories
                return list_unit_categories()
```

**brain.py — SYSTEM_PROMPT:**

```
Unit conversion: convert_units, list_unit_categories.
"100km in miles" → convert_units(100, "km", "miles"). "37C in Fahrenheit" → convert_units(37, "C", "F"). "how many GB in 1TB?" → convert_units(1, "tb", "gb").
Covers: temperature, length, weight, volume, speed, area, data size, time, pressure.
```

**Verification:**
```python
python -c "
from tools.unit_tool import convert_units
print(convert_units(100, 'km', 'miles'))
print(convert_units(37, 'C', 'F'))
print(convert_units(1, 'tb', 'gb'))
print(convert_units(70, 'kg', 'lbs'))
"
```

---

## Task 5 — Local Git Operations (`tools/git_tool.py`)

**Files:**
- Create: `tools/git_tool.py`
- Modify: `core/brain.py`
- Dependencies: git CLI v2.53 (already installed)

**Functions:**

| Function | Signature | What it does |
|---|---|---|
| `git_status` | `(repo_path: str = ".") -> str` | Short status of working tree |
| `git_log` | `(repo_path: str = ".", n: int = 10) -> str` | Last N commits with hash, author, date, message |
| `git_diff` | `(repo_path: str = ".", staged: bool = False) -> str` | Unstaged or staged diff |
| `git_add` | `(paths: list, repo_path: str = ".") -> str` | Stage files for commit |
| `git_commit` | `(message: str, repo_path: str = ".") -> str` | Commit staged changes |
| `git_push` | `(repo_path: str = ".", remote: str = "origin", branch: str = "") -> str` | Push to remote |
| `git_pull` | `(repo_path: str = ".", remote: str = "origin") -> str` | Pull latest from remote |

**`tools/git_tool.py` — complete implementation:**

```python
"""
Local git operations for El Fager.

Run git commands on any local repository using the system git CLI.
All paths default to the current directory (relative to where El Fager is run).
"""

import subprocess
import os


def _run_git(args: list, cwd: str) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "git command timed out after 30s"
    except FileNotFoundError:
        return -1, "", "git not found — ensure git is installed and in PATH"
    except Exception as e:
        return -1, "", str(e)


def _resolve_repo(repo_path: str) -> str:
    """Expand ~ and resolve relative paths."""
    return os.path.abspath(os.path.expanduser(repo_path))


def git_status(repo_path: str = ".") -> str:
    """Show the working tree status (modified, staged, untracked files)."""
    try:
        cwd = _resolve_repo(repo_path)
        rc, out, err = _run_git(["status", "--short", "--branch"], cwd)
        if rc != 0:
            return f"[git_status failed: {err or 'not a git repository'}]"
        return out or "Nothing to commit — working tree clean."
    except Exception as e:
        return f"[git_status failed: {e}]"


def git_log(repo_path: str = ".", n: int = 10) -> str:
    """Show the last N commits (hash, author, date, message)."""
    try:
        cwd = _resolve_repo(repo_path)
        fmt = "%h  %an  %ar  %s"
        rc, out, err = _run_git(["log", f"-{n}", f"--pretty=format:{fmt}"], cwd)
        if rc != 0:
            return f"[git_log failed: {err or 'no commits or not a git repository'}]"
        if not out:
            return "No commits yet."
        return f"Last {n} commits ({cwd}):\n" + out
    except Exception as e:
        return f"[git_log failed: {e}]"


def git_diff(repo_path: str = ".", staged: bool = False) -> str:
    """Show changes — unstaged by default, staged if staged=True."""
    try:
        cwd = _resolve_repo(repo_path)
        args = ["diff"]
        if staged:
            args.append("--staged")
        args += ["--stat", "--no-color"]
        rc, out, err = _run_git(args, cwd)
        if rc != 0:
            return f"[git_diff failed: {err}]"
        if not out:
            label = "staged" if staged else "unstaged"
            return f"No {label} changes."
        # Also get detailed diff (truncated)
        rc2, full, _ = _run_git(["diff"] + (["--staged"] if staged else []) + ["--no-color"], cwd)
        if full and len(full) > 3000:
            full = full[:3000] + "\n...[truncated]"
        return f"Diff ({cwd}):\n{out}\n\n{full}" if full else f"Diff ({cwd}):\n{out}"
    except Exception as e:
        return f"[git_diff failed: {e}]"


def git_add(paths: list, repo_path: str = ".") -> str:
    """Stage files for the next commit. Use ['.'] to stage everything."""
    try:
        cwd = _resolve_repo(repo_path)
        rc, out, err = _run_git(["add"] + paths, cwd)
        if rc != 0:
            return f"[git_add failed: {err}]"
        # Show what's staged
        rc2, status, _ = _run_git(["status", "--short"], cwd)
        staged = [l for l in (status or "").splitlines() if l.startswith(("A ", "M ", "D ", "R "))]
        return f"Staged: {', '.join(paths)}\nNow staged: {len(staged)} change(s)."
    except Exception as e:
        return f"[git_add failed: {e}]"


def git_commit(message: str, repo_path: str = ".") -> str:
    """Commit staged changes with a message."""
    try:
        cwd = _resolve_repo(repo_path)
        rc, out, err = _run_git(["commit", "-m", message], cwd)
        if rc != 0:
            combined = err or out
            if "nothing to commit" in combined.lower():
                return "Nothing to commit — stage files first with git_add."
            return f"[git_commit failed: {combined}]"
        return out or f"Committed: {message}"
    except Exception as e:
        return f"[git_commit failed: {e}]"


def git_push(repo_path: str = ".", remote: str = "origin", branch: str = "") -> str:
    """Push committed changes to the remote repository."""
    try:
        cwd = _resolve_repo(repo_path)
        args = ["push", remote]
        if branch:
            args.append(branch)
        rc, out, err = _run_git(args, cwd)
        combined = (out + "\n" + err).strip()
        if rc != 0:
            return f"[git_push failed: {combined}]"
        return combined or f"Pushed to {remote}."
    except Exception as e:
        return f"[git_push failed: {e}]"


def git_pull(repo_path: str = ".", remote: str = "origin") -> str:
    """Pull latest changes from remote."""
    try:
        cwd = _resolve_repo(repo_path)
        rc, out, err = _run_git(["pull", remote], cwd)
        combined = (out + "\n" + err).strip()
        if rc != 0:
            return f"[git_pull failed: {combined}]"
        return combined or f"Pulled from {remote}."
    except Exception as e:
        return f"[git_pull failed: {e}]"
```

**brain.py — TOOLS list:**

```python
    # ── Local Git ─────────────────────────────────────────────────────────────
    {
        "name": "git_status",
        "description": "Show local git repository status — modified, staged, and untracked files. repo_path defaults to current directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to the git repo. Defaults to '.' (current dir)."}
            }
        }
    },
    {
        "name": "git_log",
        "description": "Show recent git commit history for a local repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "n": {"type": "integer", "description": "Number of commits to show. Default 10."}
            }
        }
    },
    {
        "name": "git_diff",
        "description": "Show file changes in a local git repo — unstaged by default, or staged if staged=true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "staged": {"type": "boolean", "description": "If true, show staged (--cached) diff. Default false."}
            }
        }
    },
    {
        "name": "git_add",
        "description": "Stage files for git commit. Use paths=['.'] to stage all changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "description": "List of file paths to stage. Use ['.'] for everything."},
                "repo_path": {"type": "string"}
            },
            "required": ["paths"]
        }
    },
    {
        "name": "git_commit",
        "description": "Commit staged changes to the local repository with a message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message"},
                "repo_path": {"type": "string"}
            },
            "required": ["message"]
        }
    },
    {
        "name": "git_push",
        "description": "Push local commits to a remote repository (GitHub, GitLab, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "remote": {"type": "string", "description": "Remote name. Default 'origin'."},
                "branch": {"type": "string", "description": "Branch name. Defaults to current branch."}
            }
        }
    },
    {
        "name": "git_pull",
        "description": "Pull latest changes from a remote repository into the local branch.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "remote": {"type": "string", "description": "Remote name. Default 'origin'."}
            }
        }
    },
```

**brain.py — group + triggers:**

```python
    "git": frozenset({
        "git_status", "git_log", "git_diff", "git_add", "git_commit", "git_push", "git_pull",
    }),
```

```python
    "git": ["git status", "git commit", "git push", "git pull", "git log", "git diff",
            "git add", "commit my changes", "push my code", "what changed in git",
            "stage files", "local repo", "git repo"],
```

**brain.py — dispatch:**

```python
            # ── Local git ─────────────────────────────────────────────────────
            elif name == "git_status":
                from tools.git_tool import git_status
                return git_status(tool_input.get("repo_path", "."))
            elif name == "git_log":
                from tools.git_tool import git_log
                return git_log(tool_input.get("repo_path", "."), tool_input.get("n", 10))
            elif name == "git_diff":
                from tools.git_tool import git_diff
                return git_diff(tool_input.get("repo_path", "."), tool_input.get("staged", False))
            elif name == "git_add":
                from tools.git_tool import git_add
                return git_add(tool_input["paths"], tool_input.get("repo_path", "."))
            elif name == "git_commit":
                from tools.git_tool import git_commit
                return git_commit(tool_input["message"], tool_input.get("repo_path", "."))
            elif name == "git_push":
                from tools.git_tool import git_push
                return git_push(tool_input.get("repo_path", "."), tool_input.get("remote", "origin"), tool_input.get("branch", ""))
            elif name == "git_pull":
                from tools.git_tool import git_pull
                return git_pull(tool_input.get("repo_path", "."), tool_input.get("remote", "origin"))
```

**brain.py — SYSTEM_PROMPT:**

```
Local git: git_status, git_log, git_diff, git_add, git_commit, git_push, git_pull.
"git status" / "what changed?" → git_status. "show commits" → git_log. "commit this" → git_add(['.']) then git_commit(msg). "push my code" → git_push.
repo_path defaults to current directory '.' — Mo must specify the path if working in a different folder.
ALWAYS confirm before git_push — it's a shared-state operation.
```

**Verification** (run from any local git repo path):
```python
python -c "
from tools.git_tool import git_status, git_log
import os
# Test on the El Fager project itself (if it were a git repo)
# or on any local repo Mo has
print(git_status('C:/Users/Mo/Documents'))  # will say 'not a git repository' — that's OK
print('git_tool imports OK')
"
```

---

## Task 6 — Developer Utilities (`tools/dev_utils_tool.py`)

**Files:**
- Create: `tools/dev_utils_tool.py`
- Modify: `core/brain.py`
- Dependencies: stdlib only (hashlib, uuid, base64, urllib, secrets, string) + `pip install qrcode[pil]` for QR codes

**Functions:**

| Function | Signature | What it does |
|---|---|---|
| `hash_text` | `(text: str, algorithm: str = "sha256") -> str` | Hash a string (md5, sha1, sha256, sha512) |
| `encode_base64` | `(text: str) -> str` | Base64 encode a string |
| `decode_base64` | `(encoded: str) -> str` | Base64 decode back to string |
| `url_encode` | `(text: str) -> str` | URL-encode special characters |
| `url_decode` | `(text: str) -> str` | URL-decode percent-encoded text |
| `generate_password` | `(length: int = 16, include_symbols: bool = True) -> str` | Cryptographically secure random password |
| `generate_uuid` | `() -> str` | Generate a UUID4 |
| `generate_qr` | `(text: str, output_path: str = None) -> str` | Generate QR code PNG from any text or URL |

**Install (before creating the file):**
```bash
pip install qrcode[pil]
```

**`tools/dev_utils_tool.py` — complete implementation:**

```python
"""
Developer utility tools for El Fager.

Hash strings, encode/decode Base64 and URLs, generate passwords, UUIDs, and QR codes.
Uses Python stdlib for everything except QR codes (qrcode[pil]).
"""

import hashlib
import base64
import uuid
import secrets
import string
import urllib.parse
import os


def hash_text(text: str, algorithm: str = "sha256") -> str:
    """Hash a string using md5, sha1, sha256, or sha512."""
    try:
        algo = algorithm.lower().replace("-", "")
        supported = {"md5", "sha1", "sha256", "sha512"}
        if algo not in supported:
            return f"[hash_text failed: unknown algorithm '{algorithm}'. Supported: {', '.join(sorted(supported))}]"
        h = hashlib.new(algo, text.encode("utf-8"))
        return f"{algorithm.upper()}: {h.hexdigest()}"
    except Exception as e:
        return f"[hash_text failed: {e}]"


def encode_base64(text: str) -> str:
    """Base64 encode a string."""
    try:
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        return f"Base64: {encoded}"
    except Exception as e:
        return f"[encode_base64 failed: {e}]"


def decode_base64(encoded: str) -> str:
    """Base64 decode a string back to plain text."""
    try:
        decoded = base64.b64decode(encoded.strip()).decode("utf-8")
        return f"Decoded: {decoded}"
    except Exception as e:
        return f"[decode_base64 failed: {e}]"


def url_encode(text: str) -> str:
    """URL-encode a string (percent-encode special characters)."""
    try:
        encoded = urllib.parse.quote(text, safe="")
        return f"URL-encoded: {encoded}"
    except Exception as e:
        return f"[url_encode failed: {e}]"


def url_decode(text: str) -> str:
    """Decode a percent-encoded URL string."""
    try:
        decoded = urllib.parse.unquote(text)
        return f"URL-decoded: {decoded}"
    except Exception as e:
        return f"[url_decode failed: {e}]"


def generate_password(length: int = 16, include_symbols: bool = True) -> str:
    """Generate a cryptographically secure random password."""
    try:
        if length < 4 or length > 128:
            return f"[generate_password failed: length must be 4-128]"
        chars = string.ascii_letters + string.digits
        if include_symbols:
            chars += "!@#$%^&*()-_=+[]{}|;:,.<>?"
        password = "".join(secrets.choice(chars) for _ in range(length))
        return f"Password ({length} chars): {password}"
    except Exception as e:
        return f"[generate_password failed: {e}]"


def generate_uuid() -> str:
    """Generate a random UUID4."""
    try:
        return f"UUID: {uuid.uuid4()}"
    except Exception as e:
        return f"[generate_uuid failed: {e}]"


def generate_qr(text: str, output_path: str = None) -> str:
    """Generate a QR code PNG from text or URL. Saved to data/ if no path given."""
    try:
        import qrcode
        from PIL import Image

        if output_path is None:
            os.makedirs("data", exist_ok=True)
            safe = "".join(c if c.isalnum() else "_" for c in text[:20])
            output_path = f"data/qr_{safe}.png"

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(output_path)
        size_kb = os.path.getsize(output_path) // 1024
        return f"QR code saved: {output_path} ({size_kb} KB) — encodes: {text[:60]}"
    except ImportError:
        return "[generate_qr failed: qrcode not installed. Run: pip install qrcode[pil]]"
    except Exception as e:
        return f"[generate_qr failed: {e}]"
```

**brain.py — TOOLS list:**

```python
    # ── Developer Utilities ───────────────────────────────────────────────────
    {
        "name": "hash_text",
        "description": "Hash a string using md5, sha1, sha256, or sha512. Useful for generating checksums, verifying data integrity, or creating identifiers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "algorithm": {"type": "string", "description": "md5, sha1, sha256, or sha512. Default sha256."}
            },
            "required": ["text"]
        }
    },
    {
        "name": "encode_base64",
        "description": "Base64 encode a string. Used for encoding binary data, API tokens, or embedding data in URLs.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"]
        }
    },
    {
        "name": "decode_base64",
        "description": "Decode a Base64 encoded string back to plain text.",
        "input_schema": {
            "type": "object",
            "properties": {"encoded": {"type": "string"}},
            "required": ["encoded"]
        }
    },
    {
        "name": "url_encode",
        "description": "URL-encode a string — converts special characters to percent-encoding (e.g. spaces → %20).",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"]
        }
    },
    {
        "name": "url_decode",
        "description": "Decode a percent-encoded URL string back to readable text.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"]
        }
    },
    {
        "name": "generate_password",
        "description": "Generate a cryptographically secure random password.",
        "input_schema": {
            "type": "object",
            "properties": {
                "length": {"type": "integer", "description": "Password length 4-128. Default 16."},
                "include_symbols": {"type": "boolean", "description": "Include symbols like !@#$. Default true."}
            }
        }
    },
    {
        "name": "generate_uuid",
        "description": "Generate a random UUID4 — useful for database IDs, API keys, unique identifiers in code.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "generate_qr",
        "description": "Generate a QR code PNG image from any text or URL. Saved to data/ folder.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text or URL to encode in the QR code"},
                "output_path": {"type": "string", "description": "Output PNG path. Auto-named if omitted."}
            },
            "required": ["text"]
        }
    },
```

**brain.py — group + triggers:**

```python
    "dev_utils": frozenset({
        "hash_text", "encode_base64", "decode_base64",
        "url_encode", "url_decode",
        "generate_password", "generate_uuid", "generate_qr",
    }),
```

```python
    "dev_utils": ["hash", "md5", "sha256", "base64", "encode", "decode", "url encode",
                  "url decode", "generate password", "random password", "uuid", "qr code",
                  "qr ", "generate qr", "strong password", "secure password"],
```

**brain.py — dispatch:**

```python
            # ── Developer utilities ───────────────────────────────────────────
            elif name == "hash_text":
                from tools.dev_utils_tool import hash_text
                return hash_text(tool_input["text"], tool_input.get("algorithm", "sha256"))
            elif name == "encode_base64":
                from tools.dev_utils_tool import encode_base64
                return encode_base64(tool_input["text"])
            elif name == "decode_base64":
                from tools.dev_utils_tool import decode_base64
                return decode_base64(tool_input["encoded"])
            elif name == "url_encode":
                from tools.dev_utils_tool import url_encode
                return url_encode(tool_input["text"])
            elif name == "url_decode":
                from tools.dev_utils_tool import url_decode
                return url_decode(tool_input["text"])
            elif name == "generate_password":
                from tools.dev_utils_tool import generate_password
                return generate_password(tool_input.get("length", 16), tool_input.get("include_symbols", True))
            elif name == "generate_uuid":
                from tools.dev_utils_tool import generate_uuid
                return generate_uuid()
            elif name == "generate_qr":
                from tools.dev_utils_tool import generate_qr
                return generate_qr(tool_input["text"], tool_input.get("output_path"))
```

**brain.py — SYSTEM_PROMPT:**

```
Developer utilities: hash_text, encode_base64, decode_base64, url_encode, url_decode, generate_password, generate_uuid, generate_qr.
"hash this string" → hash_text(text, "sha256"). "base64 encode X" → encode_base64. "generate a strong password" → generate_password(length=20).
"make a QR code for this URL" → generate_qr(url). "give me a UUID" → generate_uuid.
```

**Pre-step (install QR library):**
```bash
pip install qrcode[pil]
```

**Verification:**
```python
python -c "
from tools.dev_utils_tool import hash_text, encode_base64, generate_password, generate_uuid, generate_qr
print(hash_text('hello'))
print(encode_base64('hello world'))
print(generate_password(20))
print(generate_uuid())
print(generate_qr('https://example.com'))
import os; [os.unlink(f'data/{f}') for f in os.listdir('data') if f.startswith('qr_')]
"
```

---

## Final Verification (after all 6 tasks)

```python
python -c "
from core.brain import TOOLS, _TOOL_GROUP_NAMES, _GROUP_TRIGGERS
names = {t['name'] for t in TOOLS}
checks = [
    # Task 1
    'create_folder', 'rename_file', 'copy_file', 'move_file', 'delete_file', 'list_folder',
    # Task 2
    'zip_files', 'unzip_archive', 'list_archive', 'add_to_archive',
    # Task 3
    'resize_image', 'crop_image', 'convert_image', 'compress_image', 'rotate_image',
    # Task 4
    'convert_units', 'list_unit_categories',
    # Task 5
    'git_status', 'git_log', 'git_diff', 'git_add', 'git_commit', 'git_push', 'git_pull',
    # Task 6
    'hash_text', 'encode_base64', 'decode_base64', 'url_encode', 'url_decode',
    'generate_password', 'generate_uuid', 'generate_qr',
]
missing = [t for t in checks if t not in names]
print('Missing:', missing or 'none')
print('Total tools:', len(names))
new_groups = ['archive', 'image_edit', 'units', 'git', 'dev_utils']
print('New groups present:', [g for g in new_groups if g in _TOOL_GROUP_NAMES])
"
# Expected: Missing: none, Total tools: ~344
```
