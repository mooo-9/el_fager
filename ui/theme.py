"""
El Fager — QSS style strings for the native surfaces.

Every value here is derived from `ui/tokens.py`; no color literals live in this
file or in widget code. The Overlay and the Command Center both run the DAWN
palette (ember on blue-black) per the design handoff's CANON table — cyan
belongs to the Cockpit alone, so there is one palette here, not two.

Fonts are bundled in `ui/assets/fonts/` and registered by `register_fonts()`,
which `main.py` calls once the QApplication exists. Nothing is fetched at
runtime; if registration is skipped the stacks fall back to Segoe UI.

They are the OFL *variable* files, not static instances, because Qt only
reaches a true weight 600 through the `wght` axis: measured against the real
static faces, QSS `font-weight` is exact at 400 and 500 but synthesizes a
bold at 600. So QSS carries the 400/500 text (nearly all of it), and anything
the type scale sets in 600 — the hero step — takes a QFont from `ui_font()`,
which sets the axis exactly.
"""

from pathlib import Path

from ui import tokens as t

# ── Fonts ────────────────────────────────────────────────────────────────────
FONT      = t.STACK        # "Space Grotesk" with a Segoe UI fallback
FONT_MONO = t.STACK_MONO   # data, transcripts, timestamps

_FONT_DIR = Path(__file__).parent / "assets" / "fonts"
_registered: list[str] = []


def register_fonts() -> list[str]:
    """Load the bundled OFL faces into Qt. Idempotent; needs a QApplication."""
    if _registered:
        return _registered
    from PyQt6.QtGui import QFontDatabase

    for path in sorted(_FONT_DIR.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id != -1:
            _registered.extend(QFontDatabase.applicationFontFamilies(font_id))
    return _registered


def ui_font(px: float, weight: int = 400, mono: bool = False):
    """A QFont on the design's type scale, with the `wght` axis set exactly.

    Use for QPainter text and for any label the scale sets in 600 — QSS
    `font-weight: 600` synthesizes instead of reaching the real face.
    """
    from PyQt6.QtGui import QFont

    f = QFont()
    f.setFamilies([t.FONT_MONO] if mono else [t.FONT_UI, "Segoe UI"])
    f.setPixelSize(round(px))
    # Axis only — calling setWeight() as well makes Qt pick a named instance
    # (or synthesize) and the axis is ignored, which is what loses the true 600.
    f.setVariableAxis(QFont.Tag("wght"), float(weight))
    return f


# ── Surfaces ─────────────────────────────────────────────────────────────────
# The overlay card floats over the desktop, so it sits just shy of opaque.
BG_CARD   = t.rgba(t.SURFACE_1, 0.97)
BG_RAISED = t.SURFACE_2   # bubbles, dialogs
BG_INPUT  = t.SURFACE_2   # text input, controls
BG_ACTIVE = t.SURFACE_3   # pressed / selected

BORDER        = t.HAIRLINE          # white @8%  — cards, separators
BORDER_STRONG = t.HAIRLINE_STRONG   # white @14% — inputs, buttons

# ── Text ─────────────────────────────────────────────────────────────────────
TEXT_PRIMARY   = t.TEXT_HI
TEXT_SECONDARY = t.TEXT_MID
TEXT_MUTED     = t.TEXT_LOW

# ── Accent + state colors ────────────────────────────────────────────────────
ACCENT        = t.EMBER
ACCENT_BRIGHT = t.EMBER_BRIGHT
ACCENT_PRESS  = t.EMBER_PRESS
ACCENT_WASH   = t.EMBER_WASH
TEXT_ON_ACCENT = t.TEXT_ON_EMBER

THINKING = t.STATE["thinking"]
SPEAKING = t.STATE["speaking"]
ERROR    = t.STATE["error"]

OK, WARN, BAD = t.OK, t.WARN, t.BAD

# The pipeline calls the middle state "processing"; the design calls it
# "thinking". Keyed to the app's vocabulary, valued from the design's.
STATE_COLORS = {
    "idle":       t.STATE["idle"],
    "listening":  t.STATE["listening"],
    "processing": t.STATE["thinking"],
    "speaking":   t.STATE["speaking"],
    "error":      t.STATE["error"],
    # Talked over — the mic is open again, so it reads as listening.
    "interrupted": t.STATE["listening"],
}

# ── Type scale (px) ──────────────────────────────────────────────────────────
# Qt stylesheets take integer px, so the design's 13.5 "ui" step rounds to 14
# at title weight and 13 in dense rows — both noted where they're used.
SZ_TITLE    = 21
SZ_EMPHASIS = 17
SZ_BODY     = 15
SZ_UI       = 13
SZ_CAPTION  = 12
SZ_DATA     = 11


# ── Card (the settings "theme" option is the brightness axis, not a light
#    theme — it raises or lowers the ground one step) ────────────────────────
def card_style(theme: str = "dark") -> str:
    bg = {
        "dark":   BG_CARD,
        "darker": t.rgba(t.SURFACE_0, 0.98),
        "oled":   t.rgba(t.BG_VOID, 0.98),
    }.get(theme, BG_CARD)
    return f"""
    QWidget#card {{
        background-color: {bg};
        border-radius: {t.R4}px;
        border: 1px solid {BORDER};
    }}
    """


HEADER_TITLE = f"""
    color: {TEXT_SECONDARY};
    font-size: {SZ_CAPTION}px;
    font-weight: 500;
    font-family: {FONT};
    letter-spacing: 2px;
"""

STATUS_LABEL = f"""
    color: {TEXT_SECONDARY};
    font-size: {SZ_UI}px;
    font-family: {FONT};
"""

# Transcripts are mono per the type spec — they read as machine output.
TRANSCRIPT_LABEL = f"""
    color: {TEXT_SECONDARY};
    font-size: {SZ_CAPTION}px;
    font-family: {FONT_MONO};
    padding: 2px 0;
"""

STATUS_BAR = f"""
    color: {TEXT_MUTED};
    font-size: {SZ_DATA}px;
    font-family: {FONT_MONO};
    padding: 0;
"""

BUBBLE_USER = f"""
    background-color: {ACCENT_WASH};
    border: 1px solid {t.rgba(ACCENT, 0.22)};
    color: {TEXT_PRIMARY};
    border-radius: {t.R3}px;
    padding: 8px 12px;
    font-size: {SZ_BODY}px;
    font-family: {FONT};
"""

BUBBLE_ASSISTANT = f"""
    background-color: {BG_RAISED};
    border: 1px solid {BORDER};
    color: {TEXT_PRIMARY};
    border-radius: {t.R3}px;
    padding: 8px 12px;
    font-size: {SZ_BODY}px;
    font-family: {FONT};
"""

TEXT_INPUT = f"""
    QLineEdit {{
        background: {BG_INPUT};
        border: 1px solid {BORDER_STRONG};
        border-radius: {t.R2}px;
        color: {TEXT_PRIMARY};
        padding: 8px 12px;
        font-size: {SZ_UI}px;
        font-family: {FONT};
    }}
    QLineEdit:focus {{
        border: 1px solid {ACCENT};
    }}
    QLineEdit::placeholder {{ color: {TEXT_MUTED}; }}
"""

# Ghost buttons: quiet by default, ember on hover, pressed feedback.
BTN_GHOST = f"""
    QPushButton {{
        background: transparent;
        color: {TEXT_MUTED};
        border: 1px solid transparent;
        border-radius: {t.R1}px;
        font-size: {SZ_CAPTION}px;
        font-family: {FONT};
        padding: 3px 8px;
    }}
    QPushButton:hover {{
        background: {ACCENT_WASH};
        color: {TEXT_PRIMARY};
        border: 1px solid {t.rgba(ACCENT, 0.24)};
    }}
    QPushButton:pressed {{
        background: {t.rgba(ACCENT_PRESS, 0.28)};
    }}
"""

BTN_CLOSE = BTN_GHOST + f"""
    QPushButton:hover {{ background: {t.rgba(ERROR, 0.78)}; color: {TEXT_PRIMARY}; }}
"""

# 6px overlay thumb, no track, no arrows — per the component spec.
SCROLL_AREA = f"""
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        border-radius: 3px;
    }}
    QScrollBar::handle:vertical {{
        background: {t.rgba("#FFFFFF", 0.14)};
        border-radius: 3px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t.rgba("#FFFFFF", 0.22)};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""

SEPARATOR = f"background-color: {BORDER};"

DIALOG = f"""
    QDialog {{ background-color: {t.SURFACE_0}; color: {TEXT_PRIMARY}; }}
    QLabel {{ color: {TEXT_SECONDARY}; font-family: {FONT}; font-size: {SZ_UI}px; }}
    QComboBox {{ background: {BG_INPUT}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_STRONG}; border-radius: {t.R1}px; padding: 4px 8px; font-family: {FONT}; }}
    QComboBox::drop-down {{ border: none; }}
    QComboBox QAbstractItemView {{ background: {BG_INPUT}; color: {TEXT_PRIMARY}; selection-background-color: {ACCENT}; }}
    QCheckBox {{ color: {TEXT_SECONDARY}; font-family: {FONT}; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; }}
    QDialogButtonBox QPushButton {{ background: {BG_INPUT}; color: {ACCENT}; border: 1px solid {BORDER_STRONG}; border-radius: {t.R1}px; padding: 5px 14px; font-family: {FONT}; }}
    QDialogButtonBox QPushButton:hover {{ background: {ACCENT}; color: {TEXT_ON_ACCENT}; }}
"""

# Command Center data cards sit inside the window, so they take the card
# radius (16) rather than the window radius (22).
DATA_CARD = f"""
    QWidget#dataCard {{
        background-color: {t.SURFACE_1};
        border-radius: {t.R3}px;
        border: 1px solid {BORDER};
    }}
"""
