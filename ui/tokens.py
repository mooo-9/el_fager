"""
El Fager — design tokens. The single source of truth for every color, size,
and duration in the native UI.

Synced from `docs/design/design_handoff_el_fager/tokens/el_fager_tokens.py`
(the handoff's stated source of truth). Values that the handoff records only
as prose — the Cockpit grounds and text tiers — are lifted here as real
constants so the Cockpit can be built off the same module. When the handoff
and a mock disagree, this file wins; when this file and the handoff disagree,
the handoff wins and this file gets re-synced.

Two palettes, per the handoff's CANON table:
  DAWN    — Overlay (Ctrl+Space) and Command Center. Ember on blue-black.
  COCKPIT — the full-screen primary surface. Cyan / orange / gold on void.
"""


def rgba(hex_color: str, alpha: float) -> str:
    """QSS `rgba(r, g, b, a)` from a #RRGGBB literal and a 0..1 alpha."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha:.3f})"


# ═══════════════════════════════════════════════════════════════════════════
# DAWN — Overlay + Command Center
# ═══════════════════════════════════════════════════════════════════════════

# Grounds (always cold)
BG_VOID   = "#07080C"   # desktop scrim
SURFACE_0 = "#0D1017"   # window base
SURFACE_1 = "#131722"   # card
SURFACE_2 = "#1A2030"   # raised / hover
SURFACE_3 = "#222A3D"   # active / selected

HAIRLINE        = rgba("#FFFFFF", 0.08)
HAIRLINE_STRONG = rgba("#FFFFFF", 0.14)

# Text (warm white on cold ground)
TEXT_HI  = "#F2EDE6"
TEXT_MID = "#9BA3B5"
TEXT_LOW = "#5C6478"
TEXT_ON_EMBER = "#1A0F06"   # never white on ember

# Warm light — the only accent
EMBER        = "#F09950"
EMBER_BRIGHT = "#FFBE7E"    # hover
EMBER_PRESS  = "#D07E35"
EMBER_WASH   = rgba(EMBER, 0.13)   # selection, tints

# The five lights
STATE = {
    "idle":      "#7E8AA3",   # ash
    "listening": "#F09950",   # ember = brand moment
    "thinking":  "#A48BF5",   # twilight violet
    "speaking":  "#FFD9A3",   # risen gold
    "error":     "#F2604F",   # flare
}

# Semantic (dots, text, hairlines only — never fills)
OK, WARN, BAD = "#56C99C", "#EFC868", "#F2604F"


# ═══════════════════════════════════════════════════════════════════════════
# COCKPIT — full-screen primary surface
# ═══════════════════════════════════════════════════════════════════════════

CK_VOID     = "#02040A"
CK_PANEL    = "#050B18"
CK_CARD     = "#081120"
CK_CHIP     = "#0D1B2E"
CK_HAIRLINE = "#16283E"

CK_TEXT_HI    = "#EAF2F7"
CK_TEXT_MID   = "#9FB1C2"
CK_TEXT_LOW   = "#5F7183"
CK_TEXT_FAINT = "#3A4A5C"
CK_TEXT_ON_FILL = "#04121A"   # on cyan/gold fills — never white

CK_STATE = {
    "idle":      "#7E8AA3",   # ash
    "listening": "#38E0FF",   # cyan
    "thinking":  "#F09950",   # working = orange
    "speaking":  "#FFD782",   # gold
    "error":     "#FF5042",   # flare
}

# The sphere's own state colours (COLORS in ui/assets/cockpit_orb.html), for
# what sits beside it and tracks its state: the state chip and the voice bar.
CK_ORB = {
    "idle":      "#96B4FF",   # pale blue — rest is speech turned down
    "listening": "#38E0FF",   # cyan
    "thinking":  "#4870FF",   # deep blue
    "speaking":  "#B060FF",   # purple
    "error":     "#FF5042",   # flare
}

# Per-skill micro-tints — captions, receipts, and ledger dots only
SKILL_TINT = {
    "whatsapp": "#25D366", "gmail":   "#EA6C5A", "todoist": "#E8746A",
    "calendar": "#5B8DEF", "browser": "#38E0FF",
}

# Trust Ledger categories — what kind of thing an entry records.
LEDGER_TINT = {
    "sent":    CK_STATE["speaking"],   # gold
    "changed": SKILL_TINT["calendar"], # blue
    "logged":  OK,                     # green
    "learned": STATE["thinking"],      # violet
    "read":    CK_STATE["listening"],  # cyan
    "acted":   CK_STATE["thinking"],   # orange
    "revoked": CK_STATE["error"],      # flare
}


# ═══════════════════════════════════════════════════════════════════════════
# TYPE
# ═══════════════════════════════════════════════════════════════════════════

FONT_UI   = "Space Grotesk"      # Latin UI/display, 400/500/600
FONT_MONO = "Spline Sans Mono"   # data, transcripts, timestamps

STACK      = f"'{FONT_UI}', 'Segoe UI', sans-serif"
STACK_MONO = f"'{FONT_MONO}', 'Consolas', monospace"

TYPE = {  # name: (px, line_height, weight)
    "hero":     (44, 1.10, 600),
    "display":  (28, 1.20, 500),
    "title":    (21, 1.30, 500),
    "emphasis": (17, 1.45, 500),
    "body":     (15, 1.55, 400),
    "ui":       (13.5, 1.40, 500),
    "caption":  (12, 1.40, 400),
    "data":     (12, 1.50, 400),  # mono
}

# ── Spacing (px, base 4) ────────────────────────────────────────────────────
S1, S2, S3, S4, S5, S6, S7, S8 = 4, 8, 12, 16, 20, 24, 32, 48

# ── Radii (px) ──────────────────────────────────────────────────────────────
R1, R2, R3, R4, R_PILL = 6, 10, 16, 22, 999

# ── Motion (ms) ─────────────────────────────────────────────────────────────
T_INSTANT, T_FAST, T_STANDARD = 80, 140, 220
T_GENTLE, T_DECAY, T_BREATH   = 360, 600, 3600
# easing: swift-out (.22,1,.36,1) mechanical / sine (.37,0,.63,1) organic
#         / exit (.4,0,1,1). No springs, no bounce.
