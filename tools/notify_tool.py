"""Brain-callable notification tools for sending alerts to Mo's phone."""


def send_notification(message: str, channel: str = "telegram") -> str:
    """Send a message to Mo's phone via Telegram bot."""
    from core.notifier import get_notifier
    notifier = get_notifier()

    if channel in ("telegram", "all"):
        if not notifier.telegram_ready:
            return (
                "Telegram not configured. "
                "Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env, then restart El Fager."
            )
        ok = notifier.send_telegram(message)
        if not ok:
            return "Telegram send failed -- check your bot token and chat ID in .env."

    return f"Notification sent: {message[:80]}"


def notification_status() -> str:
    """Return the current notification setup status."""
    from core.notifier import get_notifier
    return get_notifier().status()
