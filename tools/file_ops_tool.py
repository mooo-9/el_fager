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
        return f"Renamed: '{p.name}' -> '{new_name}' in {p.parent}"
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
            return f"Folder copied: {src} -> {dst}"
        else:
            result = shutil.copy2(str(s), str(d))
            size_kb = Path(result).stat().st_size // 1024
            return f"File copied: {src} -> {result} ({size_kb} KB)"
    except Exception as e:
        return f"[copy_file failed: {e}]"


def move_file(src: str, dst: str) -> str:
    """Move or rename a file or folder to a new path."""
    try:
        if not Path(src).exists():
            return f"[move_file failed: source not found: {src}]"
        result = shutil.move(src, dst)
        return f"Moved: {src} -> {result}"
    except Exception as e:
        return f"[move_file failed: {e}]"


def delete_file(path: str) -> str:
    """Delete a file. For folders, deletes recursively."""
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

        all_entries = list(p.iterdir())
        if len(all_entries) > 50:
            lines.append(f"  ... and {len(all_entries) - 50} more (showing first 50)")
        return "\n".join(lines)
    except Exception as e:
        return f"[list_folder failed: {e}]"
