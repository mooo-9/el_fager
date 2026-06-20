"""
Window management tools for El Fager.

List, switch, resize, minimize, maximize, move, and snap any open window.
Uses pygetwindow which wraps win32 APIs on Windows.
"""


def _find_window(title: str):
    """Return the first window whose title contains `title` (case-insensitive)."""
    import pygetwindow as gw
    title_lower = title.lower()
    matches = [w for w in gw.getAllWindows() if title_lower in w.title.lower() and w.title.strip()]
    if not matches:
        return None, f"[No window found matching '{title}']"
    return matches[0], None


def list_windows(filter: str = "") -> str:
    """List all visible window titles, optionally filtered by a keyword."""
    try:
        import pygetwindow as gw
        windows = [w.title for w in gw.getAllWindows() if w.title.strip()]
        if filter:
            f = filter.lower()
            windows = [t for t in windows if f in t.lower()]
        if not windows:
            return "No windows found." if not filter else f"No windows matching '{filter}'."
        return "Open windows:\n" + "\n".join(f"  - {t}" for t in windows)
    except Exception as e:
        return f"[list_windows failed: {e}]"


def get_active_window() -> str:
    """Return the title and position of the currently focused window."""
    try:
        import pygetwindow as gw
        w = gw.getActiveWindow()
        if not w:
            return "No active window detected."
        return f"Active: '{w.title}' at ({w.left}, {w.top}), size {w.width}x{w.height}."
    except Exception as e:
        return f"[get_active_window failed: {e}]"


def switch_to_window(title: str) -> str:
    """Bring a window to the foreground by partial title match."""
    try:
        win, err = _find_window(title)
        if err:
            return err
        # pygetwindow.activate() can silently fail on Windows 11 due to focus-steal prevention.
        # Directly use win32gui as the primary method for reliability.
        try:
            import win32gui, win32con
            hwnd = win.getHandle()
            if win32gui.IsIconic(hwnd):  # minimized — restore first
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            win.activate()  # fallback to pygetwindow
        return f"Switched to: '{win.title}'."
    except Exception as e:
        return f"[switch_to_window failed: {e}]"


def minimize_window(title: str = None) -> str:
    """Minimize a window by title (or the active window if title is omitted)."""
    try:
        import pygetwindow as gw
        if title:
            win, err = _find_window(title)
            if err:
                return err
        else:
            win = gw.getActiveWindow()
            if not win:
                return "[No active window to minimize.]"
        win.minimize()
        return f"Minimized: '{win.title}'."
    except Exception as e:
        return f"[minimize_window failed: {e}]"


def maximize_window(title: str = None) -> str:
    """Maximize a window by title (or the active window if title is omitted)."""
    try:
        import pygetwindow as gw
        if title:
            win, err = _find_window(title)
            if err:
                return err
        else:
            win = gw.getActiveWindow()
            if not win:
                return "[No active window to maximize.]"
        win.maximize()
        return f"Maximized: '{win.title}'."
    except Exception as e:
        return f"[maximize_window failed: {e}]"


def restore_window(title: str = None) -> str:
    """Restore a minimized/maximized window to normal size."""
    try:
        import pygetwindow as gw
        if title:
            win, err = _find_window(title)
            if err:
                return err
        else:
            win = gw.getActiveWindow()
            if not win:
                return "[No active window to restore.]"
        win.restore()
        return f"Restored: '{win.title}'."
    except Exception as e:
        return f"[restore_window failed: {e}]"


def close_window(title: str) -> str:
    """Send a close signal to a window (app may prompt to save unsaved work)."""
    try:
        win, err = _find_window(title)
        if err:
            return err
        win.close()
        return f"Closed: '{win.title}'."
    except Exception as e:
        return f"[close_window failed: {e}]"


def resize_window(title: str, width: int, height: int) -> str:
    """Resize a window to specific dimensions in pixels."""
    try:
        win, err = _find_window(title)
        if err:
            return err
        win.resizeTo(width, height)
        return f"Resized '{win.title}' to {width}x{height}."
    except Exception as e:
        return f"[resize_window failed: {e}]"


def move_window(title: str, x: int, y: int) -> str:
    """Move a window's top-left corner to screen coordinates (x, y)."""
    try:
        win, err = _find_window(title)
        if err:
            return err
        win.moveTo(x, y)
        return f"Moved '{win.title}' to ({x}, {y})."
    except Exception as e:
        return f"[move_window failed: {e}]"


def snap_window(title: str, position: str) -> str:
    """Snap a window to a screen half or quarter. position: left, right, top-left, top-right, bottom-left, bottom-right, maximized."""
    try:
        import pyautogui
        win, err = _find_window(title)
        if err:
            return err

        sw, sh = pyautogui.size()
        half_w, half_h = sw // 2, sh // 2

        positions = {
            "left":         (0, 0, half_w, sh),
            "right":        (half_w, 0, half_w, sh),
            "top-left":     (0, 0, half_w, half_h),
            "top-right":    (half_w, 0, half_w, half_h),
            "bottom-left":  (0, half_h, half_w, half_h),
            "bottom-right": (half_w, half_h, half_w, half_h),
            "maximized":    (0, 0, sw, sh),
            "center":       (sw // 4, sh // 4, half_w, half_h),
        }

        pos = position.lower()
        if pos not in positions:
            opts = ", ".join(positions.keys())
            return f"[Unknown position '{position}'. Options: {opts}]"

        x, y, w, h = positions[pos]
        win.restore()
        win.moveTo(x, y)
        win.resizeTo(w, h)
        return f"Snapped '{win.title}' to {position} ({w}x{h} at {x},{y})."
    except Exception as e:
        return f"[snap_window failed: {e}]"
