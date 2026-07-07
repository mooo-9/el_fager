"""
El Fager — design system (single source of truth for the native UI).

One layered dark palette, one warm accent, one semantic color per assistant
state. Every stylesheet in the native surface pulls from here — no scattered
rgba() literals in widget code.

Palette rationale (W3 redesign): the old UI was monochrome cyan on a
near-black #040815 with flat type. This system uses layered neutrals for
depth, a single warm copper accent, and distinct listening / thinking /
speaking colors so the assistant's state is readable at a glance.
"""

# ── Layered surfaces (dark, but not flat-black) ─────────────────────────────
BG_CARD      = "rgba(22, 24, 29, 247)"   # main card
BG_RAISED    = "#1E2127"                  # bubbles, dialogs
BG_INPUT     = "#22252C"                  # text input, controls
BORDER       = "rgba(255, 255, 255, 18)"  # hairline borders
BORDER_SOFT  = "rgba(255, 255, 255, 10)"  # separators

# ── Type ─────────────────────────────────────────────────────────────────────
FONT         = "'Segoe UI Variable', 'Segoe UI', sans-serif"
TEXT_PRIMARY   = "#EDEFF3"
TEXT_SECONDARY = "#A2A9B4"
TEXT_MUTED     = "#6E7684"

# ── Accent + state colors ────────────────────────────────────────────────────
ACCENT   = "#E39660"   # warm copper — brand, focus, listening
THINKING = "#8FA3C7"   # cool steel — model is working
SPEAKING = "#7FC8A0"   # sage — audio playing
ERROR    = "#E06C75"

STATE_COLORS = {
    "idle":       TEXT_MUTED,
    "listening":  ACCENT,
    "processing": THINKING,
    "speaking":   SPEAKING,
    "error":      ERROR,
}

# ── Card (theme variants keep the settings 'theme' option working) ──────────
def card_style(theme: str = "dark") -> str:
    bg = {
        "dark":   BG_CARD,
        "darker": "rgba(14, 15, 19, 250)",
        "oled":   "rgba(0, 0, 0, 250)",
    }.get(theme, BG_CARD)
    return f"""
    QWidget#card {{
        background-color: {bg};
        border-radius: 16px;
        border: 1px solid {BORDER};
    }}
    """


HEADER_TITLE = f"""
    color: {TEXT_SECONDARY};
    font-size: 10px;
    font-weight: 600;
    font-family: {FONT};
    letter-spacing: 2px;
"""

STATUS_LABEL = f"""
    color: {TEXT_SECONDARY};
    font-size: 11px;
    font-family: {FONT};
"""

TRANSCRIPT_LABEL = f"""
    color: {TEXT_SECONDARY};
    font-size: 12px;
    font-style: italic;
    font-family: {FONT};
    padding: 2px 0;
"""

STATUS_BAR = f"""
    color: {TEXT_MUTED};
    font-size: 10px;
    font-family: {FONT};
    padding: 0;
"""

BUBBLE_USER = f"""
    background-color: rgba(227, 150, 96, 34);
    border: 1px solid rgba(227, 150, 96, 56);
    color: {TEXT_PRIMARY};
    border-radius: 11px;
    padding: 7px 11px;
    font-size: 13px;
    font-family: {FONT};
"""

BUBBLE_ASSISTANT = f"""
    background-color: {BG_RAISED};
    border: 1px solid {BORDER_SOFT};
    color: {TEXT_PRIMARY};
    border-radius: 11px;
    padding: 7px 11px;
    font-size: 13px;
    font-family: {FONT};
"""

TEXT_INPUT = f"""
    QLineEdit {{
        background: {BG_INPUT};
        border: 1px solid {BORDER};
        border-radius: 10px;
        color: {TEXT_PRIMARY};
        padding: 8px 12px;
        font-size: 13px;
        font-family: {FONT};
    }}
    QLineEdit:focus {{
        border: 1px solid {ACCENT};
    }}
    QLineEdit::placeholder {{ color: {TEXT_MUTED}; }}
"""

# Ghost buttons: quiet by default, accent on hover, pressed feedback.
BTN_GHOST = f"""
    QPushButton {{
        background: transparent;
        color: {TEXT_MUTED};
        border: 1px solid transparent;
        border-radius: 6px;
        font-size: 12px;
        font-family: {FONT};
        padding: 3px 8px;
    }}
    QPushButton:hover {{
        background: rgba(227, 150, 96, 26);
        color: {TEXT_PRIMARY};
        border: 1px solid rgba(227, 150, 96, 60);
    }}
    QPushButton:pressed {{
        background: rgba(227, 150, 96, 48);
    }}
"""

BTN_CLOSE = BTN_GHOST + """
    QPushButton:hover { background: rgba(224, 108, 117, 200); color: white; }
"""

SCROLL_AREA = f"""
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 5px;
        border-radius: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(255, 255, 255, 40);
        border-radius: 2px;
        min-height: 20px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(227, 150, 96, 120);
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""

SEPARATOR = f"background-color: {BORDER_SOFT};"

DIALOG = f"""
    QDialog {{ background-color: {BG_RAISED}; color: {TEXT_PRIMARY}; }}
    QLabel {{ color: {TEXT_SECONDARY}; font-family: {FONT}; font-size: 12px; }}
    QComboBox {{ background: {BG_INPUT}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 8px; font-family: {FONT}; }}
    QComboBox::drop-down {{ border: none; }}
    QComboBox QAbstractItemView {{ background: {BG_INPUT}; color: {TEXT_PRIMARY}; selection-background-color: {ACCENT}; }}
    QCheckBox {{ color: {TEXT_SECONDARY}; font-family: {FONT}; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; }}
    QDialogButtonBox QPushButton {{ background: {BG_INPUT}; color: {ACCENT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 14px; font-family: {FONT}; }}
    QDialogButtonBox QPushButton:hover {{ background: {ACCENT}; color: #16181D; }}
"""
