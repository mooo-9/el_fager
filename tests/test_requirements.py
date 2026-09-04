"""Every third-party module the app imports must be declared in requirements.txt.

Undeclared deps don't fail at install time - they fail later, one tool at a
time, as "No module named X" on a machine that never installed them.
"""
import ast
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# import name -> distribution name, where they differ
_ALIASES = {
    "alpaca": "alpaca-py", "bs4": "beautifulsoup4", "cv2": "opencv-python",
    "docx": "python-docx", "dotenv": "python-dotenv", "fitz": "pymupdf",
    "kasa": "python-kasa", "PIL": "pillow", "pygame": "pygame-ce",
    "speedtest": "speedtest-cli", "whisper": "openai-whisper", "yaml": "pyyaml",
    "googleapiclient": "google-api-python-client", "google": "google-api-python-client",
    "google_auth_oauthlib": "google-auth-oauthlib", "todoist_api_python": "todoist-api-python",
    "youtube_transcript_api": "youtube-transcript-api", "notion_client": "notion-client",
    "edge_tts": "edge-tts", "faster_whisper": "faster-whisper",
    "sentence_transformers": "sentence-transformers", "duckduckgo_search": "duckduckgo-search",
    "sklearn": "scikit-learn",
}
for _win in ("win32api", "win32clipboard", "win32con", "win32gui", "win32print",
             "win32process", "win32file", "win32event", "pywintypes", "pythoncom", "win32com"):
    _ALIASES[_win] = "pywin32"

# Deliberately not in requirements.txt
_EXEMPT = {
    "torch",   # README: install the CPU-only build first, from the PyTorch index
    "ddgs",    # optional newer name for duckduckgo-search; code falls back
    "onnx", "scipy", "pyttsx3",  # scripts/train_hey_fager.py only, not the app
}

_SCAN = ("core", "tools", "ui")


def _declared() -> set[str]:
    names = set()
    for line in (_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            names.add(re.split(r"[<>=!\[;]", line)[0].strip().lower().replace("_", "-"))
    return names


def _imported() -> dict[str, str]:
    """Top-level third-party import name -> first file that imports it."""
    found: dict[str, str] = {}
    local = set(_SCAN) | {"tests", "main", "watchdog"}
    for pkg in _SCAN:
        for path in sorted((_ROOT / pkg).rglob("*.py")):
            if ".bak" in path.name:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue  # f-string syntax newer than the interpreter running tests
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    mods = [node.module.split(".")[0]]
                else:
                    continue
                for m in mods:
                    if m in sys.stdlib_module_names or m in local or m in _EXEMPT:
                        continue
                    found.setdefault(m, str(path.relative_to(_ROOT)))
    return found


def test_every_imported_package_is_declared():
    declared = _declared()
    missing = {
        mod: src for mod, src in _imported().items()
        if _ALIASES.get(mod, mod).lower().replace("_", "-") not in declared
    }
    assert not missing, "undeclared dependencies:\n" + "\n".join(
        f"  {m} (imported by {s})" for m, s in sorted(missing.items())
    )
