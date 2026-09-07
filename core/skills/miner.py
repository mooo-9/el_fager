"""
HabitMiner — finds Mo's repeated asks in the conversation logs and turns them
into skill proposals.

A message becomes a proposal when its keyword fingerprint appears on
`min_days` distinct days within the mining window, is not already covered by
an existing skill, and was not proposed before (any status).

Proposals persist in data/skill_proposals.json:
  {id, fingerprint, example, count, days_seen, status, created_at}
status: pending -> accepted | dismissed
"""
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from core.skills.store import SkillStore
from core import atomic

_DEFAULT_CONVERSATIONS = Path("data/conversations")
_DEFAULT_PROPOSALS = Path("data/skill_proposals.json")

_MAX_MESSAGE_LEN = 160  # longer messages are one-off content, not habits

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "so", "to", "of", "for", "in", "on",
    "at", "is", "are", "was", "were", "be", "been", "am", "do", "does", "did",
    "can", "could", "would", "should", "will", "shall", "may", "might", "must",
    "you", "your", "me", "my", "i", "we", "our", "it", "its", "this", "that",
    "these", "those", "what", "whats", "how", "hows", "please", "plz", "now",
    "today", "tonight", "again", "just", "some", "any", "with", "about",
    "el", "ya", "yalla", "keda", "lw", "law", "momken", "3ayez", "ayez",
}


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z\s]", " ", text)  # keep latin letters only
    return re.sub(r"\s+", " ", text).strip()


def fingerprint(text: str) -> str:
    """Sorted unique non-stopword tokens. Empty string when too little signal."""
    tokens = [t for t in normalize(text).split()
              if t not in _STOPWORDS and len(t) > 1]
    unique = sorted(set(tokens))
    if len(unique) < 2:
        return ""
    return " ".join(unique)


class HabitMiner:
    def __init__(self, conversations_dir: Path | None = None,
                 proposals_path: Path | None = None,
                 store: SkillStore | None = None):
        self._convo_dir = Path(conversations_dir) if conversations_dir else _DEFAULT_CONVERSATIONS
        self._proposals_path = Path(proposals_path) if proposals_path else _DEFAULT_PROPOSALS
        self._store = store if store is not None else SkillStore()

    # ── Proposal persistence ───────────────────────────────────────────────

    def _load(self) -> list[dict]:
        if self._proposals_path.exists():
            try:
                return json.loads(self._proposals_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save(self, proposals: list[dict]) -> None:
        self._proposals_path.parent.mkdir(parents=True, exist_ok=True)
        atomic.write(self._proposals_path,
            json.dumps(proposals, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def pending(self) -> list[dict]:
        return [p for p in self._load() if p["status"] == "pending"]

    def set_status(self, proposal_id: str, status: str) -> bool:
        proposals = self._load()
        for p in proposals:
            if p["id"] == proposal_id:
                p["status"] = status
                self._save(proposals)
                return True
        return False

    # ── Mining ─────────────────────────────────────────────────────────────

    def _iter_user_messages(self, days: int):
        for offset in range(days):
            day = (datetime.now() - timedelta(days=offset)).strftime("%Y-%m-%d")
            fpath = self._convo_dir / f"{day}.jsonl"
            if not fpath.exists():
                continue
            for line in fpath.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if entry.get("role") != "user":
                    continue
                content = entry.get("content", "")
                if 0 < len(content) <= _MAX_MESSAGE_LEN:
                    yield day, content

    def mine(self, days: int = 14, min_days: int = 3) -> list[dict]:
        """Scan the window and persist NEW pending proposals; returns them."""
        clusters: dict[str, dict] = {}
        for day, content in self._iter_user_messages(days):
            fp = fingerprint(content)
            if not fp:
                continue
            c = clusters.setdefault(fp, {"days": set(), "count": 0, "example": content})
            c["days"].add(day)
            c["count"] += 1
            if len(content) < len(c["example"]):
                c["example"] = content  # shortest phrasing reads best

        existing_fps = {p["fingerprint"] for p in self._load()}
        proposals = self._load()
        new: list[dict] = []
        for fp, c in clusters.items():
            if len(c["days"]) < min_days:
                continue
            if fp in existing_fps:
                continue
            if self._store.get(c["example"]) is not None:
                continue  # an existing skill already covers this ask
            proposal = {
                "id": str(uuid.uuid4())[:8],
                "fingerprint": fp,
                "example": c["example"],
                "count": c["count"],
                "days_seen": len(c["days"]),
                "status": "pending",
                "created_at": datetime.now().isoformat(),
            }
            proposals.append(proposal)
            new.append(proposal)
        if new:
            self._save(proposals)
        return new
