"""Brain-callable notification tools for sending alerts to Mo's WhatsApp."""


def send_notification(message: str, channel: str = "whatsapp") -> str:
    """Send a message to Mo's WhatsApp via CallMeBot."""
    from core.notifier import get_notifier
    notifier = get_notifier()

    if channel in ("whatsapp", "all"):
        if not notifier.whatsapp_ready:
            return (
                "WhatsApp not configured. "
                "Add WHATSAPP_PHONE and WHATSAPP_CALLMEBOT_KEY to .env, then restart El Fager."
            )
        ok = notifier.send_whatsapp(message)
        if not ok:
            return "WhatsApp send failed -- check WHATSAPP_PHONE and WHATSAPP_CALLMEBOT_KEY in .env."

    return f"Notification sent: {message[:80]}"


def notification_status() -> str:
    """Return the current WhatsApp notification setup status."""
    from core.notifier import get_notifier
    return get_notifier().status()
