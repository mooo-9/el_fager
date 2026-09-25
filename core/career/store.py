"""JSON files under data/career/, and the pipeline's settings."""
import json
import threading
from pathlib import Path

DIR = Path(__file__).parent.parent.parent / "data" / "career"

_lock = threading.RLock()

# Search terms cover Mo's targets (internships and entry-level Data/Business
# Analyst and Software/IT) and the Big 4's four service lines: technology
# consulting, data & analytics, risk / IT audit, and audit & tax.
DEFAULTS = {
    # Practice mode until Mo's CV is final: everything is found, scored and
    # drafted, nothing is sent.
    "live": False,
    "daily_target": 100,
    "min_score": 60,
    # LinkedIn restricts accounts that apply at machine pace.
    "linkedin_daily_cap": 20,
    # A firm's hiring system keeps every application; a wave of them to one
    # Big 4 firm reads as spray, and rejections can bar re-applying for months.
    "big4_per_firm_per_month": 3,
    # The autonomous task that runs the job hunt every night, once Mo turns it on.
    "nightly_task_id": "",
    "search_terms": [
        "data analyst", "business analyst", "business intelligence",
        "software developer", "IT support", "ERP SAP", "graduate program",
        "fresh graduate", "internship", "technology consultant",
        "risk advisory", "IT audit", "audit associate", "tax associate",
    ],
}


def load(name: str, default):
    with _lock:
        try:
            return json.loads((DIR / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default


def save(name: str, obj) -> None:
    with _lock:
        DIR.mkdir(parents=True, exist_ok=True)
        tmp = DIR / (name + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(DIR / name)


def settings() -> dict:
    return {**DEFAULTS, **load("settings.json", {})}


def update_settings(**changes) -> dict:
    with _lock:
        saved = load("settings.json", {})
        saved.update({k: v for k, v in changes.items() if k in DEFAULTS})
        save("settings.json", saved)
    return settings()
