"""
ElFagerNotifier -- sends alerts to Mo's phone via Telegram bot.

Setup (one-time, ~2 minutes):
  1. Open Telegram and message @BotFather -> /newbot -> pick a name -> copy the token.
  2. Start a conversation with your new bot (search its username, press Start).
  3. Visit https://api.telegram.org/bot{TOKEN}/getUpdates -> copy the "chat_id" number.
  4. Add to .env:
       TELEGRAM_BOT_TOKEN=<token from step 1>
       TELEGRAM_CHAT_ID=<chat_id from step 3>
  5. Restart El Fager. Stock trade alerts and task completions will now reach your phone.
"""

import os
from typing import Optional

import httpx

_INSTANCE: Optional["ElFagerNotifier"] = None


class ElFagerNotifier:
    def __init__(self) -> None:
        self._tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self._tg_chat  = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    @property
    def telegram_ready(self) -> bool:
        return bool(self._tg_token and self._tg_chat)

    def send_telegram(self, text: str) -> bool:
        if not self.telegram_ready:
            return False
        try:
            resp = httpx.post(
                f"https://api.telegram.org/bot{self._tg_token}/sendMessage",
                json={"chat_id": self._tg_chat, "text": text[:4096]},
                timeout=8,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def send(self, text: str) -> bool:
        return self.send_telegram(text)

    def status(self) -> str:
        if self.telegram_ready:
            return "Telegram: ready -- alerts will be sent to your phone."
        return (
            "Telegram: not configured. "
            "Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env. "
            "Ask El Fager 'how do I set up phone notifications' for step-by-step instructions."
        )


def get_notifier() -> ElFagerNotifier:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ElFagerNotifier()
    return _INSTANCE
