"""
SkillStore — persistent store for SkillForge skills.

A skill is a stored natural-language instruction template. run_skill returns
the instructions into Brain.chat()'s tool loop where Claude executes them with
the tools it already has — skills are data, not code.

Storage: data/skills.json  {"seeds_installed": bool, "skills": [...]}
Seeds:   core/skills/seeds.json (committed; installed once, source="seed")
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from core import atomic

_DEFAULT_PATH = Path("data/skills.json")
_DEFAULT_SEEDS = Path(__file__).parent / "seeds.json"

# Instructions that could steer toward the live-trading confirmation flow are
# rejected outright — real-money actions stay behind the deterministic gate.
_FORBIDDEN_FRAGMENTS = ("confirm live trading",)


class ForbiddenSkillError(ValueError):
    """Raised when skill instructions touch the live-trading confirmation flow."""


class SkillStore:
    def __init__(self, path: Path | None = None, seeds_path: Path | None = None):
        self._path = Path(path) if path else _DEFAULT_PATH
        self._seeds_path = Path(seeds_path) if seeds_path else _DEFAULT_SEEDS
        self._data = self._load()
        if not self._data.get("seeds_installed"):
            self._install_seeds()

    # ── Persistence ────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"seeds_installed": False, "skills": []}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic.write(self._path,
            json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── Seeds ──────────────────────────────────────────────────────────────

    def _install_seeds(self) -> None:
        """One-time install of the starter packs. Idempotent: the flag persists
        even if Mo later deletes a seed skill — it is never re-installed."""
        try:
            if self._seeds_path.exists():
                seeds = json.loads(self._seeds_path.read_text(encoding="utf-8"))
                existing = {s["name"].lower() for s in self._data["skills"]}
                for seed in seeds:
                    if seed["name"].lower() in existing:
                        continue
                    self._data["skills"].append(self._new_skill(
                        seed["name"], seed["instructions"],
                        seed.get("trigger_phrases", []), source="seed",
                    ))
        except Exception:
            pass
        self._data["seeds_installed"] = True
        self._save()

    # ── CRUD ───────────────────────────────────────────────────────────────

    @staticmethod
    def _new_skill(name: str, instructions: str,
                   trigger_phrases: list[str] | None, source: str) -> dict:
        return {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "instructions": instructions,
            "trigger_phrases": trigger_phrases or [],
            "source": source,
            "created_at": datetime.now().isoformat(),
            "run_count": 0,
            "last_run_at": None,
            "scheduled_task_id": None,
            "automation_proposed": False,
        }

    def add(self, name: str, instructions: str,
            trigger_phrases: list[str] | None = None,
            source: str = "taught") -> dict:
        lowered = instructions.lower()
        for frag in _FORBIDDEN_FRAGMENTS:
            if frag in lowered:
                raise ForbiddenSkillError(
                    "Skills cannot include live-trading confirmation steps."
                )
        if any(s["name"].lower() == name.lower() for s in self._data["skills"]):
            raise ValueError(f"A skill named '{name}' already exists.")
        skill = self._new_skill(name, instructions, trigger_phrases, source)
        self._data["skills"].append(skill)
        self._save()
        return skill

    def list_all(self) -> list[dict]:
        return list(self._data["skills"])

    def get(self, query: str) -> dict | None:
        """Match by exact name, then trigger phrase inside the query,
        then skill name inside the query (all case-insensitive)."""
        q = query.lower().strip()
        for s in self._data["skills"]:
            if s["name"].lower() == q:
                return s
        for s in self._data["skills"]:
            if any(p.lower() in q for p in s.get("trigger_phrases", []) if p):
                return s
        for s in self._data["skills"]:
            if s["name"].lower() in q:
                return s
        return None

    def delete(self, name: str) -> bool:
        before = len(self._data["skills"])
        self._data["skills"] = [
            s for s in self._data["skills"] if s["name"].lower() != name.lower()
        ]
        if len(self._data["skills"]) < before:
            self._save()
            return True
        return False

    # ── Run tracking / scheduling ──────────────────────────────────────────

    def _update(self, name: str, fields: dict) -> dict | None:
        for s in self._data["skills"]:
            if s["name"].lower() == name.lower():
                s.update(fields)
                self._save()
                return s
        return None

    def mark_run(self, name: str) -> dict | None:
        skill = self.get(name)
        if skill is None:
            return None
        return self._update(skill["name"], {
            "run_count": skill["run_count"] + 1,
            "last_run_at": datetime.now().isoformat(),
        })

    def set_schedule(self, name: str, task_id: str) -> dict | None:
        return self._update(name, {"scheduled_task_id": task_id})

    def clear_schedule(self, name: str) -> dict | None:
        return self._update(name, {"scheduled_task_id": None})

    def set_automation_proposed(self, name: str) -> dict | None:
        return self._update(name, {"automation_proposed": True})
