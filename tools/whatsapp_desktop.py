"""
WhatsApp Desktop, driven through Windows UI Automation.

The Windows app is WhatsApp Web inside a WebView2, and its accessibility tree
is readable: the search box, the search results, and a composer named
"Type a message to <chat>". That lets El Fager reach any chat saved in Mo's
WhatsApp by name — no phone number, no browser, no QR login.

Two things UI Automation can't do here, found by probing the real app:
  - open a chat: result rows ignore Select() and DoDefaultAction(), so a row
    is opened with one real click on its rectangle;
  - fill the composer: it's a rich editor that ignores SetValue(), so the
    message is pasted.
Clicks and keys go to whatever window is in front, so every one of them is
preceded by a check that WhatsApp is in front and — for keys — that the
composer for the right chat has focus. If a check fails, nothing is pressed.

Searching (find_chats) sets the search box's value directly and never takes
focus, so drafting a message doesn't pull WhatsApp in front of Mo. It also
crops each chat's profile photo out of one PrintWindow capture, which renders
WhatsApp even while other windows cover it — so the draft can show whose
chat it is going to.
"""

import ctypes
import io
import os
import time
from ctypes import wintypes
from typing import NamedTuple

_WINDOW_CLASS = "WinUIDesktopWin32WindowClass"
_COMPOSER_PREFIX = "Type a message to "
_RESULTS_NAME = "Search results."
_CHAT_LIST_NAME = "Chat list"
_NO_RESULTS_TEXT = "No chats, contacts or messages found"

_EDIT, _TEXT, _GROUP, _DATAITEM = 50004, 50020, 50026, 50029

_user32 = ctypes.windll.user32


class WhatsAppDesktopError(Exception):
    """A step didn't happen as expected. Nothing after it was attempted."""


class Chat(NamedTuple):
    title: str
    photo: "bytes | None"     # PNG of the profile photo as WhatsApp shows it


# ── UI Automation plumbing ────────────────────────────────────────────────────

def _uia():
    import comtypes
    import comtypes.client
    # UIA rectangles, the window capture and the cursor must share one
    # coordinate space. In a DPI-unaware thread at 125% scaling they don't:
    # the photo crops came out shifted onto the wrong part of the window.
    _user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))   # per-monitor v2
    try:
        comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
    except OSError:
        pass            # this thread already has COM
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as U
    return U, comtypes.client.CreateObject(U.CUIAutomation, interface=U.IUIAutomation)


def _wait(fn, timeout: float, step: float = 0.1):
    end = time.monotonic() + timeout
    while True:
        result = fn()
        if result:
            return result
        if time.monotonic() > end:
            return None
        time.sleep(step)


class _App:
    def __init__(self):
        self.U, self.uia = _uia()
        self.win = None

    def cond(self, prop, value):
        return self.uia.CreatePropertyCondition(prop, value)

    def find_window(self):
        self._page = None
        # Other WinUI apps share the window class, so the name is checked too.
        self.win = self.uia.GetRootElement().FindFirst(
            self.U.TreeScope_Children, self.uia.CreateAndCondition(
                self.cond(self.U.UIA_ClassNamePropertyId, _WINDOW_CLASS),
                self.cond(self.U.UIA_NamePropertyId, "WhatsApp")))
        return self.win

    def open_window(self, timeout: float = 15.0):
        if self.find_window() and self.page() and self.search_box():
            return
        os.startfile("whatsapp:")
        if not _wait(lambda: self.find_window() and self.page() and self.search_box(),
                     timeout, 0.3):
            raise WhatsAppDesktopError("WhatsApp Desktop didn't open")

    def page(self):
        """The web page inside the window. Lookups start here: from the
        window they also crawl the WebView's endlessly repeated host panes,
        and a lookup for something absent took seconds instead of ~50 ms."""
        if getattr(self, "_page", None) is None:
            self._page = self.win.FindFirst(
                self.U.TreeScope_Descendants,
                self.cond(self.U.UIA_AutomationIdPropertyId, "RootWebArea"))
        return self._page

    def search_box(self):
        # The box loses its accessible name once it holds text, but it is
        # always the first edit in the window.
        page = self.page()
        return page.FindFirst(self.U.TreeScope_Descendants,
                              self.cond(self.U.UIA_ControlTypePropertyId, _EDIT)) if page else None

    def value(self, element):
        return element.GetCurrentPattern(self.U.UIA_ValuePatternId).QueryInterface(
            self.U.IUIAutomationValuePattern)

    def composer(self):
        # FindAll over the whole window loops through the WebView's repeated
        # subtrees, so it's the first edit that isn't the search box.
        search = self.search_box()
        if not search:
            return None
        found = self.page().FindFirst(self.U.TreeScope_Descendants, self.uia.CreateAndCondition(
            self.cond(self.U.UIA_ControlTypePropertyId, _EDIT),
            self.uia.CreateNotCondition(
                self.cond(self.U.UIA_NamePropertyId, search.CurrentName))))
        if found and found.CurrentName.startswith(_COMPOSER_PREFIX):
            return found
        return None

    def _table(self, name: str):
        page = self.page()
        return page.FindFirst(self.U.TreeScope_Descendants,
                              self.cond(self.U.UIA_NamePropertyId, name)) if page else None

    def _rows(self, table) -> list:
        rows = table.FindAll(self.U.TreeScope_Children, self.uia.CreateTrueCondition())
        return [rows.GetElement(i) for i in range(rows.Length)]

    def _chat_list_top(self) -> list[str]:
        table = self._table(_CHAT_LIST_NAME)
        return [r.CurrentName for r in self._rows(table)[:3]] if table else []

    def search(self, query: str):
        """Type the query into the search box and return the result rows."""
        self.clear_search()
        unfiltered = self._chat_list_top()
        self.value(self.search_box()).SetValue(query)
        started = time.monotonic()
        last, retried = None, False
        while time.monotonic() - started < 8.0:
            time.sleep(0.25)
            table = self._table(_RESULTS_NAME)
            if not table:
                if self._table(_NO_RESULTS_TEXT):
                    return []
                if not retried and time.monotonic() - started > 3.0:
                    # Once, the results never appeared for a query that worked
                    # on every other try; typing it again recovers that.
                    print(f"[El Fager] WhatsApp search for {query!r} showed no results; retrying")
                    self.value(self.search_box()).SetValue("")
                    time.sleep(0.3)
                    self.value(self.search_box()).SetValue(query)
                    retried = True
                continue
            rows = self._rows(table)
            names = [r.CurrentName for r in rows]
            # WhatsApp first lists every chat under "Search results." and
            # swaps the matches in ~half a second later; that first list was
            # being read as the answer.
            if unfiltered and names[1:1 + len(unfiltered)] == unfiltered:
                last = None
                continue
            if names == last:
                return rows
            last = names
        return []

    def clear_search(self):
        box = self.search_box()
        if not (box and self.value(box).CurrentValue):
            return
        self.value(box).SetValue("")
        # Wait for WhatsApp to actually leave search, or a window minimised
        # straight after keeps showing the old query the next time — and a
        # leftover "No chats … found" made the next search return nothing.
        _wait(lambda: not self._table(_RESULTS_NAME)
              and not self._table(_NO_RESULTS_TEXT), 2.0)

    def title_of(self, row) -> "str | None":
        """The chat's name as saved. WhatsApp splits it into pieces around
        the matched text ("M", "ah", "mod"), so the pieces are joined."""
        walker = self.uia.RawViewWalker

        def walk(element, parent_type, depth):
            if depth > 8:
                return None
            if element.CurrentControlType == _GROUP and parent_type == _DATAITEM:
                pieces, child = [], walker.GetFirstChildElement(element)
                while child:
                    if child.CurrentControlType != _TEXT:
                        pieces = []
                        break
                    pieces.append(child.CurrentName or "")
                    child = walker.GetNextSiblingElement(child)
                if pieces:
                    return "".join(pieces).replace("\xa0", " ").strip()
            child = walker.GetFirstChildElement(element)
            while child:
                found = walk(child, element.CurrentControlType, depth + 1)
                if found:
                    return found
                child = walker.GetNextSiblingElement(child)
            return None

        return walk(row, None, 0)

    def photo_rect(self, row):
        """The avatar: the first square group in the row. It has no image
        element of its own in the accessibility tree."""
        walker = self.uia.RawViewWalker
        queue = [row]
        while queue:
            element = queue.pop(0)
            r = element.CurrentBoundingRectangle
            w, h = r.right - r.left, r.bottom - r.top
            if element.CurrentControlType == _GROUP and 30 <= w <= 120 and abs(w - h) <= 3:
                return r
            child = walker.GetFirstChildElement(element)
            while child:
                queue.append(child)
                child = walker.GetNextSiblingElement(child)
        return None

    def is_section(self, row) -> bool:
        return not row.FindFirst(self.U.TreeScope_Children,
                                 self.cond(self.U.UIA_ControlTypePropertyId, _DATAITEM))

    def hwnd(self) -> int:
        return self.win.CurrentNativeWindowHandle


# ── Public API ────────────────────────────────────────────────────────────────

def find_chats(query: str) -> list[Chat]:
    """The chats (contacts and groups) WhatsApp lists for a search, with their
    profile photos, in WhatsApp's own order. Message-text hits are left out."""
    import _ctypes

    app = _App()
    if not app.find_window():
        app.open_window()      # not running: launching it is the only way in
    hwnd = app.hwnd()
    # Minimised, WhatsApp stops rendering: searches returned the previous
    # query's rows and no photos, and sometimes its page wasn't there at all —
    # which used to launch WhatsApp in front of Mo mid-draft. It is restored
    # at the bottom of the window stack instead — behind everything, focus
    # untouched — and minimised again after.
    minimised = bool(_user32.IsIconic(hwnd))
    if minimised:
        _restore_behind(hwnd)
    try:
        if not _wait(lambda: app.page() and app.search_box(), 5.0, 0.2):
            raise WhatsAppDesktopError("WhatsApp didn't finish loading")
        for attempt in range(3):
            try:
                return _read_chats(app, app.search(query))
            except _ctypes.COMError:
                if attempt == 2:       # rows kept re-rendering under us
                    raise WhatsAppDesktopError("WhatsApp's search kept changing")
                app.clear_search()
                time.sleep(0.3)
    finally:
        app.clear_search()
        if minimised:
            _user32.ShowWindow(hwnd, 7)            # SW_SHOWMINNOACTIVE


def _restore_behind(hwnd: int) -> None:
    flags = 0x0001 | 0x0002 | 0x0010               # NOSIZE | NOMOVE | NOACTIVATE
    _user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, flags)   # HWND_BOTTOM
    _user32.ShowWindow(hwnd, 4)                    # SW_SHOWNOACTIVATE
    _user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, flags)


def _read_chats(app: _App, rows) -> list[Chat]:
    shot = _capture(app.hwnd())
    chats: list[Chat] = []
    section = ""
    for row in rows:
        if app.is_section(row):
            section = (row.CurrentName or "").strip().lower()
            continue
        if section == "messages":
            break
        title = app.title_of(row)
        if title and all(c.title != title for c in chats):
            chats.append(Chat(title, _crop_png(shot, app.photo_rect(row))))
    return chats


def _capture(hwnd: int):
    """The window as it is drawn, whatever covers it. None when minimised
    (nothing is drawn) or when the capture fails."""
    from PIL import Image

    if _user32.IsIconic(hwnd):
        return None
    gdi = ctypes.windll.gdi32
    rect = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    window_dc = _user32.GetWindowDC(hwnd)
    mem_dc = gdi.CreateCompatibleDC(window_dc)
    bitmap = gdi.CreateCompatibleBitmap(window_dc, w, h)
    gdi.SelectObject(mem_dc, bitmap)
    try:
        if not _user32.PrintWindow(hwnd, mem_dc, 2):      # PW_RENDERFULLCONTENT
            return None
        header = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), w, -h, 1, 32)
        pixels = ctypes.create_string_buffer(w * h * 4)
        gdi.GetDIBits(mem_dc, bitmap, 0, h, pixels, ctypes.byref(header), 0)
        image = Image.frombuffer("RGBA", (w, h), pixels.raw, "raw", "BGRA", 0, 1)
        return image.convert("RGB"), rect.left, rect.top
    finally:
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(mem_dc)
        _user32.ReleaseDC(hwnd, window_dc)


def _crop_png(shot, rect) -> "bytes | None":
    if shot is None or rect is None:
        return None
    image, left, top = shot
    box = (rect.left - left, rect.top - top, rect.right - left, rect.bottom - top)
    if box[0] < 0 or box[1] < 0 or box[2] > image.width or box[3] > image.height:
        return None           # scrolled out of the window: not drawn
    out = io.BytesIO()
    image.crop(box).save(out, "PNG")
    return out.getvalue()


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def send(title: str, message: str) -> None:
    """Open the chat named exactly `title` and send `message`. Raises
    WhatsAppDesktopError at the first step that fails; nothing after it runs."""
    import keyboard
    import pyperclip

    app = _App()
    previous = _user32.GetForegroundWindow()
    was_minimised = bool(app.find_window() and _user32.IsIconic(app.hwnd()))
    os.startfile("whatsapp:")
    app.open_window()
    hwnd = app.hwnd()
    if not _wait(lambda: _user32.GetForegroundWindow() == hwnd, 8.0):
        raise WhatsAppDesktopError("WhatsApp didn't come to the front")

    try:
        row = next((r for r in app.search(title)
                    if not app.is_section(r) and app.title_of(r) == title), None)
        if row is None:
            raise WhatsAppDesktopError(f"couldn't find the chat '{title}'")
        _click_center(row, hwnd)
    finally:
        app.clear_search()

    want = _COMPOSER_PREFIX + title
    composer = _wait(lambda: (c := app.composer()) and c.CurrentName == want and c, 5.0)
    if not composer:
        raise WhatsAppDesktopError(f"the chat with '{title}' didn't open")
    # WhatsApp puts the cursor in the composer when a chat opens. Not
    # SetFocus(): that hands the foreground to the WebView's own window, and
    # UIA's focused element is the app's host pane, not the composer.
    def focused_on_composer() -> bool:
        return (_user32.GetForegroundWindow() == hwnd
                and composer.CurrentName == want
                and bool(composer.CurrentHasKeyboardFocus))

    if not _wait(focused_on_composer, 1.5):
        _click_center(composer, hwnd)
        if not _wait(focused_on_composer, 1.5):
            raise WhatsAppDesktopError("couldn't put the cursor in the message box")
    if app.value(composer).CurrentValue.strip():
        raise WhatsAppDesktopError(
            f"there's already unsent text in the chat with '{title}'")

    saved_clipboard = _read_clipboard(pyperclip)
    try:
        pyperclip.copy(message)
        if not focused_on_composer():
            raise WhatsAppDesktopError("WhatsApp lost focus before pasting")
        keyboard.press_and_release("ctrl+v")
        if not _wait(lambda: app.value(composer).CurrentValue.strip(), 3.0):
            raise WhatsAppDesktopError("the message didn't paste")
        if not focused_on_composer():
            raise WhatsAppDesktopError(
                "WhatsApp lost focus before sending — the message is typed "
                "in the chat but not sent")
        keyboard.press_and_release("enter")
        if not _wait(lambda: not app.value(composer).CurrentValue.strip(), 5.0):
            raise WhatsAppDesktopError(
                "pressed send but the message is still in the box")
    finally:
        if saved_clipboard is not None:
            pyperclip.copy(saved_clipboard)

    if previous and previous != hwnd:
        _user32.SetForegroundWindow(previous)
    if was_minimised:
        _user32.ShowWindow(hwnd, 7)                # back how Mo left it


def _click_center(element, hwnd: int) -> None:
    rect = element.CurrentBoundingRectangle
    if rect.right <= rect.left or rect.bottom <= rect.top:
        raise WhatsAppDesktopError("the chat isn't visible in the results")
    if _user32.GetForegroundWindow() != hwnd:
        raise WhatsAppDesktopError("WhatsApp lost focus before opening the chat")
    saved = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(saved))
    _user32.SetCursorPos((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
    _user32.mouse_event(0x0002, 0, 0, 0, 0)     # left down
    _user32.mouse_event(0x0004, 0, 0, 0, 0)     # left up
    _user32.SetCursorPos(saved.x, saved.y)


def _read_clipboard(pyperclip) -> "str | None":
    try:
        return pyperclip.paste()
    except Exception:
        return None
