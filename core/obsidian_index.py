"""
Semantic index over the Obsidian vault.

A second ChromaDB collection alongside core.memory's — same persist dir and
embedding model, but kept separate so notes never pollute conversation memory.

Sync is incremental: notes are re-embedded only when their mtime changes, so
calling sync() before every query is cheap once the vault is indexed.

All operations are non-fatal — failures return a message, never raise.
"""

import json
import os
import re
from pathlib import Path
from core import atomic

_COLLECTION = "obsidian_vault"
_CHUNK_CHARS = 800
_BATCH = 100

_collection = None
_load_error: str | None = None


def _get_collection():
    """Lazily open the vault collection. Returns None if ChromaDB is unusable."""
    global _collection, _load_error
    if _collection is not None:
        return _collection
    try:
        import chromadb
        from chromadb.utils import embedding_functions

        persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")
        os.makedirs(persist_dir, exist_ok=True)
        client = chromadb.PersistentClient(path=persist_dir)
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        _collection = client.get_or_create_collection(
            name=_COLLECTION,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        return _collection
    except Exception as e:
        _load_error = str(e)
        print(f"[El Fager] Obsidian index unavailable (non-fatal): {e}")
        return None


def _state_path() -> Path:
    """State lives beside the Chroma store it describes, so the two can't drift."""
    persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")
    return Path(persist_dir) / "obsidian_index.json"


def _load_state() -> dict:
    """Returns {"vault": str, "notes": {rel: mtime}}."""
    try:
        path = _state_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "notes" in data:
                return data
    except Exception:
        pass
    return {"vault": "", "notes": {}}


def _save_state(state: dict) -> None:
    try:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic.write(path,
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[El Fager] Obsidian index state save failed: {e}")


def _strip_frontmatter(text: str) -> str:
    """Drop the YAML delimiters so '---' lines aren't embedded as content."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return (text[3:end].strip("\n") + "\n\n" + text[end + 4:].lstrip("\n")).strip()


def _chunk(text: str) -> list[str]:
    """Split note text into ~_CHUNK_CHARS pieces, breaking on blank lines."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", _strip_frontmatter(text)) if b.strip()]
    chunks, current = [], ""
    for block in blocks:
        if len(current) + len(block) + 2 <= _CHUNK_CHARS:
            current = f"{current}\n\n{block}" if current else block
        else:
            if current:
                chunks.append(current)
            while len(block) > _CHUNK_CHARS:
                chunks.append(block[:_CHUNK_CHARS])
                block = block[_CHUNK_CHARS:]
            current = block
    if current:
        chunks.append(current)
    return chunks


def _delete_path(col, rel: str) -> None:
    try:
        col.delete(where={"path": rel})
    except Exception as e:
        print(f"[El Fager] Obsidian index delete failed for {rel}: {e}")


def sync(notes: list[tuple[str, Path]], vault: str = "", rebuild: bool = False) -> dict:
    """
    Bring the index in line with the vault.

    notes: list of (vault-relative path, absolute Path) pairs.
    vault: absolute vault path — if it differs from the indexed one, the index
           is rebuilt so notes from a previous vault can't linger as ghost hits.
    Returns {"added": n, "updated": n, "removed": n, "error": str|None}.
    """
    result = {"added": 0, "updated": 0, "removed": 0, "error": None}
    col = _get_collection()
    if col is None:
        result["error"] = _load_error or "ChromaDB unavailable"
        return result

    previous = _load_state()
    if vault and previous.get("vault") and previous["vault"] != vault:
        rebuild = True

    if rebuild:
        for rel in previous.get("notes", {}):
            _delete_path(col, rel)
        state = {}
    else:
        state = dict(previous.get("notes", {}))

    seen = set()
    docs, ids, metas = [], [], []

    def flush():
        if not docs:
            return
        try:
            col.add(documents=list(docs), ids=list(ids), metadatas=list(metas))
        except Exception as e:
            result["error"] = str(e)
            print(f"[El Fager] Obsidian index add failed: {e}")
        docs.clear(); ids.clear(); metas.clear()

    for rel, path in notes:
        seen.add(rel)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if state.get(rel) == mtime:
            continue

        is_update = rel in state
        if is_update:
            _delete_path(col, rel)

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        pieces = _chunk(text)
        if not pieces:
            state[rel] = mtime
            continue

        for i, piece in enumerate(pieces):
            # Title rides along in every chunk so a note is findable by its
            # subject even when the body never repeats it.
            docs.append(f"{path.stem}: {piece}")
            ids.append(f"{rel}::{i}")
            metas.append({"path": rel, "title": path.stem})
            if len(docs) >= _BATCH:
                flush()

        state[rel] = mtime
        result["updated" if is_update else "added"] += 1

    flush()

    for rel in [r for r in state if r not in seen]:
        _delete_path(col, rel)
        state.pop(rel, None)
        result["removed"] += 1

    _save_state({"vault": vault or previous.get("vault", ""), "notes": state})
    return result


def query(text: str, n: int = 5) -> tuple[list[dict], str | None]:
    """Semantic search. Returns (hits, error) where each hit is
    {"path": str, "title": str, "text": str, "score": float}."""
    col = _get_collection()
    if col is None:
        return [], _load_error or "ChromaDB unavailable"
    try:
        count = col.count()
        if count == 0:
            return [], None
        res = col.query(query_texts=[text], n_results=min(n, count))
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0] or [None] * len(docs)
        hits = []
        for doc, meta, dist in zip(docs, metas, dists):
            hits.append({
                "path": meta.get("path", "?"),
                "title": meta.get("title", "?"),
                "text": doc,
                "score": round(1 - dist, 3) if dist is not None else None,
            })
        return hits, None
    except Exception as e:
        return [], str(e)


def stats() -> dict:
    """Index size, for reporting."""
    col = _get_collection()
    state = _load_state()
    chunks = None
    if col is not None:
        try:
            chunks = col.count()
        except Exception:
            pass
    return {"notes": len(state.get("notes", {})), "chunks": chunks, "error": _load_error}
