"""
EL FAGER — DESIGN TOKENS (Python source of truth)
Import everywhere; QSS literals are generated from / synced to this file.
Spec: "El Fager Design Language.dc.html", boards 01-05.
"""

# ---- NIGHT — grounds (always cold) ----
BG_VOID    = "#07080C"   # HUD / desktop scrim
SURFACE_0  = "#0D1017"   # window base
SURFACE_1  = "#131722"   # card
SURFACE_2  = "#1A2030"   # raised / hover
SURFACE_3  = "#222A3D"   # active / selected
HAIRLINE        = (255, 255, 255, 20)   # white @ 8%
HAIRLINE_STRONG = (255, 255, 255, 36)   # white @ 14%

# ---- TEXT (warm white on cold ground) ----
TEXT_HI  = "#F2EDE6"
TEXT_MID = "#9BA3B5"
TEXT_LOW = "#5C6478"
TEXT_ON_EMBER = "#1A0F06"   # never white on ember

# ---- WARM LIGHT — the only accent ----
EMBER        = "#F09950"
EMBER_BRIGHT = "#FFBE7E"    # hover
EMBER_PRESS  = "#D07E35"
EMBER_WASH   = (240, 153, 80, 33)   # @13% — selection, tints

# ---- THE FIVE LIGHTS — assistant states ----
# Two palettes. DAWN (default) governs the compact overlay + Command Center.
# COCKPIT (v4) governs the full-screen cockpit — cyan listening / orange working / gold speaking.
STATE = {  # DAWN — compact surfaces
    "idle":      "#7E8AA3",   # ash
    "listening": "#F09950",   # ember = brand moment
    "thinking":  "#A48BF5",   # twilight violet
    "speaking":  "#FFD9A3",   # risen gold
    "error":     "#F2604F",   # flare
}
STATE_COCKPIT = {  # V4 — full-screen cockpit (JARVIS register)
    "idle":      "#7E8AA3",   # ash
    "listening": "#38E0FF",   # cyan
    "thinking":  "#F09950",   # working = ember orange
    "speaking":  "#FFD782",   # gold
    "error":     "#FF5042",   # flare
}
# Cockpit grounds run colder: void #02040A, panel #050B18, card #081120, chip #0D1B2E, hairline #16283E
# Cockpit text: hi #EAF2F7, mid #9FB1C2, low #5F7183, faint #3A4A5C
# Per-skill micro-tint dots (captions/receipts only): whatsapp #25D366, gmail #EA6C5A,
#   todoist #E8746A, calendar #5B8DEF, browser #38E0FF
SKILL_TINT = {
    "whatsapp": "#25D366", "gmail": "#EA6C5A", "todoist": "#E8746A",
    "calendar": "#5B8DEF", "browser": "#38E0FF",
}

# ---- SEMANTIC (dots, text, hairlines only — never fills) ----
OK, WARN, BAD = "#56C99C", "#EFC868", "#F2604F"

# ---- TYPE ----
FONT_UI   = "Space Grotesk"      # Latin UI/display, 400/500/600
FONT_AR   = "Alexandria"         # Arabic, one weight lighter, +1px at body
FONT_MONO = "Spline Sans Mono"   # data, transcripts, timestamps
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

# ---- SPACING (px, base 4) ----
S1, S2, S3, S4, S5, S6, S7, S8 = 4, 8, 12, 16, 20, 24, 32, 48

# ---- RADII (px) ----
R1, R2, R3, R4, R_PILL = 6, 10, 16, 22, 999

# ---- MOTION (ms) ----
T_INSTANT, T_FAST, T_STANDARD = 80, 140, 220
T_GENTLE, T_DECAY, T_BREATH   = 360, 600, 3600
# easing: swift-out (.22,1,.36,1) mechanical / sine (.37,0,.63,1) organic / exit (.4,0,1,1)

# ---- STATE MOTION SPECS ----
# idle:      scale 1->1.10, opacity .45->.85, T_BREATH sine loop
# listening: form rides mic RMS @60fps, smoothed 120ms; glow ON
# thinking:  3 orbiters @1.4s/rev + core shimmer; tool captions in mono
# speaking:  rings emitted on TTS cadence (~420ms nominal)
# error:     two 90ms flashes -> steady 75%; auto-return to idle after 4s
# transitions: idle->listening <=100ms snap; hue crossfades T_STANDARD;
#              speaking->idle T_DECAY; any->error immediate

# ---- HARD RULES ----
# 1. Nothing web-rendered on the Ctrl+Space path; overlay window pre-created.
# 2. Glow = live now (mic open / action armed). One glowing thing per view.
# 3. Never a warm surface, never a cold accent.
# 4. Organic loops pause when window hidden (zero idle CPU in tray).
