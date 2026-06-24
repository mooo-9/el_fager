"""
ElFagerNotifier -- sends alerts to Mo's WhatsApp via CallMeBot (free, personal use).

Setup (one-time, ~2 minutes):
  1. Save +34 644 64 87 48 in your WhatsApp contacts as "CallMeBot".
  2. Send this exact message to that contact: I allow callmebot to send me messages
  3. You will receive your API key in a reply from CallMeBot.
  4. Add to .env:
       WHATSAPP_PHONE=201234567890        (your number with country code, no + sign)
       WHATSAPP_CALLMEBOT_KEY=<key from step 3>
  5. Restart El Fager. Stock trades, price alerts, and task completions will reach your WhatsApp.
"""

import os
from typing import Optional

import httpx

_CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"
_INSTANCE: Optional["ElFagerNotifier"] = None


class ElFagerNotifier:
    def __init__(self) -> None:
        self._wa_phone = os.getenv("WHATSAPP_PHONE", "").strip()
        self._wa_key   = os.getenv("WHATSAPP_CALLMEBOT_KEY", "").strip()

    @property
    def whatsapp_ready(self) -> bool:
        return bool(self._wa_phone and self._wa_key)

    def send_whatsapp(self, text: str) -> bool:
        if not self.whatsapp_ready:
            return False
        try:
            resp = httpx.get(
                _CALLMEBOT_URL,
                params={
                    "phone":  self._wa_phone,
                    "text":   text[:1600],
                    "apikey": self._wa_key,
                },
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def send(self, text: str) -> bool:
        return self.send_whatsapp(text)

    def status(self) -> str:
        if self.whatsapp_ready:
            return "WhatsApp: ready -- alerts will be sent to your phone."
        return (
            "WhatsApp: not configured. "
            "Add WHATSAPP_PHONE and WHATSAPP_CALLMEBOT_KEY to .env. "
            "Ask El Fager 'how do I set up WhatsApp notifications' for step-by-step instructions."
        )


def get_notifier() -> ElFagerNotifier:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ElFagerNotifier()
    return _INSTANCE
