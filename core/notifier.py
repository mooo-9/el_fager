"""
ElFagerNotifier -- sends alerts to Mo's WhatsApp via Twilio sandbox (free).

One-time setup (~10 minutes):
  1. Sign up at twilio.com/try-twilio (free, no credit card for sandbox).
  2. In the Twilio Console go to: Messaging -> Try it out -> Send a WhatsApp message.
  3. You will see a sandbox number (e.g. +14155238886) and a join code like "join silver-tiger".
  4. From YOUR WhatsApp, send that join message to the sandbox number to opt in.
  5. From the Twilio Console dashboard copy your Account SID and Auth Token.
  6. Add to .env:
       TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
       TWILIO_AUTH_TOKEN=your_auth_token
       TWILIO_WHATSAPP_FROM=+14155238886   (the sandbox number from step 3)
       WHATSAPP_PHONE=+201152215125        (your number, WITH + sign)
  7. Restart El Fager. Trades, alerts, and task completions will arrive on WhatsApp.
"""

import os
from typing import Optional

import httpx

_INSTANCE: Optional["ElFagerNotifier"] = None


class ElFagerNotifier:
    def __init__(self) -> None:
        self._account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        self._auth_token  = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        self._from_number = os.getenv("TWILIO_WHATSAPP_FROM", "").strip()
        self._to_number   = os.getenv("WHATSAPP_PHONE", "").strip()

    @property
    def whatsapp_ready(self) -> bool:
        return bool(
            self._account_sid
            and self._auth_token
            and self._from_number
            and self._to_number
        )

    def send_whatsapp(self, text: str) -> bool:
        if not self.whatsapp_ready:
            return False
        url = (
            f"https://api.twilio.com/2010-04-01/Accounts/"
            f"{self._account_sid}/Messages.json"
        )
        from_wa = f"whatsapp:{self._from_number}"
        to_wa   = f"whatsapp:{self._to_number}"
        try:
            resp = httpx.post(
                url,
                data={"From": from_wa, "To": to_wa, "Body": text[:1600]},
                auth=(self._account_sid, self._auth_token),
                timeout=10,
            )
            return resp.status_code in (200, 201)
        except Exception:
            return False

    def send(self, text: str) -> bool:
        return self.send_whatsapp(text)

    def status(self) -> str:
        if self.whatsapp_ready:
            return f"WhatsApp (Twilio): ready -- alerts go to {self._to_number}."
        missing = [
            v for v, k in [
                ("TWILIO_ACCOUNT_SID",  self._account_sid),
                ("TWILIO_AUTH_TOKEN",   self._auth_token),
                ("TWILIO_WHATSAPP_FROM", self._from_number),
                ("WHATSAPP_PHONE",      self._to_number),
            ] if not k
        ]
        return (
            f"WhatsApp not configured. Missing in .env: {', '.join(missing)}. "
            "Ask El Fager 'how do I set up WhatsApp notifications' for setup steps."
        )


def get_notifier() -> ElFagerNotifier:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ElFagerNotifier()
    return _INSTANCE
