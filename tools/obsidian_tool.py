"""
Obsidian tool — local vault access.

An Obsidian vault is just a folder of Markdown files, so there is no API key.
Vault location is resolved in this order:
  1. OBSIDIAN_VAULT in .env
  2. ~/Documents/Obsidian Vault
  3. ~/OneDrive/Documents/Obsidian Vault

Functions:
  Read:    search_vault, ask_vault, read_note, list_notes
  Write:   create_note, append_to_note, append_to_daily_note
  Manage:  delete_note, rename_note, move_note
  Graph:   get_backlinks, get_outgoing_links, list_vault_tags, search_vault_by_tag
  Index:   index_vault

Notes are Markdown; .canvas files are read for their text nodes. YAML
frontmatter is parsed for properties and tags. All writes stay inside the
vault, and delete_note moves to .trash rather than erasing.
"""

import json
import os
import re
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

_SKIP_DIRS = {".obsidian", ".trash", ".git", ".smart-env"}
_MAX_SCAN = 2000  # notes scanned per literal search

_WIKILINK_RE = re.compile(r"\[\[([^\]\[]+)\]\]")
_TAG_RE = re.compile(r"(?:^|\s)#([A-Za-z0-9_/-]*[A-Za-z_/][A-Za-z0-9_/-]*)")

_NOT_SET_UP = (
    "[Obsidian vault not found — add OBSIDIAN_VAULT=C:\\path\\to\\vault to .env, "
    "or put the vault in Documents\\Obsidian Vault.]"
)


def _vault() -> Path | None:
    """Resolve the vault folder, or None if it can't be found."""
    env = os.getenv("OBSIDIAN_VAULT")
    if env:
        p = Path(env).expanduser()
        return p if p.is_dir() else None

    home = Path.home()
    for candidate in (
        home / "Documents" / "Obsidian Vault",
        home / "OneDrive" / "Documents" / "Obsidian Vault",
    ):
        if candidate.is_dir():
            return candidate
    return None


def _files(root: Path, exts=(".md",)):
    """Yield every note file under root, skipping config folders."""
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in files:
            if f.endswith(exts):
                yield Path(dirpath) / f


def _inside(vault: Path, path: Path) -> bool:
    """True if path stays inside the vault (blocks ../ traversal)."""
    try:
        path.resolve().relative_to(vault.resolve())
        return True
    except ValueError:
        return False


def _rel(vault: Path, note: Path) -> str:
    return note.relative_to(vault).as_posix()


def _resolve(vault: Path, name: str) -> Path | None:
    """Find a note by name, path, or [[wikilink]]. Case-insensitive."""
    name = name.strip().strip("[]").replace("\\", "/")
    name = name.split("|")[0].split("#")[0].strip()
    for ext in (".md", ".canvas"):
        if name.endswith(ext):
            name = name[: -len(ext)]

    for ext in (".md", ".canvas"):
        direct = vault / f"{name}{ext}"
        if direct.is_file() and _inside(vault, direct):
            return direct

    target = name.lower()
    stem_match = None
    for note in _files(vault, (".md", ".canvas")):
        rel = note.relative_to(vault).as_posix()
        rel = rel[: rel.rfind(".")].lower()
        if rel == target:
            return note
        if stem_match is None and note.stem.lower() == target:
            stem_match = note
    return stem_match


def _read(path: Path) -> str:
    """Read a note. .canvas files are flattened to their text nodes."""
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    if path.suffix != ".canvas":
        return raw
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return ""
    parts = []
    for node in data.get("nodes", []):
        if node.get("type") == "text" and node.get("text"):
            parts.append(node["text"])
        elif node.get("type") == "file" and node.get("file"):
            parts.append(f"[[{Path(node['file']).stem}]]")
    return "\n\n".join(parts)


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter into a properties dict and the remaining body."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    body = text[end + 4:].lstrip("\n")

    props: dict = {}
    key = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z0-9_ -]+):\s*(.*)$", line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                props[key] = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
            elif val:
                props[key] = val.strip("\"'")
            else:
                props[key] = []
        elif line.lstrip().startswith("- ") and key is not None:
            value = line.lstrip()[2:].strip().strip("\"'")
            if isinstance(props.get(key), list):
                props[key].append(value)
    return props, body


def _note_tags(text: str) -> set[str]:
    """Tags from frontmatter and from #tags in the body, skipping code fences."""
    props, body = _split_frontmatter(text)
    tags = set()

    raw = props.get("tags") or props.get("tag") or []
    if isinstance(raw, str):
        raw = [t.strip() for t in raw.replace(",", " ").split()]
    for t in raw:
        if t:
            tags.add(str(t).lstrip("#"))

    in_fence = False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            tags.update(_TAG_RE.findall(line))
    return tags


def _link_targets(text: str) -> list[str]:
    """Wikilink targets, stripped of aliases and heading anchors."""
    out = []
    for raw in _WIKILINK_RE.findall(text):
        target = raw.split("|")[0].split("#")[0].strip()
        if target and target not in out:
            out.append(target)
    return out


def _daily_note_rel(vault: Path) -> str:
    """Vault-relative path for today's daily note, honouring Obsidian's config."""
    fmt, folder = "YYYY-MM-DD", ""
    cfg = vault / ".obsidian" / "daily-notes.json"
    try:
        if cfg.is_file():
            data = json.loads(cfg.read_text(encoding="utf-8") or "{}")
            fmt = data.get("format") or fmt
            folder = (data.get("folder") or "").strip("/\\")
    except Exception:
        pass

    py = (fmt.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")
             .replace("HH", "%H").replace("mm", "%M"))
    try:
        name = datetime.now().strftime(py)
    except ValueError:
        name = date.today().isoformat()
    return f"{folder}/{name}" if folder else name


# ── Read ──────────────────────────────────────────────────────────────────────

def search_vault(query: str, n: int = 5) -> str:
    """Literal search over note titles and contents."""
    vault = _vault()
    if vault is None:
        return _NOT_SET_UP

    q = query.lower().strip()
    if not q:
        return "[Obsidian error: empty search query]"

    title_hits, body_hits = [], []
    try:
        for i, note in enumerate(_files(vault, (".md", ".canvas"))):
            if i >= _MAX_SCAN:
                break
            rel = _rel(vault, note)
            if q in note.stem.lower():
                title_hits.append((rel, ""))
                continue
            for line in _read(note).splitlines():
                if q in line.lower():
                    body_hits.append((rel, line.strip()[:120]))
                    break
    except Exception as e:
        return f"[Obsidian error: {e}]"

    hits = (title_hits + body_hits)[:n]
    if not hits:
        return f"No notes found matching '{query}'"

    lines = []
    for i, (rel, snippet) in enumerate(hits, 1):
        lines.append(f"{i}. {rel}" + (f"\n   {snippet}" if snippet else ""))
    return "Obsidian notes found:\n" + "\n".join(lines)


def ask_vault(query: str, n: int = 5) -> str:
    """Meaning-based search — finds relevant notes even without exact wording."""
    vault = _vault()
    if vault is None:
        return _NOT_SET_UP

    from core import obsidian_index

    notes = [(_rel(vault, p), p) for p in _files(vault, (".md",))]
    sync = obsidian_index.sync(notes, vault=str(vault.resolve()))
    if sync["error"] and not sync["added"] and not sync["updated"]:
        return (f"[Obsidian semantic search unavailable: {sync['error']}. "
                f"Falling back to literal search]\n" + search_vault(query, n))

    hits, err = obsidian_index.query(query, n)
    if err:
        return f"[Obsidian index error: {err}]"
    if not hits:
        return f"Nothing in the vault relates to '{query}'"

    lines = []
    for i, hit in enumerate(hits, 1):
        snippet = " ".join(hit["text"].split())[:220]
        score = f" ({hit['score']})" if hit["score"] is not None else ""
        lines.append(f"{i}. {hit['path']}{score}\n   {snippet}")
    return f"Notes related to '{query}':\n" + "\n".join(lines)


def read_note(name: str, max_chars: int = 6000) -> str:
    """Read a note's full text by name, vault path, or wikilink."""
    vault = _vault()
    if vault is None:
        return _NOT_SET_UP

    note = _resolve(vault, name)
    if note is None:
        return f"[Obsidian: no note named '{name}' — try search_vault first]"

    text = _read(note)
    props, body = _split_frontmatter(text)

    header = f"# {note.stem}"
    if props:
        pairs = ", ".join(
            f"{k}: {', '.join(v) if isinstance(v, list) else v}" for k, v in props.items()
        )
        header += f"\n*Properties: {pairs}*"

    if len(body) > max_chars:
        body = body[:max_chars] + "\n[... truncated]"
    if not body.strip():
        return f"{header}\n\n(Note is empty)"
    return f"{header}\n\n{body}"


def list_notes(folder: str = None, n: int = 30) -> str:
    """List notes, most recently modified first."""
    vault = _vault()
    if vault is None:
        return _NOT_SET_UP

    root = vault / folder.strip("/\\") if folder else vault
    if not _inside(vault, root):
        return "[Obsidian error: folder is outside the vault]"
    if not root.is_dir():
        return f"[Obsidian: no folder named '{folder}']"

    try:
        notes = sorted(
            _files(root, (".md", ".canvas")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError as e:
        return f"[Obsidian error: {e}]"

    if not notes:
        return f"No notes in {folder or 'the vault'}"

    lines = [f"{i}. {_rel(vault, note)}" for i, note in enumerate(notes[:n], 1)]
    return f"Notes in {folder or 'vault'} ({len(notes)} total):\n" + "\n".join(lines)


# ── Write ─────────────────────────────────────────────────────────────────────

def create_note(title: str, content: str = "", folder: str = None) -> str:
    """Create a new note. Adds a numeric suffix if the title already exists."""
    vault = _vault()
    if vault is None:
        return _NOT_SET_UP

    safe_title = title.strip().replace("/", "-").replace("\\", "-")
    for ch in '<>:"|?*':
        safe_title = safe_title.replace(ch, "")
    if not safe_title:
        return "[Obsidian error: empty note title]"

    target_dir = vault / folder.strip("/\\") if folder else vault
    if not _inside(vault, target_dir):
        return "[Obsidian error: folder is outside the vault]"

    note = target_dir / f"{safe_title}.md"
    counter = 2
    while note.exists():
        note = target_dir / f"{safe_title} {counter}.md"
        counter += 1

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        note.write_text(content, encoding="utf-8")
    except OSError as e:
        return f"[Obsidian error: {e}]"
    return f"Created Obsidian note '{_rel(vault, note)}'"


def append_to_note(name: str, text: str) -> str:
    """Append a line to a note. Creates the note (and folders) if missing."""
    vault = _vault()
    if vault is None:
        return _NOT_SET_UP

    note = _resolve(vault, name)
    created = False
    if note is None:
        parts = name.strip().replace("\\", "/").split("/")
        title = parts[-1]
        folder = "/".join(parts[:-1]) or None
        result = create_note(title, "", folder)
        if result.startswith("["):
            return result
        note = _resolve(vault, name)
        created = True
        if note is None:
            return f"[Obsidian error: could not create note '{name}']"

    try:
        existing = note.read_text(encoding="utf-8", errors="ignore")
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        with note.open("a", encoding="utf-8") as f:
            f.write(f"{prefix}{text}\n")
    except OSError as e:
        return f"[Obsidian error: {e}]"

    rel = _rel(vault, note)
    return f"Created '{rel}' and added the text" if created else f"Added to '{rel}'"


def append_to_daily_note(text: str) -> str:
    """Append a timestamped bullet to today's daily note."""
    vault = _vault()
    if vault is None:
        return _NOT_SET_UP
    stamp = datetime.now().strftime("%H:%M")
    return append_to_note(_daily_note_rel(vault), f"- {stamp} — {text}")


# ── Manage ────────────────────────────────────────────────────────────────────

def delete_note(name: str) -> str:
    """Move a note to the vault's .trash folder (recoverable, not erased)."""
    vault = _vault()
    if vault is None:
        return _NOT_SET_UP

    note = _resolve(vault, name)
    if note is None:
        return f"[Obsidian: no note named '{name}']"

    trash = vault / ".trash"
    target = trash / note.name
    counter = 2
    while target.exists():
        target = trash / f"{note.stem} {counter}{note.suffix}"
        counter += 1

    rel = _rel(vault, note)
    try:
        trash.mkdir(parents=True, exist_ok=True)
        note.rename(target)
    except OSError as e:
        return f"[Obsidian error: {e}]"
    return f"Moved '{rel}' to the vault trash (.trash/{target.name}) — recoverable"


def rename_note(name: str, new_title: str) -> str:
    """Rename a note and repoint every [[wikilink]] in the vault to it."""
    vault = _vault()
    if vault is None:
        return _NOT_SET_UP

    note = _resolve(vault, name)
    if note is None:
        return f"[Obsidian: no note named '{name}']"

    safe = new_title.strip().replace("/", "-").replace("\\", "-")
    for ch in '<>:"|?*':
        safe = safe.replace(ch, "")
    if not safe:
        return "[Obsidian error: empty new title]"

    target = note.with_name(f"{safe}{note.suffix}")
    if target.exists():
        return f"[Obsidian: a note named '{safe}' already exists there]"

    old_stem, old_rel = note.stem, _rel(vault, note)
    try:
        note.rename(target)
    except OSError as e:
        return f"[Obsidian error: {e}]"

    relinked = 0
    for other in _files(vault, (".md",)):
        try:
            text = other.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "[[" not in text:
            continue

        def repoint(m):
            inner = m.group(1)
            target_part = inner.split("|")[0].split("#")[0].strip()
            if target_part.lower() != old_stem.lower():
                return m.group(0)
            return "[[" + safe + inner[len(target_part):] + "]]"

        updated = _WIKILINK_RE.sub(repoint, text)
        if updated != text:
            try:
                other.write_text(updated, encoding="utf-8")
                relinked += 1
            except OSError:
                pass

    suffix = f", updated links in {relinked} note{'s' if relinked != 1 else ''}" if relinked else ""
    return f"Renamed '{old_rel}' to '{_rel(vault, target)}'{suffix}"


def move_note(name: str, folder: str) -> str:
    """Move a note to another folder. Wikilinks are name-based, so they survive."""
    vault = _vault()
    if vault is None:
        return _NOT_SET_UP

    note = _resolve(vault, name)
    if note is None:
        return f"[Obsidian: no note named '{name}']"

    target_dir = vault / folder.strip("/\\") if folder else vault
    if not _inside(vault, target_dir):
        return "[Obsidian error: folder is outside the vault]"

    target = target_dir / note.name
    if target.exists():
        return f"[Obsidian: '{note.name}' already exists in {folder}]"

    old_rel = _rel(vault, note)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        note.rename(target)
    except OSError as e:
        return f"[Obsidian error: {e}]"
    return f"Moved '{old_rel}' to '{_rel(vault, target)}'"


# ── Graph ─────────────────────────────────────────────────────────────────────

def get_backlinks(name: str, n: int = 20) -> str:
    """List notes that link to this one."""
    vault = _vault()
    if vault is None:
        return _NOT_SET_UP

    note = _resolve(vault, name)
    stem = note.stem if note else name.strip().strip("[]")
    target = stem.lower()

    hits = []
    for other in _files(vault, (".md", ".canvas")):
        if note is not None and other == note:
            continue
        text = _read(other)
        if "[[" not in text:
            continue
        if any(t.lower() == target for t in _link_targets(text)):
            hits.append(_rel(vault, other))

    if not hits:
        return f"No notes link to '{stem}'"
    lines = [f"{i}. {rel}" for i, rel in enumerate(hits[:n], 1)]
    return f"Notes linking to '{stem}' ({len(hits)}):\n" + "\n".join(lines)


def get_outgoing_links(name: str) -> str:
    """List the notes this one links to, flagging links with no note yet."""
    vault = _vault()
    if vault is None:
        return _NOT_SET_UP

    note = _resolve(vault, name)
    if note is None:
        return f"[Obsidian: no note named '{name}']"

    targets = _link_targets(_read(note))
    if not targets:
        return f"'{note.stem}' has no outgoing links"

    lines = []
    for i, t in enumerate(targets, 1):
        exists = _resolve(vault, t) is not None
        lines.append(f"{i}. {t}" + ("" if exists else "  (no note yet)"))
    return f"'{note.stem}' links to:\n" + "\n".join(lines)


def list_vault_tags(n: int = 40) -> str:
    """List every tag in the vault with how many notes use it."""
    vault = _vault()
    if vault is None:
        return _NOT_SET_UP

    counts: dict[str, int] = {}
    for note in _files(vault, (".md",)):
        for tag in _note_tags(_read(note)):
            counts[tag] = counts.get(tag, 0) + 1

    if not counts:
        return "No tags in the vault yet"
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    lines = [f"#{tag} ({count})" for tag, count in ranked]
    return f"Vault tags ({len(counts)}):\n" + ", ".join(lines)


def search_vault_by_tag(tag: str, n: int = 20) -> str:
    """List notes carrying a tag, in frontmatter or body."""
    vault = _vault()
    if vault is None:
        return _NOT_SET_UP

    want = tag.strip().lstrip("#").lower()
    if not want:
        return "[Obsidian error: empty tag]"

    hits = []
    for note in _files(vault, (".md",)):
        tags = {t.lower() for t in _note_tags(_read(note))}
        if want in tags or any(t.startswith(want + "/") for t in tags):
            hits.append(_rel(vault, note))

    if not hits:
        return f"No notes tagged #{want}"
    lines = [f"{i}. {rel}" for i, rel in enumerate(hits[:n], 1)]
    return f"Notes tagged #{want} ({len(hits)}):\n" + "\n".join(lines)


# ── Index ─────────────────────────────────────────────────────────────────────

def index_vault(rebuild: bool = False) -> str:
    """Refresh the semantic index. Runs automatically before ask_vault."""
    vault = _vault()
    if vault is None:
        return _NOT_SET_UP

    from core import obsidian_index

    notes = [(_rel(vault, p), p) for p in _files(vault, (".md",))]
    result = obsidian_index.sync(notes, vault=str(vault.resolve()), rebuild=rebuild)
    if result["error"]:
        return f"[Obsidian index error: {result['error']}]"

    stats = obsidian_index.stats()
    changed = (f"{result['added']} added, {result['updated']} updated, "
               f"{result['removed']} removed")
    return (f"Vault index {'rebuilt' if rebuild else 'up to date'} — {changed}. "
            f"{stats['notes']} notes indexed ({stats['chunks']} chunks).")
