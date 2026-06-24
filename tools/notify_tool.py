"""Brain-callable notification tools for sending alerts to Mo's WhatsApp (Twilio)."""


def send_notification(message: str, channel: str = "whatsapp") -> str:
    """Send a message to Mo's WhatsApp via Twilio sandbox."""
    from core.notifier import get_notifier
    notifier = get_notifier()

    if channel in ("whatsapp", "all"):
        if not notifier.whatsapp_ready:
            return (
                "WhatsApp not configured. "
                "Add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, "
                "and WHATSAPP_PHONE to .env, then restart El Fager."
            )
        ok = notifier.send_whatsapp(message)
        if not ok:
            return "WhatsApp send failed -- check your Twilio credentials in .env."

    return f"Notification sent: {message[:80]}"


def notification_status() -> str:
    """Return the current WhatsApp notification setup status."""
    from core.notifier import get_notifier
    return get_notifier().status()
