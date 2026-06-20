def get_clipboard_text() -> str:
    try:
        import pyperclip
        text = pyperclip.paste()
        if not text:
            return "[Clipboard is empty]"
        if len(text) > 4000:
            return text[:4000] + "\n[... truncated]"
        return text
    except Exception:
        try:
            import win32clipboard
            win32clipboard.OpenClipboard()
            try:
                text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
            if not text:
                return "[Clipboard is empty]"
            if len(text) > 4000:
                return text[:4000] + "\n[... truncated]"
            return text
        except Exception as e:
            return f"[Clipboard read failed: {e}]"


def set_clipboard_text(text: str) -> str:
    try:
        import pyperclip
        pyperclip.copy(text)
        return f"Copied to clipboard ({len(text)} chars)."
    except Exception:
        try:
            import win32clipboard
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
            finally:
                win32clipboard.CloseClipboard()
            return f"Copied to clipboard ({len(text)} chars)."
        except Exception as e:
            return f"[Clipboard write failed: {e}]"
