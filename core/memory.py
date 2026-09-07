import hashlib
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from core import atomic


_FACTS_FILE = Path(__file__).parent.parent / "data" / "facts.json"
_MAX_FACTS = 300  # facts.json growth bound — oldest non-deadline facts drop first


class Memory:
    """
    Two-layer memory for El Fager:
      Layer 1: ChromaDB vector store of conversation summaries
      Layer 2: Explicit facts JSON store for persistent personal info
    All operations are non-fatal — exceptions are logged, never raised.
    _setup() runs in a background thread so it never blocks Qt startup.
    """

    def __init__(self):
        self._collection = None
        self._ready = False
        self._failed = False
        threading.Thread(target=self._setup, daemon=True).start()

    @property
    def degraded(self) -> bool:
        """True when vector-memory init finished and FAILED (vs still loading).
        Surfaced in the UI so a broken ChromaDB never fails silently again."""
        return self._failed

    def _setup(self):
        try:
            import chromadb
            from chromadb.utils import embedding_functions

            persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")
            os.makedirs(persist_dir, exist_ok=True)

            client = chromadb.PersistentClient(path=persist_dir)

            ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )

            self._collection = client.get_or_create_collection(
                name="el_fager_memory",
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"},
            )
            self._ready = True
            print(f"[El Fager] Memory ready ({self._collection.count()} entries).")

        except Exception as e:
            print(f"[El Fager] Memory init failed (non-fatal): {e}")
            self._ready = False
            self._failed = True

    # ── Layer 1: ChromaDB conversation summaries ──────────────────────────

    def store_conversation_summary(self, user_input: str, assistant_response: str):
        if not self._ready or self._collection is None:
            return
        try:
            summary = f"Mo: {user_input}\nEl Fager: {assistant_response}"
            uid = hashlib.md5(
                f"{datetime.now().isoformat()}{user_input[:30]}".encode()
            ).hexdigest()

            self._collection.add(
                documents=[summary],
                ids=[uid],
                metadatas=[{
                    "timestamp": datetime.now().isoformat(),
                    "preview": user_input[:100],
                }],
            )
        except Exception as e:
            print(f"[El Fager] Memory store failed (non-fatal): {e}")

    def get_recent_context(self, query: str, n_results: int = 5) -> str:
        """
        Query ChromaDB for relevant past exchanges.
        Returns a joined string to inject into the system prompt.
        """
        if not self._ready or self._collection is None:
            return ""
        try:
            count = self._collection.count()
            if count == 0:
                return ""

            results = self._collection.query(
                query_texts=[query],
                n_results=min(n_results, count),
            )
            docs: list[str] = results.get("documents", [[]])[0]
            return "\n---\n".join(docs) if docs else ""

        except Exception as e:
            print(f"[El Fager] Memory retrieve failed (non-fatal): {e}")
            return ""

    # ── Layer 2: Explicit facts store ────────────────────────────────────

    def _load_facts(self) -> dict:
        try:
            if _FACTS_FILE.exists():
                return json.loads(_FACTS_FILE.read_text(encoding="utf-8"))
            return {"facts": []}
        except Exception:
            return {"facts": []}

    def _save_facts(self, data: dict) -> None:
        try:
            _FACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            atomic.write(_FACTS_FILE,
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            print(f"[El Fager] Facts save failed: {e}")

    def store_fact(self, content: str, category: str = "other") -> str:
        try:
            data = self._load_facts()
            data["facts"].append({
                "id": str(uuid.uuid4()),
                "category": category,
                "content": content,
                "created_at": datetime.now().isoformat(),
                "source": "explicit",
            })
            # Growth bound: drop the oldest non-deadline facts past the cap.
            if len(data["facts"]) > _MAX_FACTS:
                facts = sorted(data["facts"], key=lambda f: f.get("created_at", ""))
                for f in facts:
                    if len(data["facts"]) <= _MAX_FACTS:
                        break
                    if f.get("category") != "deadline":
                        data["facts"].remove(f)
            self._save_facts(data)
            return f"Noted: {content}"
        except Exception as e:
            print(f"[El Fager] store_fact failed: {e}")
            return f"[store_fact failed: {e}]"

    def get_all_facts(self, category: str = None) -> list:
        try:
            data = self._load_facts()
            facts = data.get("facts", [])
            if category:
                facts = [f for f in facts if f.get("category") == category]
            return facts
        except Exception:
            return []

    def delete_fact(self, fact_id: str) -> str:
        try:
            data = self._load_facts()
            original = len(data["facts"])
            data["facts"] = [f for f in data["facts"] if f.get("id") != fact_id]
            if len(data["facts"]) == original:
                return "Fact not found"
            self._save_facts(data)
            return "Forgotten"
        except Exception as e:
            return f"[delete_fact failed: {e}]"

    def search_facts(self, query: str) -> list:
        try:
            data = self._load_facts()
            q = query.lower()
            return [f for f in data.get("facts", []) if q in f.get("content", "").lower()]
        except Exception:
            return []

    def format_facts_for_prompt(self) -> str:
        try:
            facts = self.get_all_facts()
            if not facts:
                return ""
            facts.sort(key=lambda f: f.get("created_at", ""), reverse=True)
            lines = [f"- [{f['category']}] {f['content']}" for f in facts]
            header = "What I know about Mo:"
            result = header + "\n" + "\n".join(lines)
            if len(result) > 1500:
                while len(result) > 1500 and lines:
                    lines.pop()
                result = header + "\n" + "\n".join(lines)
            return result
        except Exception:
            return ""

    def forget_topic(self, topic: str) -> str:
        removed = 0

        try:
            data = self._load_facts()
            topic_lower = topic.lower()
            before = len(data["facts"])
            data["facts"] = [
                f for f in data["facts"]
                if topic_lower not in f.get("content", "").lower()
            ]
            removed += before - len(data["facts"])
            self._save_facts(data)
        except Exception as e:
            print(f"[El Fager] forget_topic facts error: {e}")

        try:
            if self._ready and self._collection is not None:
                count = self._collection.count()
                if count > 0:
                    results = self._collection.query(
                        query_texts=[topic],
                        n_results=min(10, count),
                    )
                    ids = results.get("ids", [[]])[0]
                    if ids:
                        self._collection.delete(ids=ids)
                        removed += len(ids)
        except Exception as e:
            print(f"[El Fager] forget_topic chroma error: {e}")

        if removed == 0:
            return f"Nothing found about '{topic}' to forget"
        return f"Forgotten everything about '{topic}' ({removed} item{'s' if removed != 1 else ''} removed)"

    def get_memory_summary(self) -> str:
        parts = []

        facts_text = self.format_facts_for_prompt()
        if facts_text:
            parts.append(facts_text)

        try:
            if self._ready and self._collection is not None and self._collection.count() > 0:
                results = self._collection.get(
                    limit=50,
                    include=["metadatas", "documents"],
                )
                docs = results.get("documents", [])
                metas = results.get("metadatas", [])
                if docs:
                    pairs = list(zip(docs, metas))
                    pairs.sort(key=lambda x: x[1].get("timestamp", ""), reverse=True)
                    recent = pairs[:5]
                    lines = []
                    for doc, meta in recent:
                        ts = meta.get("timestamp", "")
                        date = ts[:10] if ts else "unknown"
                        preview = meta.get("preview", doc[:80])
                        lines.append(f"- [{date}] {preview}")
                    parts.append("Recent conversations:\n" + "\n".join(lines))
        except Exception as e:
            print(f"[El Fager] get_memory_summary chroma error: {e}")

        if not parts:
            return "I don't have anything stored about you yet."

        result = "\n\n".join(parts)
        if len(result) > 2000:
            result = result[:2000] + "\n[... truncated]"
        return result

    def get_upcoming_deadlines(self, days_ahead: int = 7) -> str:
        """
        Scan deadline-category facts and any facts mentioning date keywords.
        Returns a formatted string for system prompt injection.
        """
        import re
        DATE_PATTERNS = [
            r'\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b',
            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2}\b',
            r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b',
            r'\b(?:today|tomorrow|next\s+week|this\s+week)\b',
            r'\b\d{4}-\d{2}-\d{2}\b',
            r'\bexam\b|\bdeadline\b|\bsubmit\b|\bdue\b|\bpresentation\b|\bappointment\b',
        ]
        try:
            facts = self.get_all_facts()
            hits = []
            seen = set()
            for fact in facts:
                content = fact.get("content", "")
                if content in seen:
                    continue
                if fact.get("category") == "deadline":
                    hits.append(content)
                    seen.add(content)
                    continue
                for pat in DATE_PATTERNS:
                    if re.search(pat, content, re.IGNORECASE):
                        hits.append(content)
                        seen.add(content)
                        break
            if not hits:
                return ""
            lines = [f"- {h}" for h in hits[:6]]
            return "Upcoming / time-sensitive from memory:\n" + "\n".join(lines)
        except Exception as e:
            print(f"[El Fager] get_upcoming_deadlines failed (non-fatal): {e}")
            return ""

    def clear_all(self) -> None:
        """Delete facts.json and reset ChromaDB collection."""
        try:
            if _FACTS_FILE.exists():
                _FACTS_FILE.unlink()
        except Exception as e:
            print(f"[El Fager] Facts clear failed: {e}")

        try:
            if self._ready and self._collection is not None:
                import chromadb
                from chromadb.utils import embedding_functions
                persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")
                client = chromadb.PersistentClient(path=persist_dir)
                client.delete_collection("el_fager_memory")
                ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name="all-MiniLM-L6-v2"
                )
                self._collection = client.create_collection(
                    name="el_fager_memory",
                    embedding_function=ef,
                    metadata={"hnsw:space": "cosine"},
                )
        except Exception as e:
            print(f"[El Fager] ChromaDB clear failed: {e}")
