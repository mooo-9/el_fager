"""
Local LLM fallback via Ollama (http://localhost:11434).

Used when Claude API is unreachable or rate-limited. Provides basic chat
without tool calls. Model and enabled flag are read from data/settings.json
at call time so settings-dialog changes take effect immediately.
"""

import json
import os
from pathlib import Path

import httpx

OLLAMA_BASE = "http://localhost:11434"
_TIMEOUT = 120.0

_PROFILE_FILE = Path("profile.json")


def _build_system_prompt() -> str:
    try:
        p = json.loads(_PROFILE_FILE.read_text(encoding="utf-8"))
        name     = p.get("name", "Mo")
        location = p.get("location", "Cairo")
        occ      = p.get("occupation", "student")
    except Exception:
        name, location, occ = "Mo", "Cairo", "student"
    return (
        f"You are El Fager, a personal AI assistant for {name}, "
        f"a {occ} based in {location}. "
        "You are currently in offline mode — the Claude API is unreachable or rate-limited. "
        "You can still chat naturally, but tool calls (smart home, calendar, "
        "email, weather, file access, etc.) are unavailable in this mode. "
        "Be warm, helpful, and concise."
    )

_SETTINGS_FILE = Path("data/settings.json")


def _read_settings() -> dict:
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def is_fallback_enabled() -> bool:
    """Check settings.json first, then env var."""
    s = _read_settings()
    if "local_llm_fallback" in s:
        return bool(s["local_llm_fallback"])
    return os.getenv("LOCAL_LLM_FALLBACK", "true").lower() != "false"


def _get_model() -> str:
    """Read model from settings.json → env var → default."""
    s = _read_settings()
    return s.get("ollama_model") or os.getenv("OLLAMA_MODEL", "llama3.2")


def is_ollama_running() -> bool:
    try:
        r = httpx.get(OLLAMA_BASE, timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def local_chat(messages: list[dict]) -> str:
    """
    Send messages to local Ollama model.

    Returns the assistant's reply as plain text (no prefix).
    Raises RuntimeError with a human-readable message if fallback
    is disabled or Ollama is not available.
    """
    if not is_fallback_enabled():
        raise RuntimeError("Local LLM fallback is disabled in settings.")

    if not is_ollama_running():
        raise RuntimeError(
            "Can't reach Claude API and Ollama isn't running. "
            "Install Ollama from ollama.ai or check your internet connection."
        )

    model = _get_model()

    ollama_messages = [{"role": "system", "content": _build_system_prompt()}]
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            # Flatten Anthropic-style content blocks (text only — skip images)
            content = " ".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        if role in ("user", "assistant") and content:
            ollama_messages.append({"role": role, "content": content})

    try:
        r = httpx.post(
            f"{OLLAMA_BASE}/api/chat",
            json={"model": model, "messages": ollama_messages, "stream": False},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "").strip()

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise RuntimeError(
                f"Ollama is running but model '{model}' is not installed. "
                f"Run: ollama pull {model}"
            )
        raise RuntimeError(f"Ollama HTTP error {e.response.status_code}: {e}")

    except httpx.TimeoutException:
        raise RuntimeError(
            f"Ollama timed out after {_TIMEOUT}s. "
            "The model may still be loading — try again in 30 seconds. "
            "For a faster first response, switch to llama3.2:1b in Settings."
        )

    except Exception as e:
        raise RuntimeError(f"Local chat failed: {e}")
