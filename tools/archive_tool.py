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

        for path in paths:
            if not Path(path).exists():
                return f"[zip_files failed: path not found: {path}]"

        added = 0
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in paths:
                p = Path(path)
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

        return f"Extracted {len(names)} files -> {output_dir}"
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
