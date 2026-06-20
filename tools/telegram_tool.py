"""
Telegram bot tool — Phase 6A.

Uses Telegram Bot API directly via httpx (no python-telegram-bot library).
Setup:
  1. Message @BotFather on Telegram → /newbot → copy the token
  2. Add TELEGRAM_BOT_TOKEN to .env
  3. Message your bot once, then say "check my Telegram messages" to see your chat_id
  4. Say "add Telegram contact [name] [chat_id]" to save contacts

Contacts are stored in data/telegram_contacts.json: {"Name": 123456789}
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
load_dotenv()

_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_API = f"https://api.telegram.org/bot{_TOKEN}"
_CONTACTS_PATH = Path("data/telegram_contacts.json")
_NOT_SET_UP = (
    "[Telegram not set up — add TELEGRAM_BOT_TOKEN to .env. "
    "Get a token from @BotFather on Telegram: /newbot → copy the token.]"
)


def _available() -> bool:
    return bool(_TOKEN and not _TOKEN.startswith("xxx"))


def _load_contacts() -> dict:
    try:
        if _CONTACTS_PATH.exists():
            return json.loads(_CONTACTS_PATH.read_text(encoding="utf-8"))
        return {}
    except Exception:
        return {}


def _save_contacts(contacts: dict) -> None:
    _CONTACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONTACTS_PATH.write_text(
        json.dumps(contacts, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _find_contact(name: str) -> tuple[str, int] | tuple[None, None]:
    contacts = _load_contacts()
    name_lower = name.lower()
    for stored, cid in contacts.items():
        if name_lower in stored.lower():
            return stored, int(cid)
    return None, None


def _time_ago(unix_ts: int) -> str:
    try:
        dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        diff = int((now - dt).total_seconds())
        if diff < 60:
            return "just now"
        if diff < 3600:
            return f"{diff // 60}m ago"
        if diff < 86400:
            return f"{diff // 3600}h ago"
        return f"{diff // 86400}d ago"
    except Exception:
        return ""


def send_telegram(contact_name: str, message: str) -> str:
    """Send a Telegram message to a saved contact."""
    if not _available():
        return _NOT_SET_UP
    display_name, chat_id = _find_contact(contact_name)
    if chat_id is None:
        return (
            f"No Telegram contact named '{contact_name}'. "
            f"Say 'add Telegram contact {contact_name} [chat_id]' first. "
            f"Run 'check my Telegram messages' to find chat IDs."
        )
    try:
        resp = httpx.post(
            f"{_API}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            return f"Sent to {display_name}"
        return f"[Telegram error: {data.get('description', 'unknown')}]"
    except Exception as e:
        return f"[Telegram error: {e}]"


def get_telegram_messages(n: int = 10) -> str:
    """Fetch the last N messages received by the bot."""
    if not _available():
        return _NOT_SET_UP
    try:
        resp = httpx.get(
            f"{_API}/getUpdates",
            params={"limit": min(n, 100), "allowed_updates": ["message"]},
            timeout=10,
        )
        data = resp.json()
        if not data.get("ok"):
            return f"[Telegram error: {data.get('description', 'unknown')}]"

        updates = data.get("result", [])
        if not updates:
            return "No messages received yet — message your bot first to register your chat_id."

        lines = []
        for upd in updates[-n:]:
            msg = upd.get("message", {})
            if not msg:
                continue
            sender = msg.get("from", {})
            first = sender.get("first_name", "")
            last = sender.get("last_name", "")
            name = f"{first} {last}".strip() or "Unknown"
            chat_id = msg.get("chat", {}).get("id", "?")
            text = msg.get("text", "[non-text message]")
            ts = msg.get("date", 0)
            lines.append(f"{name} (chat_id: {chat_id}) [{_time_ago(ts)}]: {text}")

        if not lines:
            return "No text messages found."
        return "Recent Telegram messages:\n" + "\n".join(lines)
    except Exception as e:
        return f"[Telegram error: {e}]"


def add_telegram_contact(name: str, chat_id: str) -> str:
    """Save a Telegram contact (name → chat_id)."""
    try:
        cid = int(str(chat_id).strip())
        contacts = _load_contacts()
        contacts[name.strip()] = cid
        _save_contacts(contacts)
        return f"Saved Telegram contact: {name} -> {cid}"
    except ValueError:
        return f"[Invalid chat_id '{chat_id}' — must be a number. Run 'check my Telegram messages' to find it.]"
    except Exception as e:
        return f"[Telegram error: {e}]"


def list_telegram_contacts() -> str:
    """List all saved Telegram contacts."""
    contacts = _load_contacts()
    if not contacts:
        return "No Telegram contacts saved yet. Say 'add Telegram contact [name] [chat_id]'."
    lines = [f"{i+1}. {name}: {cid}" for i, (name, cid) in enumerate(contacts.items())]
    return "Telegram contacts:\n" + "\n".join(lines)
