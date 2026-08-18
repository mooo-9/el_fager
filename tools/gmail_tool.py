"""
Gmail tool — Phase 3C.

Requires data/credentials.json (same file as Calendar — same Google Cloud project).
Must also enable the Gmail API in Google Cloud Console for project grand-verve-499512-d9.
token_gmail.json is auto-created on first OAuth flow (separate from calendar's token.json).
Both credential files are in .gitignore — never commit them.
"""

import base64
import os
import re
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

CREDENTIALS_PATH = "data/credentials.json"
TOKEN_PATH = "data/token_gmail.json"   # kept separate so calendar auth is untouched
GMAIL_AVAILABLE = os.path.exists(CREDENTIALS_PATH)

CAIRO_TZ = ZoneInfo("Africa/Cairo")
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",  # read + mark as read/archive
    "https://www.googleapis.com/auth/gmail.send",     # compose + reply
]

_pending_send: dict = {}   # staged email waiting for Mo's confirmation


# ── Auth ─────────────────────────────────────────────────────────────────────

def get_gmail_service():
    """Build and return an authenticated Gmail service, or None on failure."""
    if not GMAIL_AVAILABLE:
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = None
        if os.path.exists(TOKEN_PATH):
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        if not creds or not creds.valid:
            refreshed = False
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    refreshed = True
                except Exception:
                    # Refresh token revoked/expired server-side -- fall through
                    # to a fresh interactive OAuth flow instead of failing.
                    creds = None
            if not refreshed:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
        return build("gmail", "v1", credentials=creds)
    except Exception as e:
        print(f"[El Fager] Gmail auth failed: {e}")
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_header(headers: list, name: str) -> str:
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", "")
    return ""


def _strip_html(html: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"\s+", " ", text).strip()


def _extract_body(payload: dict) -> str:
    """Recursively extract plain-text body from a Gmail message payload."""
    mime = payload.get("mimeType", "")

    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    parts = payload.get("parts", [])

    for part in parts:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    for part in parts:
        if part.get("mimeType") == "text/html":
            data = part.get("body", {}).get("data", "")
            if data:
                html = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
                return _strip_html(html)

    for part in parts:
        result = _extract_body(part)
        if result:
            return result

    return ""


def _fmt_date(date_str: str) -> str:
    """Parse RFC 2822 date header to a short readable format."""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str).astimezone(CAIRO_TZ)
        return dt.strftime("%a, %b %d %H:%M")
    except Exception:
        return date_str[:16] if date_str else "unknown date"


def _encode_mime(msg) -> str:
    """Encode a MIME message as URL-safe base64 for the Gmail API."""
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


# ── Public Gmail functions ────────────────────────────────────────────────────

_NOT_SET_UP = (
    "[Gmail not set up — enable Gmail API in Google Cloud Console "
    "(project grand-verve-499512-d9) then say 'check my emails' to authorize]"
)


def list_messages(n: int = 5, unread_only: bool = True, query: str = "") -> str:
    """List recent Gmail messages."""
    if not GMAIL_AVAILABLE:
        return _NOT_SET_UP

    service = get_gmail_service()
    if service is None:
        return "[Gmail auth failed — check credentials.json and ensure Gmail API is enabled]"

    try:
        q = query.strip()
        if unread_only and "is:unread" not in q:
            q = ("is:unread " + q).strip()

        result = (
            service.users()
            .messages()
            .list(userId="me", q=q or None, maxResults=n)
            .execute()
        )
        messages = result.get("messages", [])
        if not messages:
            label = "unread emails" if unread_only else "emails"
            suffix = f" matching '{query}'" if query else ""
            return f"No {label} found{suffix}"

        lines = []
        for i, ref in enumerate(messages, 1):
            meta = (
                service.users()
                .messages()
                .get(userId="me", id=ref["id"], format="metadata",
                     metadataHeaders=["Subject", "From", "Date"])
                .execute()
            )
            hdrs = meta.get("payload", {}).get("headers", [])
            sender  = _get_header(hdrs, "From")
            subject = _get_header(hdrs, "Subject") or "(no subject)"
            date    = _fmt_date(_get_header(hdrs, "Date"))
            snippet = meta.get("snippet", "")[:100]
            lines.append(
                f"{i}. From: {sender}\n"
                f"   Subject: {subject}\n"
                f"   Date: {date}\n"
                f"   Preview: {snippet}\n"
                f"   ID: {ref['id']}"
            )

        title = "Unread emails" if (unread_only and not query) else "Emails"
        if query:
            title += f" matching '{query}'"
        return f"{title} ({len(messages)} shown):\n\n" + "\n\n".join(lines)

    except Exception as e:
        return f"[Gmail error: {e}]"


def read_message(msg_id: str) -> str:
    """Read the full content of a Gmail message and mark it as read."""
    if not GMAIL_AVAILABLE:
        return _NOT_SET_UP

    service = get_gmail_service()
    if service is None:
        return "[Gmail auth failed]"

    try:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )
        hdrs    = msg.get("payload", {}).get("headers", [])
        sender  = _get_header(hdrs, "From")
        to      = _get_header(hdrs, "To")
        subject = _get_header(hdrs, "Subject") or "(no subject)"
        date    = _fmt_date(_get_header(hdrs, "Date"))

        body = _extract_body(msg.get("payload", {}))
        if not body:
            body = msg.get("snippet", "(no readable content)")

        try:
            service.users().messages().modify(
                userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
            ).execute()
        except Exception:
            pass

        text = (
            f"From: {sender}\nTo: {to}\nSubject: {subject}\nDate: {date}\n\n"
            + body[:4000]
        )
        if len(body) > 4000:
            text += "\n[... message truncated ...]"
        return text

    except Exception as e:
        return f"[Gmail error: {e}]"


def search_messages(query: str, n: int = 10) -> str:
    """Search Gmail with a query string (same syntax as Gmail search bar)."""
    return list_messages(n=n, unread_only=False, query=query)


def send_message(to: str, subject: str, body: str) -> str:
    """Stage a new email for Mo to confirm before sending."""
    if not GMAIL_AVAILABLE:
        return _NOT_SET_UP

    from core import staging

    _pending_send.clear()
    _pending_send.update({
        "type": "new",
        "to": to,
        "subject": subject,
        "body": body,
        "expires_at": datetime.now(CAIRO_TZ) + timedelta(minutes=5),
    })
    staging.stage(
        medium="gmail",
        target=to,
        body=body,
        subject=subject,
        expires_at=_pending_send["expires_at"],
        confirm=confirm_send_message,
        cancel=_pending_send.clear,
    )

    preview = body[:200] + ("..." if len(body) > 200 else "")
    return (
        f"Ready to send email:\n"
        f"  To: {to}\n"
        f"  Subject: {subject}\n"
        f"  Body: {preview}\n\n"
        f"Say 'yes send it' to confirm."
    )


def confirm_send_message() -> str:
    """Actually send the staged email after Mo confirms."""
    if not GMAIL_AVAILABLE:
        return _NOT_SET_UP

    from core import staging

    if not _pending_send:
        return "No email staged — compose one first (e.g. 'send email to X about Y')."

    if datetime.now(CAIRO_TZ) > _pending_send.get("expires_at", datetime.min.replace(tzinfo=CAIRO_TZ)):
        _pending_send.clear()
        staging.resolve("expired")
        return "Send request expired (5-minute limit) — say 'send email to ...' again."

    service = get_gmail_service()
    if service is None:
        return "[Gmail auth failed]"

    try:
        pending = _pending_send.copy()
        msg = MIMEText(pending["body"], "plain", "utf-8")
        msg["to"] = pending["to"]
        msg["subject"] = pending["subject"]

        send_body: dict = {"raw": _encode_mime(msg)}

        if pending.get("type") == "reply":
            msg["In-Reply-To"] = pending.get("message_id", "")
            msg["References"]  = pending.get("message_id", "")
            send_body["raw"]   = _encode_mime(msg)
            if pending.get("thread_id"):
                send_body["threadId"] = pending["thread_id"]

        service.users().messages().send(userId="me", body=send_body).execute()
        _pending_send.clear()
        staging.resolve("sent", f"gmail → {pending['to']} · sent")
        return f"Sent to {pending['to']} — Subject: {pending['subject']}"

    except Exception as e:
        _pending_send.clear()
        staging.resolve("failed")
        return f"[Gmail send error: {e}]"


def reply_to_message(msg_id: str, body: str) -> str:
    """Stage a reply to an existing email for Mo to confirm before sending."""
    if not GMAIL_AVAILABLE:
        return _NOT_SET_UP

    service = get_gmail_service()
    if service is None:
        return "[Gmail auth failed]"

    try:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="metadata",
                 metadataHeaders=["Subject", "From", "Message-ID"])
            .execute()
        )
        hdrs             = msg.get("payload", {}).get("headers", [])
        original_from    = _get_header(hdrs, "From")
        original_subject = _get_header(hdrs, "Subject") or "(no subject)"
        original_msg_id  = _get_header(hdrs, "Message-ID")
        thread_id        = msg.get("threadId", "")

        reply_subject = (
            original_subject if original_subject.startswith("Re:")
            else f"Re: {original_subject}"
        )

        from core import staging

        _pending_send.clear()
        _pending_send.update({
            "type": "reply",
            "to": original_from,
            "subject": reply_subject,
            "body": body,
            "message_id": original_msg_id,
            "thread_id": thread_id,
            "expires_at": datetime.now(CAIRO_TZ) + timedelta(minutes=5),
        })
        staging.stage(
            medium="gmail",
            target=original_from,
            body=body,
            subject=reply_subject,
            expires_at=_pending_send["expires_at"],
            confirm=confirm_reply_message,
            cancel=_pending_send.clear,
        )

        preview = body[:200] + ("..." if len(body) > 200 else "")
        return (
            f"Ready to reply:\n"
            f"  To: {original_from}\n"
            f"  Subject: {reply_subject}\n"
            f"  Body: {preview}\n\n"
            f"Say 'yes send it' to confirm."
        )

    except Exception as e:
        return f"[Gmail error: {e}]"


def confirm_reply_message() -> str:
    """Actually send the staged reply after Mo confirms."""
    return confirm_send_message()
