# Handoff: El Fager — Voice-First Desktop AI Assistant

## Overview

El Fager ("the dawn") is a Jarvis-style, voice-first personal AI assistant for one power user (**Mo**) on **Windows 11**. Press **Ctrl+Space** or say **"hey Fager"**, speak, and get a spoken answer streamed back while it acts — reads/drafts Gmail & WhatsApp, manages calendar/Todoist, reads news, analyzes the screen, drives a browser, tracks health, remembers facts, and runs proactive routines. Every outbound action goes through **stage → preview → confirm**. It is **bilingual** (English + Egyptian Arabic, code-switched, full RTL). It lives in the system tray, ambient until summoned.

Target stack: **Python + PyQt6** (QSS styling + QPainter custom paints), with a few **QWebEngine** panels (real HTML/CSS/JS) loaded lazily, plus a companion **phone PWA**.

## About the design files

The files in `mocks/` are **design references authored in HTML** (a lightweight component runtime, `support.js`, renders the `.dc.html` files — open any in a browser, serving the folder so `support.js` loads, e.g. `python -m http.server`). **They are not production code to copy.** The task is to **recreate these designs in El Fager's real environment**: native Qt widgets styled with QSS + hand-painted QPainter visuals for the everyday surfaces, and QWebEngine (port the HTML/JS render loops verbatim) for the animated orb / rich panels. Where an HTML mock uses CSS animation or canvas, the Notes below say whether it should become QSS, QPainter, or QWebEngine.

## Fidelity: HIGH

Final colors, typography, spacing, motion, and interactions. Recreate pixel-accurately using the exact tokens in `tokens/`. `tokens/el_fager_tokens.py` is the **source of truth**; `.qss` and `.css` are generated views of it.

---

## CANON — what is current (read before anything)

The design evolved across versions. **The full-screen Cockpit is the primary surface and its cyan/orange/gold state palette is canonical.** The earlier warm "dawn" palette (ember/violet/gold on blue-black) remains canon **only for the compact Overlay and the Command Center**. When two references disagree, the newer wins. Priority: **8a > 5a > 4a(Cockpit) > 3a > 2a > 1a**.

| Surface | Palette | Reference mock |
|---|---|---|
| **Cockpit** (full-screen "the Ember" orb) — PRIMARY | Cyan/orange/gold | `El Fager Cockpit v2.dc.html` |
| **Overlay** (Ctrl+Space, 384px) | Dawn (ember) + horizon header | `El Fager Voice Overlay.dc.html` |
| **Command Center** (dashboard) | Dawn + horizon header + day-arc | `El Fager Command Center Prototype.dc.html` |
| **Settings / Onboarding** | Cockpit cyan | `El Fager Settings.dc.html`, `El Fager Onboarding.dc.html` |
| **HUD** (early full-screen orb) | Ember | `El Fager HUD Prototype.dc.html` (superseded by Cockpit) |
| **Sound cues** | — | `El Fager Sound Cues.dc.html` |
| **Full spec doc** (14 boards, newest-first) | — | `El Fager Design Language.dc.html` |
| **Index** (map of everything) | — | `El Fager - Index.dc.html` |

---

## Design tokens

### Cockpit palette (CANONICAL primary surface)
| Role | Hex |
|---|---|
| Void ground | `#02040A` |
| Surface | `#050B18` / `#081120` |
| Depth wash | indigo `#0D1B2E` → teal |
| Text hi / mid / low | `#EAF2F7` / `#9FB1C2` / `#5F7183` |
| State · idle | `#7E8AA3` (ash) |
| State · **listening** | `#38E0FF` (cyan) — 48-bar radial waveform rides mic amplitude |
| State · **working** | `#F09950` (orange) — rings 2–3× speed + radar sweep |
| State · **speaking** | `#FFD782` (gold) — rings emitted ~420ms |
| State · **error** | `#FF5042` (flare) — flicker, rings halt |
| Text on cyan/gold fills | `#04121A` (never white) |
| Skill tints (dots only) | whatsapp `#25D366` · calendar `#5B8DEF` · gmail `#EA6C5A` · todoist `#E8746A` · browser `#38E0FF` |
| Semantic ok/warn/bad | `#56C99C` / `#EFC868` / `#FF5042` |

### Dawn palette (Overlay + Command Center only)
| Role | Hex |
|---|---|
| Grounds | void `#07080C` · surface.0 `#0D1017` · .1 `#131722` · .2 `#1A2030` · .3 `#222A3D` |
| Text hi / mid / low | `#F2EDE6` / `#9BA3B5` / `#5C6478` |
| Accent ember / bright / press | `#F09950` / `#FFBE7E` / `#D07E35` |
| Text on ember | `#1A0F06` |
| States | idle ash `#7E8AA3` · listening ember `#F09950` · thinking violet `#A48BF5` · speaking gold `#FFD9A3` · error `#F2604F` |

### Type
- **Space Grotesk** — Latin UI/display, weights 400/500/600
- **Alexandria** — Arabic, weights 300/400/500 (one step lighter than Latin; +1px at body size). Egyptian register, never MSA.
- **Spline Sans Mono** — data, transcripts, timestamps, kbd hints
- Stack everywhere: `"Space Grotesk", "Alexandria"` so code-switched lines set themselves. All OFL; bundle and register via `QFontDatabase.addApplicationFont` at boot — never fetch at runtime.
- Scale (desktop): hero 44/1.1/600 · display 28/1.2/500 · title 21/1.3/500 · emphasis 17/1.45/500 · body 15/1.55/400 · ui 13.5/1.4/500 · caption 12/1.4/400 · data 11–13 mono.

### Spacing / radii / motion
- Spacing base-4: 4 · 8 · 12 · 16 · 20 · 24 · 32 · 48.
- Radii: chips 6 · buttons/inputs 10 · cards/bubbles 16 · windows 22 · pill 999.
- Durations: 80ms hover/press · 140ms summon/dismiss · 220ms state hue crossfade · 360ms dialogs · 600ms speaking→idle decay · 3600ms idle breath.
- Easing: mechanical `cubic-bezier(.22,1,.36,1)` · organic `cubic-bezier(.37,0,.63,1)` · exit `cubic-bezier(.4,0,1,1)`. No springs, no bounce.

---

## Hard rules (violating these breaks the design)

1. **Nothing web-rendered on the Ctrl+Space path.** The overlay window is pre-created at boot and only shown/hidden. Summon = one frame to visible + a 140ms entrance (opacity 0→1, translateY 6→0, scale .985→1). The mic opens *before* the animation ends. If a feature costs summon latency, the feature loses.
2. **Glow = live.** A glowing element means a mic is open OR an action is staged — never decoration. One glowing thing per view.
3. **Stage → preview → confirm for every outbound action.** No auto-send timers. The preview renders in the target medium's shape (a WhatsApp-style bubble, an email header block). Confirm is voice ("ابعت"/"send") or click.
4. **State is never signalled by color alone** — always hue + a motion signature + a text label (accessibility).
5. **Organic loops pause when a window is hidden** — zero idle CPU in the tray. UI never breathes; the assistant never snaps.
6. **RTL mirrors per conversation language, not OS locale** (Mo flips mid-day). Mirrored: alignment, bubble tails, mic side, chevrons, dot-before-label order. NOT mirrored: state colors, kbd hints, clock times, sparkline/timeline time axes (time flows left→right always).
7. **No light theme.** Daytime concession is a brightness axis (raise surfaces one step + text contrast), not an inverted theme.

---

## The five states (the heart of the UI)

Voice-first ⇒ the single most important element is showing what the assistant is doing. Each state = unique hue + motion, legible from 4px (overlay dot) to full-screen (Cockpit orb).

| State | Cockpit hue | Motion signature | Transition |
|---|---|---|---|
| idle | ash `#7E8AA3` | slow breath, 3.6s sine; ambient after 60s silence (readouts fade to 0%) | wake on voice/click 140ms |
| listening | cyan `#38E0FF` | 48-bar radial waveform rides mic RMS @60fps, smoothed 120ms | idle→listening ≤100ms snap |
| working | orange `#F09950` | ring 2–3× speed + radar sweep; step ledger fills | 220ms hue crossfade |
| speaking | gold `#FFD782` | rings emitted outward on TTS cadence ~420ms | first ring on first syllable |
| error | flare `#FF5042` | two ~90ms flashes then steady; rings halt | auto-return to idle after 4s |

**Orb build (QWebEngine, canonical `tick()` in `El Fager Cockpit v2.dc.html`):** white-hot core, 60-tick ring, counter-rotating segment band, blade ring, crosshairs, polar grid, scanlines, indigo→teal depth wash. Single lerped RGB drives every element (`cur += (target−cur)*0.07` per frame) so a state change is one variable. 60fps on integrated GPU. Honor `prefers-reduced-motion`: orb stops rotating → still core + one slow opacity breath; waveform → static level meter; text appears in one paint.

---

## Screens / views

### Cockpit (primary) — `El Fager Cockpit v2.dc.html`
- **Layout:** full-screen `#02040A`; centered orb; four corner readouts (time 12h AM/PM, next event, today stats, skills online) with state-tinted hairline borders; bottom bar (mic-live status + `?` keyboard button); staged-action card anchors just above the bottom bar (never clipped).
- **Attention states:** ambient (orb only, readouts 0%) → ready (readouts 100%) → exchange (readouts dim to 12%, words own the stage).
- **Exchange model (voice-first, no chat thread):** HEARD (your words large while speaking, live bars) → DOING (heard line shrinks to mono caption; vertical **step ledger** appears under the orb — per-skill tinted dot shimmers while active, green ✓ done, red on fail) → ANSWER (spoken first; streamed caption; a transient **data moment** viz may materialize beside it — day-arc, macro bars, timeline, mail rows — and fades with the exchange) → RECEIPT (one green-dot mono line in the corner ledger, max 3 kept).
- **Keyboard:** Ctrl+Space summon · Space push-to-talk · Enter confirm staged / Send-all · Esc cancel·dismiss·close (also clears a staged queue) · T type · ? keyboard-map overlay. Ignored while an input is focused.
- **Confirmation depth:** multiple staged cards render side-by-side with a queue badge ("1 OF 2") + own Send/Cancel; a **Send all** batch button appears; every send raises a **6-second Undo toast** ("Message sent" / "N messages sent"); Undo pulls the receipts back.
- **Failure:** failed ledger step turns red and waits (no auto-dismiss) with Retry / Skip + "SAY RETRY OR SKIP". **Ambiguity → clarify, never guess:** "tell Ali…" with two known Alis short-circuits before any tool call and offers two pickable option cards.
- **Barge-in:** talking over TTS interrupts immediately; half-spoken answer collapses to a dim "… · INTERRUPTED" caption; orb snaps to listening.
- **Wake-word bloom:** voice-wake fires a bright double ring from the core (~900ms); click-wake is silent.
- **Arabic-first labels:** in an Arabic exchange the Arabic state label leads (larger/brighter), English recedes — layout never mirrors mid-conversation, only text hierarchy flips.

### Overlay — `El Fager Voice Overlay.dc.html`
384px column anchored to the screen edge nearest the cursor. Horizon header (1px state-hue gradient line + 5px "sun" dot straddling it; glow pools above only while live). Same HEARD→DOING→ANSWER→RECEIPT exchange, compact. Typing hidden behind a key icon; produces the identical exchange. Native Qt, zero web content, paints in one frame.

### Command Center — `El Fager Command Center Prototype.dc.html`
12-col / 24px gutter / 48px margin, min 1100px. Greeting + briefing prose (the assistant's synthesis) → data cards (calendar, tasks, mail, news, health) → "it's getting to know me" row (learned facts as forgettable chips, active skills, one proposed automation needing a yes) → global command bar (same brain). Health card uses the **day-arc** (180° arc over a hairline horizon; gold sun rides the fill head; past target the sun turns warn-amber; animate only on first paint, 600ms sweep) + macro bars + weight/sleep sparklines. Every card footer has ONE voice-runnable action.

### Trust Ledger — `El Fager Trust Ledger.dc.html`  **(new, canonical)**
The append-only record of everything El Fager did on Mo's behalf — the trust anchor for an agent holding his Gmail/WhatsApp. Reached from the cockpit bottom bar (list icon, left of the gear).
- **Row anatomy:** time (12h) · category dot (skill/category tinted, glowing) · kicker (channel) · title · target chip · body in the target medium's words · **provenance line** in mono ("YOU SAID 'ابعت لعمر' · CONFIRMED BY VOICE" / "INFERRED FROM 6 EXCHANGES · CONFIDENCE HIGH" / "PROPOSED AUTOMATION YOU APPROVED JUL 9"). Every entry says *why* it happened.
- **Categories + hues:** sent gold · changed blue · logged green · learned violet · read cyan · acted orange · revoked flare. Filter pills: All / Sent / Changed / Read / Learned.
- **Voice search:** the search field takes natural language in both languages ("what did you send Omar?", "ابعتلي كل حاجة اتبعتت امبارح"); the answer streams in a gold-ruled strip labelled "ANSWERED FROM THE LEDGER, NOT THE MODEL" — it never speculates, it reads the record.
- **Retroactive revoke:** entries inside their reversal window carry a medium-specific action (Delete for all · Restore old time · Remove entry · Forget). Past it they read **SEALED**.
- **THE LAW (footer, non-negotiable):** append-only — nothing is ever edited or deleted. A revoke writes a **new** flare-tinted entry that undoes the old one; the original stays visible and marked REVOKED. Stored locally, encrypted at rest, never leaves the machine.
- Header counters: total entries (30 days) and **still revocable** — the second number is the one that matters.

### Settings — `El Fager Settings.dc.html`
Left rail + 5 sections, 120ms cross-fade between them; gear in cockpit → Settings, "Back to cockpit" in rail. **Voice** (wake word, reply-language pills Match/EN/AR, barge-in + sound-cue toggles), **Routines** (morning/evening/focus/gym, each schedule + toggle), **Skills** (per-skill permission line + toggle; inline rule "anything that leaves the machine always stages first"), **Memory** (tagged facts, per-fact Forget, search, count, undo), **System** (start with Windows, ambient delay 30s/60s/2m, local-data statement). Toggle: 40×22 track, 18px knob, cyan@80% on / white@12% off, 140ms. `uiLanguage` prop mirrors the whole surface to RTL.

### Onboarding — `El Fager Onboarding.dc.html`
4 steps, orb present from frame one changing hue per step: Name → voice calibration (bilingual test line → "VOICE LOCKED" receipt) → skill permissions (staging rule has no off switch) → wake-word test. Continue gates on completion; ends with the assistant speaking ("تحت أمرك"), not a tour.

### Proactive — the Knock Rule
Knock (tray sun brightens + soft chime) → one-line banner naming what it has → speaks only on invitation or on speak-first routines. Unanswered knocks fade to Command Center receipts after 30s. Focus mode holds knocks → exit digest; gym mode is voice-only big-text; evening shutdown ends with a visible orb sleep (600ms decay to ash).

### Edge states
Offline = ash orb, stopped rings, queued amber-dashed action cards. Mic busy/denied = amber struck-through bar + auto-open typing. Updating = slow 50% cyan pulse, tick ring becomes a progress arc, read-only voice stays. Low battery = earlier ambient, half particles, 30fps.

---

## Sound design — implementation spec

Reference implementation: **`El Fager Sound Cues.dc.html`** (Web Audio, synthesized live — click any cue). Recreate in the app with the same synthesis so no audio assets need shipping. Global chain: each voice → soft-knee **compressor** (threshold −20, knee 22, ratio 3, attack 3ms, release 180ms) → master 0.9; plus a **convolver reverb** send (≈0.9s decaying-noise impulse, wet ≈0.16). Target −18 LUFS, all cues ≤~400ms, warm synthetic timbre (never skeuomorphic samples).

Three synthesis voices:
- **`note(freq, dur, peak, {bright, atk, click})`** — additive pluck: fundamental + two detuned unisons (±0.2–0.3%) + octave (0.18·bright) + fifth-above-octave (0.08·bright); a lowpass opens to `freq*5*bright` on attack and closes to ~`freq*1.6` over the decay; ADSR ≈ 8ms attack → decay to 0.55 sustain → exp release; optional filtered-noise attack transient (`click`).
- **`fm(freq, dur, peak, ratio, index, {atk, click})`** — sine carrier, sine modulator at `freq*ratio`, mod depth `freq*index` decaying to 15% over the note → metallic/glassy/hollow timbres.
- **`noise(dur, peak, center, Q)`** — bandpassed noise burst for transients/knocks.

The 7 cues (each a distinct timbre, recognizable eyes-closed):
| Cue | When | Recipe |
|---|---|---|
| **Summon** | orb wakes (with the 140ms visual snap) | glassy FM bell rising a fifth: `fm(587.33,…,3.5,2.2)` then `fm(880,…,3.5,1.8)` at +80ms |
| **Heard** | utterance commits hearing→doing | dry mallet tick: `noise(0.012, .16, 2400, 2.5)` + faint `note(1568, bright1.8)` |
| **Step complete** | a ledger step turns green | hollow woodblock: `noise(0.02,.14,800,4)` + `note(392, bright0.55)` |
| **Task resolved** | a multi-step run finishes | warm dark plucked fifth + tail: `note(146.83)` + `note(220)` + faint `note(293.66)` |
| **Armed / staged** | action staged, awaiting confirm | hollow FM, unresolved suspension: `fm(523.25,…,2,1.4)` then `fm(698.46, atk20ms)` |
| **Sent** | action leaves the machine | clean 3-note sine arpeggio down A5→D5→A4: `note(880)`,`note(698)`,`note(587)` |
| **Error** | failure | two low knocks + faint tritone buzz: `fm(155.56,…,1.41,1.2)` then `fm(146.83,…,1.41,1.4)` |

**Mix rules:** no cue while TTS is speaking *except* error; all cues duck under live mic input; volume follows OS; every cue category is optional in Settings → Voice → Sound cues.

---

## Implementation tiers (native Qt)

- **QSS (cheap — do everything here):** all colors/borders/radii/padding, buttons, chips, inputs, cards, list rows, scrollbars (6px overlay thumb white@14%, hover 22%, no track/arrows), menus, dialogs. The whole overlay + ~90% of Command Center.
- **QPainter (small regions only):** state dot + amplitude bars (one 60fps QTimer repainting a ≤32px rect), horizon header line+sun+glow (one gradient over the existing dot pass; glow only while live), day-arc / macro bars / sparklines (static; animate first paint only, 600ms sweep), the 140ms summon fade (QPropertyAnimation on windowOpacity). QPainter may animate small regions, never full windows.
- **QWebEngine (lazy, max one live instance, killed on hide):** the Cockpit/HUD orb only, and any future rich charts/news reader. Port the mock's `tick()` render loop verbatim. **Never on the Ctrl+Space path.**

Windows 11: sit **alongside** Fluent, not of it — no Mica/acrylic/Fluent corners (visual sovereignty is the point); but be DPI-aware, snap-layout friendly, and honor the OS reduced-motion flag.

---

## Files

- `mocks/*.dc.html` — the design references (+ `support.js` runtime; serve the folder to run). `El Fager - Index.dc.html` maps them all.
- `mocks/El Fager Design Language.dc.html` — the full 14-board spec (newest-first; board 8a = canon + component sheet + accessibility).
- `mocks/El Fager Design Language-print.dc.html` — print/PDF copy (landscape Letter, animations frozen).
- `tokens/el_fager_tokens.py` — **source of truth** for all tokens. `tokens/el-fager-tokens.qss` — base Qt stylesheet. `tokens/el-fager-tokens.css` — CSS custom properties for QWebEngine panels + the phone PWA.

> Note: the mocks predate a few late palette decisions in prose — when the CANON table or a token file disagrees with an older mock's inline colors, the token file wins. `El Fager Summon Prototype.dc.html` and `El Fager HUD Prototype.dc.html` are retained as historical (superseded by the Voice Overlay and the Cockpit respectively).
