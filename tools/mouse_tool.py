"""
Mouse & keyboard control for El Fager.

Lets El Fager click, type, drag, scroll, and press hotkeys on ANY application.
Uses pyautogui with FAILSAFE=True — move mouse to top-left corner to abort.
"""

import pyautogui

pyautogui.FAILSAFE = True   # move mouse to top-left to abort runaway automation
pyautogui.PAUSE = 0.1       # small delay between calls prevents flooding


def mouse_move(x: int, y: int, duration: float = 0.3) -> str:
    """Move the mouse cursor to screen coordinates (x, y)."""
    try:
        pyautogui.moveTo(x, y, duration=duration)
        return f"Mouse moved to ({x}, {y})."
    except Exception as e:
        return f"[mouse_move failed: {e}]"


def mouse_click(x: int = None, y: int = None, button: str = "left", clicks: int = 1) -> str:
    """Click the mouse at (x, y), or at current position if x/y omitted. button: left/right/middle."""
    try:
        if x is not None and y is not None:
            pyautogui.click(x, y, button=button, clicks=clicks)
            return f"Clicked ({x}, {y}) [{button}]."
        else:
            pyautogui.click(button=button, clicks=clicks)
            pos = pyautogui.position()
            return f"Clicked at current position ({pos.x}, {pos.y}) [{button}]."
    except Exception as e:
        return f"[mouse_click failed: {e}]"


def mouse_double_click(x: int = None, y: int = None) -> str:
    """Double-click at (x, y), or at current position if omitted."""
    try:
        if x is not None and y is not None:
            pyautogui.doubleClick(x, y)
            return f"Double-clicked ({x}, {y})."
        else:
            pyautogui.doubleClick()
            pos = pyautogui.position()
            return f"Double-clicked at ({pos.x}, {pos.y})."
    except Exception as e:
        return f"[mouse_double_click failed: {e}]"


def mouse_drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> str:
    """Drag from (x1, y1) to (x2, y2) with left mouse button held."""
    try:
        pyautogui.moveTo(x1, y1, duration=0.2)
        pyautogui.dragTo(x2, y2, duration=duration, button="left")
        return f"Dragged from ({x1}, {y1}) to ({x2}, {y2})."
    except Exception as e:
        return f"[mouse_drag failed: {e}]"


def mouse_scroll(amount: int, x: int = None, y: int = None) -> str:
    """Scroll the mouse wheel. Positive = up, negative = down. Optionally scroll at (x, y)."""
    try:
        if x is not None and y is not None:
            pyautogui.scroll(amount, x=x, y=y)
        else:
            pyautogui.scroll(amount)
        direction = "up" if amount > 0 else "down"
        return f"Scrolled {abs(amount)} clicks {direction}."
    except Exception as e:
        return f"[mouse_scroll failed: {e}]"


def type_text(text: str, interval: float = 0.03) -> str:
    """Type text into the focused field. Uses clipboard-paste for Arabic/Unicode, keystrokes for ASCII."""
    try:
        # pyautogui.write() only supports ASCII keyboard scancodes.
        # For Arabic or any non-ASCII text, copy to clipboard then paste.
        is_ascii = all(ord(c) < 128 for c in text)
        if is_ascii:
            pyautogui.write(text, interval=interval)
        else:
            import pyperclip, time
            try:
                old_clip = pyperclip.paste()
            except Exception:
                old_clip = ""
            pyperclip.copy(text)
            time.sleep(0.05)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.1)
            try:
                pyperclip.copy(old_clip)
            except Exception:
                pass
        preview = text[:50] + "..." if len(text) > 50 else text
        return f"Typed: {preview}"
    except Exception as e:
        return f"[type_text failed: {e}]"


def press_key(key: str) -> str:
    """Press a single key. Examples: enter, esc, tab, backspace, delete, f5, ctrl, alt, win."""
    try:
        pyautogui.press(key)
        return f"Pressed: {key}"
    except Exception as e:
        return f"[press_key failed: {e}]"


def hotkey(*keys: str) -> str:
    """Press a key combination simultaneously. E.g. hotkey('ctrl', 'c') copies. hotkey('alt', 'tab') switches apps."""
    try:
        pyautogui.hotkey(*keys)
        combo = "+".join(keys)
        return f"Pressed hotkey: {combo}"
    except Exception as e:
        return f"[hotkey failed: {e}]"


def get_mouse_position() -> str:
    """Return the current mouse cursor position (x, y) in screen coordinates."""
    try:
        pos = pyautogui.position()
        size = pyautogui.size()
        return f"Mouse at ({pos.x}, {pos.y}). Screen size: {size.width}x{size.height}."
    except Exception as e:
        return f"[get_mouse_position failed: {e}]"


def screenshot_coords(x: int, y: int, width: int = 100, height: int = 100) -> str:
    """Capture a small region of the screen centered at (x, y) for debugging. Saves to data/."""
    try:
        import os
        from datetime import datetime
        left = max(0, x - width // 2)
        top = max(0, y - height // 2)
        region = pyautogui.screenshot(region=(left, top, width, height))
        os.makedirs("data", exist_ok=True)
        ts = datetime.now().strftime("%H%M%S")
        path = f"data/screen_region_{ts}.png"
        region.save(path)
        return f"Region screenshot saved: {path} ({width}x{height} at {left},{top})."
    except Exception as e:
        return f"[screenshot_coords failed: {e}]"
