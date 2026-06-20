"""
Google Workspace tool — Phase 4E.

Covers Google Drive, Google Docs, and Google Sheets via a single OAuth token.
Reuses the same data/credentials.json as Calendar and Gmail.

Setup (one-time):
  1. Google Cloud Console → APIs & Services → Enable:
       Google Drive API, Google Docs API, Google Sheets API
     (same project as Calendar: grand-verve-499512-d9)
  2. Say "search my Drive" → browser opens for OAuth → approve →
     data/token_gdrive.json written automatically.
  3. All future calls auto-refresh silently.

ID / URL handling:
  All functions accept either a bare file/doc/sheet ID or a full URL.
  Drive/Docs/Sheets URLs all contain /d/{ID}/ — _extract_id() handles both.
"""

import mimetypes
import os
import re
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

CREDENTIALS_PATH = "data/credentials.json"
TOKEN_PATH = "data/token_gdrive.json"
GDRIVE_AVAILABLE = os.path.exists(CREDENTIALS_PATH)

_NOT_SET_UP = (
    "[Google Workspace not set up — place credentials.json in the data/ folder "
    "(same file used for Calendar and Gmail). "
    "Then enable Google Drive API, Google Docs API, and Google Sheets API in "
    "Google Cloud Console for project grand-verve-499512-d9.]"
)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]

MIME_LABELS = {
    "application/vnd.google-apps.document":     "Doc",
    "application/vnd.google-apps.spreadsheet":  "Sheet",
    "application/vnd.google-apps.presentation": "Slides",
    "application/vnd.google-apps.folder":       "Folder",
    "application/pdf":                           "PDF",
}


# ── Auth ─────────────────────────────────────────────────────────────────────

def _get_service(api: str, version: str):
    """Return an authenticated Google API service client, or None on failure."""
    if not GDRIVE_AVAILABLE:
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
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
        return build(api, version, credentials=creds)
    except Exception as e:
        print(f"[El Fager] Google {api} auth failed: {e}")
        return None


def _extract_id(id_or_url: str) -> str:
    """Extract Google file/doc/sheet ID from a URL, or return the string as-is."""
    m = re.search(r"/d/([a-zA-Z0-9_-]{25,})", id_or_url)
    return m.group(1) if m else id_or_url.strip()


def _fmt_mime(mime: str) -> str:
    return MIME_LABELS.get(mime, "File")


def _fmt_date(dt_str: str) -> str:
    """Convert '2026-06-15T10:30:00.000Z' to 'Jun 15'."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%b %d")
    except Exception:
        return dt_str[:10] if dt_str else ""


# ── Google Drive ──────────────────────────────────────────────────────────────

def search_drive(query: str, n: int = 10) -> str:
    """Search Drive files by name containing the query."""
    if not GDRIVE_AVAILABLE:
        return _NOT_SET_UP
    svc = _get_service("drive", "v3")
    if svc is None:
        return "[Google Drive auth failed — check credentials.json and enable the Drive API]"
    try:
        # Escape single quotes in query to prevent API injection
        safe_q = query.replace("'", "\\'")
        results = svc.files().list(
            q=f"name contains '{safe_q}' and trashed=false",
            pageSize=n,
            fields="files(id,name,mimeType,modifiedTime,webViewLink)",
            orderBy="modifiedTime desc",
        ).execute()

        files = results.get("files", [])
        if not files:
            return f"No Drive files found matching '{query}'"

        lines = []
        for i, f in enumerate(files, 1):
            label = _fmt_mime(f.get("mimeType", ""))
            date = _fmt_date(f.get("modifiedTime", ""))
            link = f.get("webViewLink", "")
            lines.append(
                f"{i}. {f['name']} ({label}) — modified {date}\n"
                f"   ID: {f['id']}\n"
                f"   Link: {link}"
            )
        return "Drive files found:\n" + "\n".join(lines)
    except Exception as e:
        return f"[Drive error: {e}]"


def share_drive_file(file_id_or_name: str) -> str:
    """Make a Drive file shareable ('anyone with link') and return the link."""
    if not GDRIVE_AVAILABLE:
        return _NOT_SET_UP
    svc = _get_service("drive", "v3")
    if svc is None:
        return "[Google Drive auth failed]"
    try:
        # Resolve name → ID if a bare name or non-URL was passed
        fid = _extract_id(file_id_or_name)
        # If _extract_id returned the original string unchanged and it looks like a name
        # (no URL pattern matched and it's short / not a Drive ID), search for it
        if fid == file_id_or_name.strip() and len(fid) < 25:
            safe_q = fid.replace("'", "\\'")
            res = svc.files().list(
                q=f"name contains '{safe_q}' and trashed=false",
                pageSize=1,
                fields="files(id,name)",
            ).execute()
            hits = res.get("files", [])
            if not hits:
                return f"No Drive file found matching '{file_id_or_name}'"
            fid = hits[0]["id"]
            file_name = hits[0]["name"]
        else:
            meta = svc.files().get(fileId=fid, fields="name").execute()
            file_name = meta.get("name", fid)

        # Grant "anyone with link can view"
        svc.permissions().create(
            fileId=fid,
            body={"type": "anyone", "role": "reader"},
        ).execute()

        # Fetch the shareable link
        meta = svc.files().get(fileId=fid, fields="webViewLink").execute()
        link = meta.get("webViewLink", "")
        return f"Shared '{file_name}' — anyone with this link can view:\n{link}"
    except Exception as e:
        return f"[Drive error: {e}]"


def upload_to_drive(local_path: str, folder_id: str = None) -> str:
    """Upload a local file to Google Drive."""
    if not GDRIVE_AVAILABLE:
        return _NOT_SET_UP
    svc = _get_service("drive", "v3")
    if svc is None:
        return "[Google Drive auth failed]"
    try:
        from googleapiclient.http import MediaFileUpload

        path = Path(local_path)
        if not path.exists():
            return f"File not found: {local_path}"

        mime, _ = mimetypes.guess_type(str(path))
        mime = mime or "application/octet-stream"

        metadata: dict = {"name": path.name}
        if folder_id:
            metadata["parents"] = [folder_id]

        file_obj = svc.files().create(
            body=metadata,
            media_body=MediaFileUpload(str(path), mimetype=mime),
            fields="id,webViewLink",
        ).execute()

        file_id = file_obj.get("id", "")
        link = file_obj.get("webViewLink", "")
        return f"Uploaded '{path.name}' to Drive — ID: {file_id}\nLink: {link}"
    except Exception as e:
        return f"[Drive error: {e}]"


# ── Google Docs ───────────────────────────────────────────────────────────────

def _doc_to_text(doc: dict, max_chars: int = 8000) -> str:
    """Extract plain text from a Docs API document object."""
    parts = []
    total = 0
    for item in doc.get("body", {}).get("content", []):
        paragraph = item.get("paragraph")
        if not paragraph:
            continue
        line_parts = []
        for element in paragraph.get("elements", []):
            text_run = element.get("textRun")
            if text_run:
                line_parts.append(text_run.get("content", ""))
        text = "".join(line_parts)
        if not text.strip():
            continue
        parts.append(text)
        total += len(text)
        if total >= max_chars:
            parts.append("[... truncated]")
            break
    return "".join(parts)


def read_doc(doc_id: str) -> str:
    """Read the full text content of a Google Doc."""
    if not GDRIVE_AVAILABLE:
        return _NOT_SET_UP
    svc = _get_service("docs", "v1")
    if svc is None:
        return "[Google Docs auth failed — check credentials.json and enable the Docs API]"
    try:
        did = _extract_id(doc_id)
        doc = svc.documents().get(documentId=did).execute()
        title = doc.get("title", "(untitled)")
        body = _doc_to_text(doc)
        if not body.strip():
            return f"# {title}\n\n(Document is empty)"
        return f"# {title}\n\n{body}"
    except Exception as e:
        return f"[Docs error: {e}]"


def append_to_doc(doc_id: str, text: str) -> str:
    """Append a paragraph of text to the end of a Google Doc."""
    if not GDRIVE_AVAILABLE:
        return _NOT_SET_UP
    svc = _get_service("docs", "v1")
    if svc is None:
        return "[Google Docs auth failed]"
    try:
        did = _extract_id(doc_id)
        # Get the document to find the end index
        doc = svc.documents().get(documentId=did).execute()
        content = doc.get("body", {}).get("content", [])
        # End index of the last element minus 1 (before the implicit newline)
        end_index = content[-1]["endIndex"] - 1 if content else 1

        svc.documents().batchUpdate(
            documentId=did,
            body={"requests": [
                {"insertText": {
                    "location": {"index": end_index},
                    "text": "\n" + text,
                }}
            ]},
        ).execute()
        return "Added to doc"
    except Exception as e:
        return f"[Docs error: {e}]"


# ── Google Sheets ─────────────────────────────────────────────────────────────

def _fmt_table(rows: list, max_rows: int = 50) -> str:
    """Format a list of rows (list of lists) as an aligned text table."""
    if not rows:
        return "(empty)"

    truncated = False
    if len(rows) > max_rows:
        rows = rows[:max_rows]
        truncated = True

    # Compute column widths
    col_count = max(len(r) for r in rows)
    widths = [0] * col_count
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt_row(row):
        cells = [str(row[i]) if i < len(row) else "" for i in range(col_count)]
        return " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells))

    lines = [fmt_row(rows[0])]
    lines.append("-+-".join("-" * w for w in widths))
    for row in rows[1:]:
        lines.append(fmt_row(row))

    if truncated:
        lines.append(f"[... more rows not shown]")

    return "\n".join(lines)


def read_sheet(spreadsheet_id: str, range_name: str = "Sheet1") -> str:
    """Read cells from a Google Sheet and return as a formatted table."""
    if not GDRIVE_AVAILABLE:
        return _NOT_SET_UP
    svc = _get_service("sheets", "v4")
    if svc is None:
        return "[Google Sheets auth failed — check credentials.json and enable the Sheets API]"
    try:
        sid = _extract_id(spreadsheet_id)
        result = svc.spreadsheets().values().get(
            spreadsheetId=sid,
            range=range_name,
        ).execute()

        values = result.get("values", [])
        if not values:
            return f"Sheet '{range_name}' is empty"

        table = _fmt_table(values)
        return f"Sheet: {range_name}\n\n{table}"
    except Exception as e:
        return f"[Sheets error: {e}]"


def append_sheet_row(spreadsheet_id: str, sheet_name: str, values: list) -> str:
    """Append a new row of values to a Google Sheet."""
    if not GDRIVE_AVAILABLE:
        return _NOT_SET_UP
    svc = _get_service("sheets", "v4")
    if svc is None:
        return "[Google Sheets auth failed]"
    try:
        sid = _extract_id(spreadsheet_id)
        svc.spreadsheets().values().append(
            spreadsheetId=sid,
            range=f"{sheet_name}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": [values]},
        ).execute()
        row_preview = " | ".join(str(v) for v in values)
        return f"Added row to {sheet_name}: {row_preview}"
    except Exception as e:
        return f"[Sheets error: {e}]"
