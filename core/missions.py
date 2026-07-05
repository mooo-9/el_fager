"""
MissionManager — El Fager's multi-step planning layer.

A mission is a goal decomposed into ordered steps, persisted in
data/missions.json. The ProactiveEngine executes ONE step per 60s cycle via
brain.chat(); each step's prompt carries the goal plus completed-step results.
Failed steps retry once, then the mission is marked blocked and reported.
State lives on disk, so a crash or restart resumes at the same step.

Only one mission runs at a time — sequential focus keeps context coherent
and cost bounded.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path

_MISSIONS_PATH = Path("data/missions.json")

_MAX_ATTEMPTS = 2  # 1 try + 1 retry per step

_FORBIDDEN_FRAGMENTS = ("confirm live trading",)


class ForbiddenMissionError(ValueError):
    """Raised when a mission step touches the live-trading confirmation flow."""


class MissionManager:
    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path else _MISSIONS_PATH

    # ── Persistence ────────────────────────────────────────────────────────

    def _load(self) -> list[dict]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save(self, missions: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(missions, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def create(self, goal: str, steps: list[str]) -> dict:
        steps = [s.strip() for s in steps if s and s.strip()]
        if not steps:
            raise ValueError("A mission needs at least one step.")
        joined = (goal + " " + " ".join(steps)).lower()
        for frag in _FORBIDDEN_FRAGMENTS:
            if frag in joined:
                raise ForbiddenMissionError(
                    "Missions cannot include live-trading confirmation steps."
                )
        if self.get_active() is not None:
            raise ValueError(
                "A mission is already in progress. Finish or cancel it first."
            )
        mission = {
            "id": str(uuid.uuid4())[:8],
            "goal": goal,
            "steps": [
                {"n": i + 1, "description": desc, "status": "pending",
                 "result": None, "attempts": 0}
                for i, desc in enumerate(steps)
            ],
            "status": "in_progress",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        missions = self._load()
        missions.append(mission)
        self._save(missions)
        return mission

    def get_active(self) -> dict | None:
        for m in self._load():
            if m["status"] == "in_progress":
                return m
        return None

    def last_finished(self) -> dict | None:
        finished = [m for m in self._load() if m["status"] != "in_progress"]
        return finished[-1] if finished else None

    def cancel(self, mission_id: str) -> bool:
        return self._finish(mission_id, "cancelled")

    # ── Step execution bookkeeping ─────────────────────────────────────────

    def next_step(self) -> dict | None:
        """First pending step of the active mission (None when idle)."""
        active = self.get_active()
        if active is None:
            return None
        for s in active["steps"]:
            if s["status"] == "pending":
                return s
        return None

    def step_context(self, max_result_chars: int = 400) -> str:
        """Prompt context: the goal plus results of completed steps."""
        active = self.get_active()
        if active is None:
            return ""
        lines = [f"Mission goal: {active['goal']}"]
        for s in active["steps"]:
            if s["status"] == "done" and s.get("result"):
                lines.append(
                    f"Step {s['n']} ({s['description']}) result: "
                    f"{s['result'][:max_result_chars]}"
                )
        return "\n".join(lines)

    def complete_step(self, mission_id: str, n: int, result: str) -> None:
        missions = self._load()
        for m in missions:
            if m["id"] != mission_id:
                continue
            for s in m["steps"]:
                if s["n"] == n:
                    s["status"] = "done"
                    s["result"] = (result or "")[:2000]
            m["updated_at"] = datetime.now().isoformat()
            if all(s["status"] == "done" for s in m["steps"]):
                m["status"] = "done"
        self._save(missions)

    def fail_step(self, mission_id: str, n: int, error: str) -> None:
        """First failure re-queues the step; the second blocks the mission."""
        missions = self._load()
        for m in missions:
            if m["id"] != mission_id:
                continue
            for s in m["steps"]:
                if s["n"] == n:
                    s["attempts"] += 1
                    if s["attempts"] >= _MAX_ATTEMPTS:
                        s["status"] = "failed"
                        s["result"] = f"Failed: {error[:400]}"
                        m["status"] = "blocked"
                    else:
                        s["status"] = "pending"  # retry next cycle
            m["updated_at"] = datetime.now().isoformat()
        self._save(missions)

    def _finish(self, mission_id: str, status: str) -> bool:
        missions = self._load()
        for m in missions:
            if m["id"] == mission_id and m["status"] == "in_progress":
                m["status"] = status
                m["updated_at"] = datetime.now().isoformat()
                self._save(missions)
                return True
        return False

    # ── Reporting ──────────────────────────────────────────────────────────

    def format_status(self) -> str:
        active = self.get_active()
        if active is None:
            last = self.last_finished()
            if last:
                return (f"No mission running. Last mission '{last['goal']}' "
                        f"ended: {last['status']}.")
            return "No mission running."
        done = sum(1 for s in active["steps"] if s["status"] == "done")
        total = len(active["steps"])
        current = self.next_step()
        lines = [
            f"Mission '{active['goal']}' -- {done}/{total} steps done.",
        ]
        if current:
            lines.append(f"Next: step {current['n']} -- {current['description']}")
        return " ".join(lines)
