"""Crash-safe file writes.

Path.write_text() truncates the file and then writes into it, so a crash or a
power cut between those two steps leaves a truncated file on disk. That is
worse than it sounds here: every loader in this codebase ends in
`except Exception: return {}`, so a half-written trades.json does not raise —
it reports zero trades, and the caller believes it.

write() removes that window. The data goes to a temporary file in the same
directory, is flushed to the platter, and is then moved into place with
os.replace(), which is atomic on both Windows and POSIX. A reader sees either
the whole old file or the whole new one, never a fragment.
"""
import os
import tempfile
from pathlib import Path


def write(path, data: str, encoding: str = "utf-8") -> None:
    """Replace path's contents with data, atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Same directory as the target: os.replace cannot cross a filesystem.
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
